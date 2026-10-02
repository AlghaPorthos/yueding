"""Local OCR adapter for image and scanned-PDF uploads on macOS.

The helper uses Apple's Vision framework when available.  PDF inputs are
rendered page by page with PDFKit and recognised concurrently (up to 4 pages
in flight).  The Swift source is precompiled once into a native binary under
``backend/.build`` and reused, which removes the per-call script-interpreter
overhead; if compilation is unavailable the source-script fallback still runs.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


_SOURCE = Path(__file__).with_name("macos_ocr.swift")
_BINARY = Path(__file__).resolve().parent.parent / ".build" / "macos-ocr"


def _helper_command() -> list[str] | None:
    if os.uname().sysname != "Darwin" or not _SOURCE.exists():
        return None
    source_mtime = _SOURCE.stat().st_mtime
    if _BINARY.exists() and _BINARY.stat().st_mtime >= source_mtime:
        return [str(_BINARY)]
    try:
        _BINARY.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            # 不开 -O：编译从 ~40s 降到数秒，Vision 识别才是耗时大头
            ["/usr/bin/swiftc", str(_SOURCE), "-o", str(_BINARY)],
            capture_output=True,
            timeout=60,
            check=True,
        )
        return [str(_BINARY)]
    except (OSError, subprocess.SubprocessError):
        return ["/usr/bin/swift", str(_SOURCE)]


def _run_helper(raw: bytes, filename: str, timeout: int) -> str:
    command = _helper_command()
    if not command:
        return ""
    suffix = Path(filename).suffix.lower() or ".png"
    image_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(raw)
            image_path = handle.name
        completed = subprocess.run(
            command + [image_path],
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
    if not raw:
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
