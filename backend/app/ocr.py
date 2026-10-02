"""Local OCR adapter for image and scanned-PDF uploads on macOS.

The helper uses Apple's Vision framework when available.  PDF inputs are
rendered page by page with PDFKit and recognised concurrently (up to 4 pages
in flight).  The Swift source is precompiled once into a native binary under
``backend/.build`` and reused, which removes the per-call script-interpreter
overhead; if compilation is unavailable the source-script fallback still runs.

The helper appends machine-readable metadata lines after each page's text:
``\\u001FCONF\\t<page>\\t<avg confidence>`` and, for image inputs, a single
``\\u001FSIZE\\t<width>\\t<height>`` line.  They are parsed and stripped here
so callers only ever see clean text plus the numeric quality signals.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path


_SOURCE = Path(__file__).with_name("macos_ocr.swift")
_BINARY = Path(__file__).resolve().parent.parent / ".build" / "macos-ocr"

_META = "\u001f"
# NOTE: match the raw line — Python treats \x1f as whitespace, so line.strip()
# would eat the marker and the metadata would leak into page text.
_CONF_RE = re.compile(rf"^{_META}CONF\t(\d+)\t([0-9]*\.?[0-9]+)[ \t]*$")
_SIZE_RE = re.compile(rf"^{_META}SIZE\t(\d+)\t(\d+)[ \t]*$")


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


def _strip_meta(lines: list[str]) -> tuple[list[str], float | None, tuple[int, int] | None]:
    """Split helper output lines into body text, page confidence, and image size."""
    body: list[str] = []
    confidence: float | None = None
    size: tuple[int, int] | None = None
    for line in lines:
        conf_match = _CONF_RE.match(line)
        if conf_match:
            confidence = float(conf_match.group(2))
            continue
        size_match = _SIZE_RE.match(line)
        if size_match:
            size = (int(size_match.group(1)), int(size_match.group(2)))
            continue
        body.append(line)
    return body, confidence, size


def _parse_helper_output(text: str, *, is_pdf: bool) -> tuple[list[str], list[float], tuple[int, int] | None]:
    """Turn raw helper stdout into (pages, per-page confidences, image size)."""
    pages: list[str] = []
    confidences: list[float] = []
    size: tuple[int, int] | None = None
    if is_pdf:
        for chunk in text.split("\f"):
            body, confidence, chunk_size = _strip_meta(chunk.splitlines())
            if chunk_size:
                size = chunk_size
            content = "\n".join(body).strip()
            if content:
                pages.append(content)
                confidences.append(confidence if confidence is not None else 0.0)
        return pages, confidences, size
    body, confidence, image_size = _strip_meta(text.splitlines())
    content = "\n".join(body).strip()
    if not content:
        return [], [], image_size
    return [content], [confidence if confidence is not None else 0.0], image_size


def ocr_document(
    raw: bytes, filename: str = "upload.png"
) -> tuple[list[str], str, list[float], tuple[int, int] | None]:
    """Return (page texts, engine name, per-page confidences, image size).

    Confidences and the image size are ``[]``/``None`` when the helper did not
    report them; the result is empty on failure.
    """
    if not raw:
        return [], "", [], None
    is_pdf = Path(filename).suffix.lower() == ".pdf"
    text = _run_helper(raw, filename, timeout=120 if is_pdf else 35)
    if not text:
        return [], "", [], None
    pages, confidences, size = _parse_helper_output(text, is_pdf=is_pdf)
    if not pages:
        return [], "", [], size
    return pages, "vision", confidences, size


def ocr_image(
    raw: bytes, filename: str = "upload.png"
) -> tuple[list[str], str, list[float], tuple[int, int] | None]:
    return ocr_document(raw, filename)
