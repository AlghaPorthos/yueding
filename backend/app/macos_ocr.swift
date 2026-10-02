import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count > 1 else { exit(2) }
let path = CommandLine.arguments[1]
let ext = (path as NSString).pathExtension.lowercased()

func recognize(_ cgImage: CGImage) -> (text: String, confidence: Double, lineCount: Int) {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    do {
        try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    } catch {
        return ("", 0, 0)
    }
    let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
    var lines: [String] = []
    var total = 0.0
    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        lines.append(candidate.string)
        total += Double(candidate.confidence)
    }
    let average = lines.isEmpty ? 0.0 : total / Double(lines.count)
    return (lines.joined(separator: "\n"), average, lines.count)
}

var pageTexts: [String] = []
if ext == "pdf" {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else { exit(3) }
    // 多页并发识别（最多 4 页同时在飞），结果按页序写回
    let group = DispatchGroup()
    let lock = NSLock()
    let gate = DispatchSemaphore(value: 4)
    var results = [(text: String, confidence: Double, lineCount: Int)](
        repeating: ("", 0, 0), count: doc.pageCount
    )
    for index in 0..<doc.pageCount {
        guard let page = doc.page(at: index) else { continue }
        group.enter()
        gate.wait()
        DispatchQueue.global(qos: .userInitiated).async {
            defer { gate.signal(); group.leave() }
            guard let tiff = page.thumbnail(of: CGSize(width: 1654, height: 2339), for: .mediaBox).tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: tiff),
                  let cgImage = bitmap.cgImage else { return }
            let recognized = recognize(cgImage)
            lock.lock()
            results[index] = recognized
            lock.unlock()
        }
    }
    group.wait()
    // 每页正文之后追加 \u{1F}CONF 元数据行（页码从 1 开始，保留 3 位小数）
    for (index, result) in results.enumerated() where result.lineCount > 0 {
        pageTexts.append(
            result.text + "\n\u{1F}CONF\t\(index + 1)\t" + String(format: "%.3f", result.confidence)
        )
    }
} else {
    guard let image = NSImage(contentsOfFile: path),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let cgImage = bitmap.cgImage else { exit(3) }
    let recognized = recognize(cgImage)
    var page = recognized.text
    if recognized.lineCount > 0 {
        page += "\n\u{1F}CONF\t1\t" + String(format: "%.3f", recognized.confidence)
    }
    // 图片分支总是带上像素尺寸，供低分辨率检查使用
    page += "\n\u{1F}SIZE\t\(cgImage.width)\t\(cgImage.height)"
    pageTexts.append(page)
}

let clean = pageTexts.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
print(clean.joined(separator: "\n\u{0C}\n"))
