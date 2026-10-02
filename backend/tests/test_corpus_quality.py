"""质量门：backend/data/legal_corpus.jsonl 对资料包承诺的可执行校验。

承诺来源（法律文书Agent资料包/资料质量检查.md + manifest.json）：
- 资料快照 2026-10-02，已核对来源文件 31 份（manifest.items）；
- 维基文库来源按 wikisource_revision_time 标注版本，市场监管总局来源版本为 '2025'；
- 语料 95 条：住房租赁条例 第一条..第五十条（50）、民法典租赁章 25 条、
  市场监管总局城镇房屋租赁合同 第一条..第二十条（20）。
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
CORPUS_PATH = BACKEND_DIR / "data" / "legal_corpus.jsonl"
MANIFEST_PATH = BACKEND_DIR.parent / "法律文书Agent资料包" / "manifest.json"

SNAPSHOT_DATE = "2026-10-02"
MANIFEST_ITEM_COUNT = 31
CORPUS_RECORD_COUNT = 114
SAMR_VERSION = "2025"

# rental packs + per-contract-type rule packs (privacy / labor)
ALLOWED_CLAUSE_TYPES = {
    "deposit", "modification", "repair", "early_termination", "general",
    "processing_scope", "consent_withdrawal", "sharing_delegation",
    "retention_period", "security_breach_notice",
    "probation_period", "compensation", "overtime", "termination", "non_compete",
}

PIPL_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E4%B8%AA%E4%BA%BA%E4%BF%A1%E6%81%AF%E4%BF%9D%E6%8A%A4%E6%B3%95"
)
PIPL_ARTICLES = {6, 13, 14, 15, 19, 21, 23, 51, 57}
LABOR_LAW_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E5%8A%B3%E5%8A%A8%E5%90%88%E5%90%8C%E6%B3%95"
)
LABOR_LAW_ARTICLES = {19, 20, 22, 23, 24, 30, 31, 39, 40, 47}

_DIGITS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
_DIGIT_VALUES = {v: k for k, v in _DIGITS.items()}


def _chinese(n: int, embedded: bool = False) -> str:
    """1..99 的中文数字；嵌在百位之后时 10..19 需带“一”（七百一十、七百一十五）。"""
    if n < 10:
        return _DIGITS[n]
    if n < 20:
        return ("一十" if embedded else "十") + ("" if n == 10 else _DIGITS[n % 10])
    if n % 10 == 0:
        return _DIGITS[n // 10] + "十"
    return _DIGITS[n // 10] + "十" + _DIGITS[n % 10]


def _chinese_full(n: int) -> str:
    """1..999 的中文数字（法律条文编号，如 703 -> 七百零三、710 -> 七百一十）。"""
    if n < 100:
        return _chinese(n)
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return _DIGITS[hundreds] + "百"
    if rest < 10:
        return _DIGITS[hundreds] + "百零" + _DIGITS[rest]
    return _DIGITS[hundreds] + "百" + _chinese(rest, embedded=True)


def _article(n: int) -> str:
    return f"第{_chinese_full(n)}条"


def _article_number(text: str) -> int:
    """解析 '第七百二十一条' 形式的条文编号为整数。"""
    body = text
    for prefix in ("第",):
        assert body.startswith(prefix), f"非条文格式: {text!r}"
        body = body[len(prefix):]
    assert body.endswith("条"), f"非条文格式: {text!r}"
    body = body[:-1]
    if body.startswith("第"):
        body = body[1:]
    if len(body) <= 2 or body[0] in _DIGIT_VALUES and body[1] != "百":
        # 1..99：十、十五、二十、二十一……
        if body.startswith("十"):
            return 10 + _DIGIT_VALUES.get(body[1:], 0) if len(body) > 1 else 10
        if body.endswith("十"):
            return _DIGIT_VALUES[body[0]] * 10
        if "十" in body:
            tens, ones = body.split("十")
            return _DIGIT_VALUES[tens] * 10 + _DIGIT_VALUES[ones]
        return _DIGIT_VALUES[body]
    hundreds, rest = body.split("百", 1)
    value = _DIGIT_VALUES[hundreds] * 100
    if not rest:
        return value
    if rest.startswith("零"):
        return value + _DIGIT_VALUES[rest[1]]
    if rest.startswith("十"):
        return value + 10 + _DIGIT_VALUES.get(rest[1:], 0)
    if rest.endswith("十"):
        return value + _DIGIT_VALUES[rest[0]] * 10
    if "十" in rest:
        tens, ones = rest.split("十")
        return value + _DIGIT_VALUES[tens] * 10 + _DIGIT_VALUES[ones]
    return value + _DIGIT_VALUES[rest]


class CorpusQualityGates(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.records = [
            json.loads(line)
            for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.items_by_source = {item["source"]: item for item in cls.manifest["items"]}
        cls.by_source = {}
        for record in cls.records:
            cls.by_source.setdefault(record["source"], []).append(record)

    def test_manifest_matches_quality_doc(self):
        self.assertEqual(self.manifest["snapshot_date"], SNAPSHOT_DATE)
        self.assertEqual(len(self.manifest["items"]), MANIFEST_ITEM_COUNT)

    def test_record_count(self):
        self.assertEqual(len(self.records), CORPUS_RECORD_COUNT)

    def test_sources_and_versions_match_manifest(self):
        for record in self.records:
            source = record["source"]
            self.assertIn(
                source,
                self.items_by_source,
                f"语料 source 未见于 manifest: {source}",
            )
            item = self.items_by_source[source]
            if "wikisource_revision_time" in item:
                expected = item["wikisource_revision_time"]
            else:
                expected = SAMR_VERSION
            self.assertEqual(
                record["version"],
                expected,
                f"{record['article']} 版本号与 manifest 不一致",
            )

    def test_content_hash_recomputable(self):
        for record in self.records:
            payload = "{source}|{article}|{version}|{quote}".format(
                source=record["source"],
                article=record["article"],
                version=record["version"],
                quote=record["quote"],
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self.assertEqual(
                record["content_hash"],
                digest,
                f"{record['article']} content_hash 无法按约定公式复算",
            )

    def test_keys_unique_and_fields_nonempty(self):
        seen = set()
        for record in self.records:
            key = (record["source"], record["article"], record["version"])
            self.assertNotIn(key, seen, f"重复 (source, article, version): {key}")
            seen.add(key)
            for field in ("article", "version", "quote"):
                value = record[field]
                self.assertTrue(
                    isinstance(value, str) and value.strip(),
                    f"{record['article']} 字段 {field} 为空",
                )

    def test_clause_type_vocabulary(self):
        for record in self.records:
            self.assertIn(record["clause_type"], ALLOWED_CLAUSE_TYPES)

    def test_housing_lease_regulation_coverage(self):
        records = self.by_source.get(
            "https://zh.wikisource.org/wiki/%E4%BD%8F%E6%88%BF%E7%A7%9F%E8%B5%81%E6%9D%A1%E4%BE%8B", []
        )
        articles = {record["article"] for record in records}
        self.assertEqual(
            articles,
            {_article(n) for n in range(1, 51)},
            "住房租赁条例应完整覆盖 第一条..第五十条",
        )

    def test_civil_code_lease_chapter_coverage(self):
        records = self.by_source.get(
            "https://zh.wikisource.org/wiki/"
            "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E6%B0%91%E6%B3%95%E5%85%B8",
            [],
        )
        self.assertEqual(len(records), 25)
        chapter_lo, chapter_hi = 703, 734  # 民法典合同编租赁合同章
        for record in records:
            number = _article_number(record["article"])
            self.assertTrue(
                chapter_lo <= number <= chapter_hi,
                f"{record['article']} 超出租赁章 第七百零三条..第七百三十四条",
            )
            self.assertEqual(record["article"], _article(number))

    def test_samr_contract_sections_coverage(self):
        records = self.by_source.get(
            "https://htsfwb.samr.gov.cn/View?id=2340996b-882d-47a4-b74d-c30784628737", []
        )
        self.assertEqual(len(records), 20)
        headers = set()
        for record in records:
            header, _, title = record["article"].partition(" ")
            headers.add(header)
            self.assertTrue(
                header.startswith("第") and header.endswith("条"),
                f"SAMR 条目应以条文编号开头: {record['article']!r}",
            )
            self.assertTrue(title.strip(), f"SAMR 条目缺少节标题: {record['article']!r}")
        self.assertEqual(
            headers,
            {_article(n) for n in range(1, 21)},
            "市场监管总局合同应覆盖 第一条..第二十条 节标题",
        )

    def test_pipl_core_articles_coverage(self):
        records = self.by_source.get(PIPL_SOURCE, [])
        self.assertEqual(
            {record["article"] for record in records},
            {_article(n) for n in PIPL_ARTICLES},
            "个人信息保护法应精确覆盖精选核心条文",
        )

    def test_labor_law_core_articles_coverage(self):
        records = self.by_source.get(LABOR_LAW_SOURCE, [])
        self.assertEqual(
            {record["article"] for record in records},
            {_article(n) for n in LABOR_LAW_ARTICLES},
            "劳动合同法应精确覆盖精选核心条文",
        )


if __name__ == "__main__":
    unittest.main()
