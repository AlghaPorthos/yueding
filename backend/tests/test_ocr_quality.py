from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.main import create_app
from app.ocr import _parse_helper_output
from app.quality import ocr_quality_reasons


FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")
VISION_AVAILABLE = sys.platform == "darwin" and FONT_PATH.exists()


def render_png(width: int, height: int, lines: list[str], font_size: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    y = 30
    for line in lines:
        draw.text((36, y), line, fill="black", font=font)
        y += font_size + 20
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def post_file(app, content: bytes, filename: str, file_type: str, name: str = "扫描合同") -> dict:
    boundary = "ocrq-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {file_type}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    result: dict = {}

    def start_response(status, headers):
        result["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/contracts",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": f"multipart/form-data; boundary={boundary}",
        "wsgi.input": io.BytesIO(body),
    }
    output = b"".join(app(environ, start_response))
    payload = json.loads(output)
    payload["http_status"] = result.get("status")
    return payload


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "app.db")

    def tearDown(self):
        self.temp.cleanup()


class HelperOutputParsingTests(unittest.TestCase):
    def test_pdf_metadata_lines_are_stripped_and_confidences_kept_in_page_order(self):
        raw = "第一页正文\n\u001fCONF\t1\t0.912\n\f第二页正文\n\u001fCONF\t2\t0.401\n"
        pages, confidences, size = _parse_helper_output(raw, is_pdf=True)
        self.assertEqual(pages, ["第一页正文", "第二页正文"])
        self.assertEqual(confidences, [0.912, 0.401])
        self.assertIsNone(size)

    def test_pdf_page_without_confidence_defaults_to_zero(self):
        raw = "只有正文\n"
        pages, confidences, size = _parse_helper_output(raw, is_pdf=True)
        self.assertEqual(pages, ["只有正文"])
        self.assertEqual(confidences, [0.0])

    def test_image_output_yields_single_page_with_confidence_and_size(self):
        raw = "第一行\n第二行\n\u001fCONF\t1\t0.870\n\u001fSIZE\t1400\t700"
        pages, confidences, size = _parse_helper_output(raw, is_pdf=False)
        self.assertEqual(pages, ["第一行\n第二行"])
        self.assertEqual(confidences, [0.870])
        self.assertEqual(size, (1400, 700))

    def test_textless_image_keeps_only_size(self):
        raw = "\u001fCONF\t1\t0.000\n\u001fSIZE\t300\t200"
        pages, confidences, size = _parse_helper_output(raw, is_pdf=False)
        self.assertEqual(pages, [])
        self.assertEqual(confidences, [])
        self.assertEqual(size, (300, 200))


class OcrQualityRuleTests(unittest.TestCase):
    def test_low_average_confidence_flags_review(self):
        self.assertEqual(ocr_quality_reasons([0.3, 0.4]), ["low_ocr_confidence"])

    def test_good_confidence_has_no_flags(self):
        self.assertEqual(ocr_quality_reasons([0.9, 0.8]), [])

    def test_no_confidences_has_no_flags(self):
        self.assertEqual(ocr_quality_reasons([]), [])

    def test_small_image_dimension_flags_review(self):
        self.assertEqual(ocr_quality_reasons([0.9], (300, 200)), ["low_resolution_image"])

    def test_large_image_has_no_flags(self):
        self.assertEqual(ocr_quality_reasons([0.9], (1400, 700)), [])


@unittest.skipUnless(VISION_AVAILABLE, "requires macOS Vision OCR and the STHeiti font")
class VisionOcrUploadTests(AppTestCase):
    def test_clear_image_upload_is_ready_with_confidence_metrics(self):
        content = render_png(
            1400,
            700,
            [
                "房屋租赁合同",
                "押金为一个月租金，退租后七日内返还。",
                "未经出租人书面同意，承租人不得改造房屋。",
                "承租人提前退租，应提前三十日书面通知。",
            ],
            48,
        )
        payload = post_file(self.app, content, "contract.png", "image/png")
        self.assertEqual(payload["http_status"], 201, payload)
        self.assertEqual(payload["quality_status"], "ready", payload)
        self.assertEqual(payload["quality_reasons"], [])
        metrics = payload["quality_metrics"]
        self.assertEqual(metrics["ocr_engine"], "vision")
        self.assertEqual(metrics["extraction_method"], "vision-ocr")
        self.assertIsInstance(metrics["ocr_confidence_avg"], float)
        self.assertGreaterEqual(metrics["ocr_confidence_avg"], 0.55)
        self.assertEqual(metrics["image_size"], {"width": 1400, "height": 700})
        joined = "\n".join(page["text"] for page in payload["pages"])
        self.assertIn("押金", joined)
        self.assertNotIn("\x1f", joined)

    def test_low_resolution_image_is_needs_review(self):
        content = render_png(300, 200, ["押金为一个月租金", "退租后七日内返还"], 30)
        payload = post_file(self.app, content, "lowres.png", "image/png")
        self.assertEqual(payload["http_status"], 201, payload)
        self.assertEqual(payload["quality_status"], "needs_review", payload)
        self.assertIn("low_resolution_image", payload["quality_reasons"])
        metrics = payload["quality_metrics"]
        self.assertEqual(metrics["image_size"], {"width": 300, "height": 200})


class PatchedOcrQualityTests(AppTestCase):
    """Deterministic end-to-end checks of the OCR quality gates via monkeypatching."""

    def test_low_confidence_image_is_needs_review(self):
        fake_pages = ["押金为一个月租金，退租后七日内返还。"]
        with mock.patch(
            "app.main.ocr_document",
            return_value=(fake_pages, "vision", [0.31], (1200, 800)),
        ):
            payload = post_file(self.app, b"\x89PNG fake bytes", "scan.png", "image/png")
        self.assertEqual(payload["http_status"], 201, payload)
        self.assertEqual(payload["quality_status"], "needs_review", payload)
        self.assertIn("low_ocr_confidence", payload["quality_reasons"])
        metrics = payload["quality_metrics"]
        self.assertAlmostEqual(metrics["ocr_confidence_avg"], 0.31)
        self.assertEqual(metrics["ocr_engine"], "vision")
        self.assertEqual(metrics["image_size"], {"width": 1200, "height": 800})

    def test_confident_image_stays_ready(self):
        fake_pages = ["押金为一个月租金，退租后七日内返还。"]
        with mock.patch(
            "app.main.ocr_document",
            return_value=(fake_pages, "vision", [0.9], (1200, 800)),
        ):
            payload = post_file(self.app, b"\x89PNG fake bytes", "scan.png", "image/png")
        self.assertEqual(payload["http_status"], 201, payload)
        self.assertEqual(payload["quality_status"], "ready", payload)
        self.assertEqual(payload["quality_reasons"], [])

    def test_low_confidence_scanned_pdf_is_needs_review_without_image_size(self):
        fake_pages = ["押金为一个月租金，退租后七日内返还。"]
        with mock.patch(
            "app.main.ocr_document",
            return_value=(fake_pages, "vision", [0.42, 0.5], None),
        ):
            payload = post_file(self.app, b"not-a-real-pdf", "scan.pdf", "application/pdf")
        self.assertEqual(payload["http_status"], 201, payload)
        self.assertEqual(payload["quality_status"], "needs_review", payload)
        self.assertIn("low_ocr_confidence", payload["quality_reasons"])
        metrics = payload["quality_metrics"]
        self.assertAlmostEqual(metrics["ocr_confidence_avg"], 0.46)
        self.assertIsNone(metrics.get("image_size"))
        self.assertEqual(metrics["ocr_engine"], "vision")


if __name__ == "__main__":
    unittest.main()
