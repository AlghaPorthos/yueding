from __future__ import annotations

from collections.abc import Iterable


OCR_LOW_CONFIDENCE_THRESHOLD = 0.55
MIN_IMAGE_DIMENSION = 600


def ocr_quality_reasons(
    page_confidences: Iterable[float],
    image_size: tuple[int, int] | None = None,
) -> list[str]:
    """Flag OCR quality problems from helper-reported confidence and pixel size."""
    confidences = list(page_confidences)
    reasons: list[str] = []
    if image_size and (image_size[0] < MIN_IMAGE_DIMENSION or image_size[1] < MIN_IMAGE_DIMENSION):
        reasons.append("low_resolution_image")
    if confidences and sum(confidences) / len(confidences) < OCR_LOW_CONFIDENCE_THRESHOLD:
        reasons.append("low_ocr_confidence")
    return reasons


def assess_pages(pages: Iterable[str], *, source_type: str, ocr_engine: str | None = None) -> dict[str, object]:
    """Return deterministic ingestion quality metadata without guessing OCR text."""
    values = [page or "" for page in pages]
    if source_type.startswith("image/") and not ocr_engine:
        return {
            "status": "needs_review",
            "score": 0.0,
            "reasons": ["ocr_unavailable"],
            "method": "none",
            "page_count": 0,
            "character_count": 0,
        }
    if not values:
        return {
            "status": "needs_review",
            "score": 0.0,
            "reasons": ["no_extractable_text"],
            "method": ocr_engine or "text",
            "page_count": 0,
            "character_count": 0,
        }
    chars = sum(len(value.strip()) for value in values)
    replacement_chars = sum(value.count("\ufffd") for value in values)
    reasons: list[str] = []
    score = 1.0
    if chars < 10:
        reasons.append("low_text_coverage")
        score = min(score, 0.45)
    if replacement_chars:
        reasons.append("decode_replacement_chars")
        score = min(score, 0.35)
    return {
        "status": "ready" if not reasons else "needs_review",
        "score": round(score, 3),
        "reasons": reasons,
        "method": ocr_engine or "text",
        "page_count": len(values),
        "character_count": chars,
    }
