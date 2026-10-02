from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class Citation:
    page: int
    span_id: str
    quote: str

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if not self.quote or not self.quote.strip():
            raise ValueError("quote must not be empty")
        if not re.fullmatch(rf"p{self.page}-s\d+", self.span_id):
            raise ValueError("span_id does not match page")

    def model_dump(self) -> dict[str, Any]:
        return {"page": self.page, "span_id": self.span_id, "quote": self.quote}

    def dict(self) -> dict[str, Any]:
        return self.model_dump()
