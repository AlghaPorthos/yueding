"""Regression tests for clause_type tagging in data/legal_corpus.jsonl.

Locks in the curated per-article overrides for the SAMR model contract
(第十五条 违约责任 / 第十六条 合同变更、终止 are tenant-termination clauses),
guards the 住房租赁条例 keyword tagging (第七条/第三十五条/第三十八条 are curated
to general), the markdown-heading bleed into the final Civil Code article,
and the corpus record count.
"""

import json
import unittest
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "data" / "legal_corpus.jsonl"

SAMR_SOURCE_KIND = "市场监管总局合同示范文本库"
PIPL_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E4%B8%AA%E4%BA%BA%E4%BF%A1%E6%81%AF%E4%BF%9D%E6%8A%A4%E6%B3%95"
)
LABOR_LAW_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E5%8A%B3%E5%8A%A8%E5%90%88%E5%90%8C%E6%B3%95"
)

# Curated per-article clause types for the per-contract-type rule packs:
# 个人信息保护法 and 劳动合同法 core articles carry the pack clause_type
# (see RULE_PACKS in app/main.py), tagged by scripts/build_legal_corpus.py.
PIPL_CLAUSE_TAGS = {
    "第六条": "processing_scope",
    "第十三条": "consent_withdrawal",
    "第十四条": "consent_withdrawal",
    "第十五条": "consent_withdrawal",
    "第十九条": "retention_period",
    "第二十一条": "sharing_delegation",
    "第二十三条": "sharing_delegation",
    "第五十一条": "security_breach_notice",
    "第五十七条": "security_breach_notice",
}
LABOR_LAW_CLAUSE_TAGS = {
    "第十九条": "probation_period",
    "第二十条": "probation_period",
    "第二十二条": "non_compete",
    "第二十三条": "non_compete",
    "第二十四条": "non_compete",
    "第三十条": "compensation",
    "第三十一条": "overtime",
    "第三十九条": "termination",
    "第四十条": "termination",
    "第四十七条": "termination",
}


def _load_rows() -> list[dict]:
    with CORPUS.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class CorpusTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _load_rows()
        cls.samr = {
            row["article"]: row
            for row in cls.rows
            if row["source_kind"] == SAMR_SOURCE_KIND
        }

    def test_record_count_is_stable(self):
        self.assertEqual(len(self.rows), 114)

    def test_samr_breach_clause_is_early_termination(self):
        row = self.samr["第十五条 违约责任"]
        self.assertEqual(row["clause_type"], "early_termination")

    def test_samr_change_termination_clause_is_early_termination(self):
        row = self.samr["第十六条 合同变更、终止"]
        self.assertEqual(row["clause_type"], "early_termination")

    def test_regulation_article_12_still_early_termination(self):
        matches = [row for row in self.rows if row["article"] == "第十二条"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["clause_type"], "early_termination")

    def test_regulation_retagged_articles_are_general(self):
        # Keyword heuristic mislabels: 第三十五条 (dispute resolution) matched
        # 押金, 第七条 (rental standards) and 第三十八条 (penalties) matched
        # 装修/装饰装修 keywords.
        expected = {
            "第七条": "消防",
            "第三十五条": "纠纷",
            "第三十八条": "处罚",
        }
        for article, anchor in expected.items():
            matches = [row for row in self.rows if row["article"] == article]
            with self.subTest(article=article):
                self.assertEqual(len(matches), 1)
                self.assertIn(anchor, matches[0]["quote"])
                self.assertEqual(matches[0]["clause_type"], "general")

    def test_regulation_modification_article_11_unchanged(self):
        # 第十一条 (tenant obligations incl. 改动承重结构) is a genuine
        # modification rule and keeps its keyword tag.
        matches = [row for row in self.rows if row["article"] == "第十一条"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["clause_type"], "modification")

    def test_civil_code_final_article_quote_has_no_markdown_heading(self):
        # 第七百三十四条 previously ended with the trailing chapter heading
        # ``#### 第十五章　融资租赁合同`` bled in from the source markdown.
        matches = [row for row in self.rows if row["article"] == "第七百三十四条"]
        self.assertEqual(len(matches), 1)
        self.assertNotIn("#", matches[0]["quote"])

    def test_samr_corrected_section_tags(self):
        expected = {
            "第五条 租金": "general",
            "第六条 押金": "deposit",
            "第七条 其他相关费用": "general",
            "第十条 房屋维修": "repair",
            "第十三条 甲方权利和义务": "general",
            "第十四条 乙方权利和义务": "general",
        }
        for article, clause_type in expected.items():
            with self.subTest(article=article):
                self.assertIn(article, self.samr)
                self.assertEqual(self.samr[article]["clause_type"], clause_type)

    def test_pipl_core_articles_carry_rule_pack_tags(self):
        rows = {row["article"]: row for row in self.rows if row["source"] == PIPL_SOURCE}
        self.assertEqual(set(rows), set(PIPL_CLAUSE_TAGS))
        for article, clause_type in PIPL_CLAUSE_TAGS.items():
            with self.subTest(article=article):
                self.assertEqual(rows[article]["clause_type"], clause_type)
                self.assertTrue(rows[article]["quote"].strip())

    def test_labor_law_core_articles_carry_rule_pack_tags(self):
        rows = {row["article"]: row for row in self.rows if row["source"] == LABOR_LAW_SOURCE}
        self.assertEqual(set(rows), set(LABOR_LAW_CLAUSE_TAGS))
        for article, clause_type in LABOR_LAW_CLAUSE_TAGS.items():
            with self.subTest(article=article):
                self.assertEqual(rows[article]["clause_type"], clause_type)
                self.assertTrue(rows[article]["quote"].strip())


if __name__ == "__main__":
    unittest.main()
