"""Local OCR adapter for image and scanned-PDF uploads on macOS.

The helper uses Apple's Vision framework when available.  PDF inputs are
rendered page by page with PDFKit and recognised the same way.  Keeping the
adapter optional preserves the deterministic ``needs_review`` path on hosts
without the framework.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


_HELPER = Path(__file__).with_name("macos_ocr.swift")


def _run_helper(raw: bytes, filename: str, timeout: int) -> str:
    suffix = Path(filename).suffix.lower() or ".png"
    image_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(raw)
            image_path = handle.name
        completed = subprocess.run(
            ["/usr/bin/swift", str(_HELPER), image_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except OSError:
                pass
    return (completed.stdout or "").replace("\r\n", "\n").strip()


def ocr_document(raw: bytes, filename: str = "upload.png") -> tuple[list[str], str]:
    """Return OCR page texts and engine name, or an empty result on failure."""
    if not raw or os.uname().sysname != "Darwin" or not _HELPER.exists():
        return [], ""
    is_pdf = Path(filename).suffix.lower() == ".pdf"
    text = _run_helper(raw, filename, timeout=120 if is_pdf else 35)
    if not text:
        return [], ""
    if is_pdf:
        return [page.strip() for page in text.split("\f") if page.strip()], "vision"
    return [line.strip() for line in text.splitlines() if line.strip()], "vision"


def ocr_image(raw: bytes, filename: str = "upload.png") -> tuple[list[str], str]:
    return ocr_document(raw, filename)
