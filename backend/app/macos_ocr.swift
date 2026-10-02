import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count > 1 else { exit(2) }
let path = CommandLine.arguments[1]
let ext = (path as NSString).pathExtension.lowercased()

func recognize(_ cgImage: CGImage) -> String {
    var output = ""
    let request = VNRecognizeTextRequest { request, error in
        if error != nil { exit(4) }
        let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
        let lines = observations.compactMap { $0.topCandidates(1).first?.string }
        output = lines.joined(separator: "\n")
    }
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    do {
        try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    } catch {
        exit(5)
    }
    return output
}

var pageTexts: [String] = []
if ext == "pdf" {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else { exit(3) }
    for index in 0..<doc.pageCount {
        guard let page = doc.page(at: index) else { continue }
        let thumb = page.thumbnail(of: CGSize(width: 1654, height: 2339), for: .mediaBox)
        guard let tiff = thumb.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let cgImage = bitmap.cgImage else { continue }
        pageTexts.append(recognize(cgImage))
    }
} else {
    guard let image = NSImage(contentsOfFile: path),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let cgImage = bitmap.cgImage else { exit(3) }
    pageTexts.append(recognize(cgImage))
}

let clean = pageTexts.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
print(clean.joined(separator: "\n\u{0C}\n"))
