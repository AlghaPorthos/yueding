from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import date

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """中文拆成重叠 bigram、英文数字按词切：比整句短语匹配的召回高一个量级。"""
    lowered = text.casefold()
    tokens: list[str] = []
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    tokens.extend(_WORD.findall(lowered))
    return tokens


@dataclass(frozen=True)
class LegalProvision:
    source: str
    article: str
    version: str
    quote: str
    jurisdiction: str = "中国大陆"
    effective_from: str | None = None
    effective_to: str | None = None
    provision_id: str | None = None
    source_kind: str = "external"

    @property
    def content_hash(self) -> str:
        canonical = "|".join((self.source, self.article, self.version, self.quote))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def is_effective_on(self, effective_on: str | None) -> bool:
        """Apply an optional ISO date filter without guessing date formats."""
        if not effective_on:
            return True
        try:
            selected = date.fromisoformat(effective_on)
            start = date.fromisoformat(self.effective_from) if self.effective_from else None
            end = date.fromisoformat(self.effective_to) if self.effective_to else None
        except (TypeError, ValueError):
            return False
        return (start is None or selected >= start) and (end is None or selected <= end)


class LegalIndex:
    """Small deterministic bigram/IDF index; it never invents provisions."""

    def __init__(self, provisions: list[LegalProvision] | None = None):
        self.provisions = list(provisions or [])
        self._doc_tokens: list[set[str]] | None = None
        self._df: dict[str, int] = {}

    def _build(self) -> None:
        if self._doc_tokens is not None:
            return
        self._doc_tokens = [
            set(_tokenize(f"{provision.source} {provision.article} {provision.quote}"))
            for provision in self.provisions
        ]
        for tokens in self._doc_tokens:
            for token in tokens:
                self._df[token] = self._df.get(token, 0) + 1

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "LegalIndex":
        records: list[LegalProvision] = []
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    records.append(LegalProvision(
                        source=str(item["source"]), article=str(item["article"]),
                        version=str(item["version"]), quote=str(item["quote"]),
                        jurisdiction=str(item.get("jurisdiction", "中国大陆")),
                        effective_from=item.get("effective_from"), effective_to=item.get("effective_to"),
                        provision_id=item.get("id") or item.get("provision_id"),
                        source_kind=str(item.get("source_kind", "external")),
                    ))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid legal corpus record at line {line_number}") from exc
        return cls(records)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        version: str | None = None,
        jurisdiction: str | None = None,
        effective_on: str | None = None,
    ) -> list[dict[str, object]]:
        normalized = " ".join(query.strip().casefold().split())
        if not normalized:
            return []
        self._build()
        tokens = list(dict.fromkeys(_tokenize(normalized)))
        total = len(self.provisions) or 1
        scored: list[tuple[float, LegalProvision, list[str]]] = []
        for index, provision in enumerate(self.provisions):
            if version is not None and provision.version != version:
                continue
            if jurisdiction is not None and provision.jurisdiction != jurisdiction:
                continue
            if not provision.is_effective_on(effective_on):
                continue
            doc_tokens = self._doc_tokens[index]
            matched = [token for token in tokens if token in doc_tokens]
            if not matched:
                continue
            # 稀有 bigram 权重高：押金这类特征词远比“什么/时候”这类常见字对得分贡献大
            score = sum(math.log((total + 1) / (self._df.get(token, 0) + 1)) + 1 for token in matched)
            scored.append((score, provision, matched))
        scored.sort(
            key=lambda row: (
                -row[0],
                row[1].source,
                row[1].article,
                row[1].version,
                row[1].jurisdiction,
                row[1].effective_from or "",
                row[1].provision_id or "",
            )
        )
        return [{
            "source": provision.source, "article": provision.article, "version": provision.version,
            "quote": provision.quote, "jurisdiction": provision.jurisdiction,
            "effective_from": provision.effective_from, "effective_to": provision.effective_to,
            "content_hash": provision.content_hash, "matched_terms": matched[:12],
            "provision_id": provision.provision_id,
            "source_kind": provision.source_kind,
            "reasoning": {"retrieval": "bigram-idf", "matched_terms": matched[:12]},
        } for _, provision, matched in scored[: max(0, limit)]]
