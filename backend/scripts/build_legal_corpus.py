#!/usr/bin/env python3
"""Build the deterministic legal corpus consumed by ``LegalIndex``.

Parses two files from the research data package and emits one JSONL record per
legal provision plus one per model-document clause. Provenance (source URL,
version, hash) is taken from ``manifest.json`` so every provision is
traceable, as ``missions/backend-full.md`` requires.

Run from the project root:

    PYTHONPATH=backend python3 backend/scripts/build_legal_corpus.py

Output: ``backend/data/legal_corpus.jsonl`` (also prints a short summary).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "法律文书Agent资料包"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "legal_corpus.jsonl"

REGULATION_TITLE = "住房租赁条例"
MODEL_CONTRACT_TITLE = "城镇房屋租赁合同_市场监管总局2025版"
PRIVACY_LAW_TITLE = "中华人民共和国个人信息保护法"
LABOR_LAW_TITLE = "中华人民共和国劳动合同法"

# Keyword priority used to tag each provision with a clause type. The first
# match wins; "general" is the fallback for provisions that touch none of the
# four MVP clause types but are still useful retrieval context.
CLAUSE_KEYWORDS = {
    "deposit": ("押金", "保证金", "押付", "退还押金"),
    "modification": ("装修", "装饰装修", "改造", "改建", "承重结构", "改动", "擅自改变", "改善", "增设他物"),
    "repair": ("维修", "修缮", "养护", "损坏", "故障"),
    "early_termination": ("解除", "退租", "腾退", "提前终止", "提前退租", "违约金", "收回房屋"),
}

# Curated per-article clause types for the SAMR model contract only
# (城镇房屋租赁合同_市场监管总局2025版). The keyword heuristic mislabels these
# fill-in sections because unrelated blanks mention 押金/解除 etc.; keys are
# the parsed ``第X条`` headers. Civil Code provisions keep the keyword path
# below unchanged.
MODEL_CONTRACT_CLAUSE_OVERRIDES = {
    "第五条": "general",  # 租金
    "第六条": "deposit",  # 押金
    "第七条": "general",  # 其他相关费用
    "第十条": "repair",  # 房屋维修
    "第十三条": "general",  # 甲方权利和义务
    "第十四条": "general",  # 乙方权利和义务
    "第十五条": "early_termination",  # 违约责任（提前收回房屋/提前退租）
    "第十六条": "early_termination",  # 合同变更、终止
}

# Curated per-article clause types for 住房租赁条例 only. The keyword
# heuristic mislabels these articles because their text mentions 押金/装修
# etc. while they actually cover rental standards, dispute resolution, and
# penalties. Scoped by title in ``_parse_regulation`` because
# ``_flush_article`` is shared with the Civil Code parse; Civil Code articles
# in the kept range are 第七百零X-style strings, so the keys cannot collide.
REGULATION_CLAUSE_OVERRIDES = {
    "第七条": "general",  # 用于出租的住房应符合建筑、消防、燃气等要求
    "第三十五条": "general",  # 押金返还、住房维修、住房腾退等纠纷的解决途径
    "第三十八条": "general",  # 罚则
}

# Curated core articles for the per-contract-type rule packs. Keys are parsed
# ``第X条`` headers from the wikisource markdown; values are the clause_type
# used by the matching pack in app/main.py (consent_withdrawal etc.). Only
# these articles enter the corpus, so every tag is curated, never guessed.
PRIVACY_LAW_CLAUSE_OVERRIDES = {
    "第六条": "processing_scope",  # 目的明确、最小必要
    "第十三条": "consent_withdrawal",  # 处理合法性基础（含同意）
    "第十四条": "consent_withdrawal",  # 同意须充分知情、自愿明确
    "第十五条": "consent_withdrawal",  # 撤回同意
    "第十九条": "retention_period",  # 保存期限最短必要
    "第二十一条": "sharing_delegation",  # 委托处理
    "第二十三条": "sharing_delegation",  # 向其他处理者提供需单独同意
    "第五十一条": "security_breach_notice",  # 安全保障措施
    "第五十七条": "security_breach_notice",  # 泄露、篡改、丢失通知
}

LABOR_LAW_CLAUSE_OVERRIDES = {
    "第十九条": "probation_period",  # 试用期上限
    "第二十条": "probation_period",  # 试用期工资下限
    "第二十二条": "non_compete",  # 服务期约定
    "第二十三条": "non_compete",  # 保密与竞业限制约定
    "第二十四条": "non_compete",  # 竞业限制范围与期限
    "第三十条": "compensation",  # 劳动报酬及时足额支付
    "第三十一条": "overtime",  # 加班限制与加班费
    "第三十九条": "termination",  # 用人单位过失性解除
    "第四十条": "termination",  # 无过失性解除与代通知金
    "第四十七条": "termination",  # 经济补偿计算
}

_SECTION_NUMBER_RE = re.compile(r"^(第[零一二三四五六七八九十百]+条)")

_CN_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def _to_iso_date(text: str) -> str | None:
    """Convert a Chinese 'YYYY年M月D日' string to ISO 'YYYY-MM-DD'."""

    match = _CN_DATE_RE.search(text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _clause_type(text: str) -> str:
    for clause, keywords in CLAUSE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return clause
    return "general"


_CN_ONES = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_small_int(text: str) -> int:
    """Convert a Chinese numeral in 0..34 (零/一/一十/十五/三十四) to an int."""

    if text in _CN_ONES:
        return _CN_ONES[text]
    match = re.match(r"^([一二三四五六七八九])十(.?[零一二三四五六七八九])?$", text)
    if match:
        return _CN_ONES[match.group(1)] * 10 + _CN_ONES.get(match.group(2) or "零", 0)
    return 0


def _cn_article_number(article: str) -> int | None:
    """Convert a Chinese article number (e.g. '第七百一十二条') to its integer."""

    match = re.match(r"^第(.+)条$", article)
    if not match:
        return None
    numeral = match.group(1)
    if numeral.startswith("七百"):
        return 700 + _cn_small_int(numeral[len("七百"):])
    return None

def _cn_article_int(article: str) -> int | None:
    """Convert a Chinese article number up to 九百九十九 to its integer.

    Unlike ``_cn_article_number`` (kept verbatim for the pinned Civil Code
    range filter), this handles the 零 separator (第七百零三条 -> 703) needed
    for the younger laws whose articles stay below one hundred.
    """
    match = re.match(r"^第(.+)条$", article)
    if not match:
        return None
    numeral = match.group(1)
    total = 0
    if "百" in numeral:
        hundreds, _, numeral = numeral.partition("百")
        total += _CN_ONES[hundreds] * 100
    if numeral:
        total += _cn_small_int(numeral.lstrip("零"))
    return total or None


def _load_manifest() -> dict:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    by_title = {item["title"]: item for item in manifest["items"]}
    return by_title


def _provision(
    *,
    source: str,
    source_kind: str,
    article: str,
    version: str,
    effective_from: str | None,
    quote: str,
    clause_type: str,
    jurisdiction: str = "中国大陆",
) -> dict:
    canonical = "|".join((source, article, version, quote))
    return {
        "source": source,
        "source_kind": source_kind,
        "article": article,
        "version": version,
        "jurisdiction": jurisdiction,
        "effective_from": effective_from,
        "effective_to": None,
        "provision_id": None,
        "clause_type": clause_type,
        "quote": quote,
        "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


_ARTICLE_RE = re.compile(r"^第([零一二三四五六七八九十百]+)条[　 ]")


def _parse_regulation(title: str, entry: dict, clause_overrides: dict[str, str] | None = None) -> list[dict]:
    """Extract every ``第X条`` article with its following paragraphs."""

    text = (PACKAGE / f"维基文库_法律法规/{title}.md").read_text(encoding="utf-8")
    effective_from = None
    match = re.search(r"(?:本法|本条例)自(.+?)日起施行", text)
    if match:
        effective_from = _to_iso_date(match.group(1))

    # Per-article overrides default to the 住房租赁条例 curation; the Civil
    # Code parse shares _flush_article without overrides, and the per-type
    # rule-pack laws pass their own curated maps explicitly.
    if clause_overrides is None:
        clause_overrides = REGULATION_CLAUSE_OVERRIDES if title == REGULATION_TITLE else None

    lines = text.splitlines()
    provisions: list[dict] = []
    current: list[str] | None = None
    current_article: str | None = None
    for line in lines:
        article_match = _ARTICLE_RE.match(line.strip())
        if article_match:
            if current is not None and any(part.strip() for part in current):
                provisions.append(_flush_article(current_article, current, entry, effective_from, clause_overrides=clause_overrides))
            current_article = f"第{article_match.group(1)}条"
            current = [line.strip()[len(current_article):].strip()]
            continue
        if line.startswith("#"):  # any heading level breaks the current article (民法典 chapters are ``#### ``)
            if current is not None and any(part.strip() for part in current):
                provisions.append(_flush_article(current_article, current, entry, effective_from, clause_overrides=clause_overrides))
            current = None
            current_article = None
            continue
        if current is not None:
            current.append(line)
    if current is not None and any(part.strip() for part in current):
        provisions.append(_flush_article(current_article, current, entry, effective_from, clause_overrides=clause_overrides))
    return provisions


def _flush_article(
    article: str | None,
    paragraphs: list[str],
    entry: dict,
    effective_from: str | None,
    clause_overrides: dict[str, str] | None = None,
) -> dict:
    body = "\n".join(part.strip() for part in paragraphs if part.strip())
    clause_type = clause_overrides.get(article) if clause_overrides else None
    if clause_type is None:
        clause_type = _clause_type(body)
    return _provision(
        source=entry["source"],
        source_kind=entry["source_kind"],
        article=article or "未知条文",
        version=entry["wikisource_revision_time"],
        effective_from=effective_from,
        quote=body,
        clause_type=clause_type,
    )


def _parse_curated_law(title: str, entry: dict, clause_overrides: dict[str, str]) -> list[dict]:
    """Parse a wikisource law and keep only the curated core articles.

    ``clause_overrides`` doubles as the keep-list: every key is a ``第X条``
    header to keep, and its value is the curated clause_type. Parsed from the
    real law text in the 资料包; nothing is typed in by hand.
    """
    kept = [
        provision
        for provision in _parse_regulation(title, entry, clause_overrides=clause_overrides)
        if provision["article"] in clause_overrides
    ]
    missing = set(clause_overrides) - {provision["article"] for provision in kept}
    if missing:
        raise ValueError(f"{title}: curated articles missing from source: {sorted(missing)}")
    return kept


_SECTION_RE = re.compile(r"^####\s+(第[零一二三四五六七八九十百]+条[^\n]*)")


def _parse_model_contract(title: str, entry: dict) -> list[dict]:
    """Extract each ``#### 第X条 ...`` section body as a model clause."""

    text = (PACKAGE / f"官方_示范文书/{title}.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    provisions: list[dict] = []
    current_header: str | None = None
    current_body: list[str] = []
    for line in lines:
        header_match = _SECTION_RE.match(line)
        if header_match:
            if current_header is not None and any(part.strip() for part in current_body):
                provisions.append(_flush_section(current_header, current_body, entry))
            current_header = header_match.group(1).strip()
            current_body = []
            continue
        if current_header is not None:
            current_body.append(line)
    if current_header is not None and any(part.strip() for part in current_body):
        provisions.append(_flush_section(current_header, current_body, entry))
    return provisions


def _flush_section(header: str, paragraphs: list[str], entry: dict) -> dict:
    body = "\n".join(part.strip() for part in paragraphs if part.strip())
    article = header
    number = _SECTION_NUMBER_RE.match(header)
    clause_type = MODEL_CONTRACT_CLAUSE_OVERRIDES.get(number.group(0)) if number else None
    if clause_type is None:
        clause_type = _clause_type(header + " " + body)
    return _provision(
        source=entry["source"],
        source_kind=entry["source_kind"],
        article=article,
        version=entry.get("wikisource_revision_time", "2025"),
        effective_from=None,
        quote=body,
        clause_type=clause_type,
    )


def main() -> int:
    manifest = _load_manifest()
    regulation_entry = manifest.get(REGULATION_TITLE)
    model_entry = manifest.get(MODEL_CONTRACT_TITLE)
    if regulation_entry is None or model_entry is None:
        print(f"manifest missing entries: regulation={regulation_entry is None} model={model_entry is None}", file=sys.stderr)
        return 2

    civil_code_entry = manifest.get("中华人民共和国民法典")
    civil_code_provisions: list[dict] = []
    if civil_code_entry is not None:
        for provision in _parse_regulation("中华人民共和国民法典", civil_code_entry):
            number = _cn_article_number(provision["article"])
            if number is not None and 703 <= number <= 734:
                civil_code_provisions.append(provision)

    privacy_entry = manifest.get(PRIVACY_LAW_TITLE)
    labor_entry = manifest.get(LABOR_LAW_TITLE)
    rule_pack_provisions: list[dict] = []
    for title, entry, overrides in (
        (PRIVACY_LAW_TITLE, privacy_entry, PRIVACY_LAW_CLAUSE_OVERRIDES),
        (LABOR_LAW_TITLE, labor_entry, LABOR_LAW_CLAUSE_OVERRIDES),
    ):
        if entry is not None:
            rule_pack_provisions.extend(_parse_curated_law(title, entry, overrides))

    provisions = [
        *_parse_regulation(REGULATION_TITLE, regulation_entry),
        *_parse_model_contract(MODEL_CONTRACT_TITLE, model_entry),
        *civil_code_provisions,
        *rule_pack_provisions,
    ]
    # Drop model-contract signature/attachment boilerplate (e.g. the trailing
    # "其他" section) that keyword tagging mislabels as a substantive clause.
    provisions = [
        p
        for p in provisions
        if not (
            ("法定代表人" in p["quote"] or "签名/盖章" in p["quote"])
            and "附件" in p["quote"]
        )
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for provision in provisions:
        record = {
            "source": provision["source"],
            "source_kind": provision["source_kind"],
            "article": provision["article"],
            "version": provision["version"],
            "jurisdiction": provision["jurisdiction"],
            "effective_from": provision["effective_from"],
            "effective_to": provision["effective_to"],
            "provision_id": provision["provision_id"],
            "clause_type": provision["clause_type"],
            "quote": provision["quote"],
            "content_hash": provision["content_hash"],
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False))

    # Atomic replace so a concurrent reader (e.g. LegalIndex in another
    # process) never observes a partially written corpus file.
    tmp_path = OUTPUT.parent / (OUTPUT.name + ".tmp")
    tmp_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    os.replace(tmp_path, OUTPUT)

    by_kind: dict[str, int] = {}
    by_clause: dict[str, int] = {}
    for record in records:
        by_kind[record["source_kind"]] = by_kind.get(record["source_kind"], 0) + 1
        by_clause[record["clause_type"]] = by_clause.get(record["clause_type"], 0) + 1
    print(f"\nWrote {len(records)} provisions to {OUTPUT}")
    print(f"  by source_kind: {by_kind}")
    print(f"  by clause_type: {by_clause}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
