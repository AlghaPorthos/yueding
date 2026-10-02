import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count > 1 else { exit(2) }
let path = CommandLine.arguments[1]
let ext = (path as NSString).pathExtension.lowercased()

func recognize(_ cgImage: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    do {
        try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    } catch {
        return ""
    }
    let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
    return observations.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

var pageTexts: [String] = []
if ext == "pdf" {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else { exit(3) }
    // 多页并发识别（最多 4 页同时在飞），结果按页序写回
    let group = DispatchGroup()
    let lock = NSLock()
    let gate = DispatchSemaphore(value: 4)
    var results = [String](repeating: "", count: doc.pageCount)
    for index in 0..<doc.pageCount {
        guard let page = doc.page(at: index) else { continue }
        group.enter()
        gate.wait()
        DispatchQueue.global(qos: .userInitiated).async {
            defer { gate.signal(); group.leave() }
            guard let tiff = page.thumbnail(of: CGSize(width: 1654, height: 2339), for: .mediaBox).tiffRepresentation,
                  let bitmap = NSBitmapImageRep(data: tiff),
                  let cgImage = bitmap.cgImage else { return }
            let text = recognize(cgImage)
            lock.lock()
            results[index] = text
            lock.unlock()
        }
    }
    group.wait()
    pageTexts = results
} else {
    guard let image = NSImage(contentsOfFile: path),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let cgImage = bitmap.cgImage else { exit(3) }
    pageTexts.append(recognize(cgImage))
}

let clean = pageTexts.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
print(clean.joined(separator: "\n\u{0C}\n"))
