"""Phase 2 非检索缺口补齐：同义词扩展、意图归一、索引版本戳。

- 口语查询（房东乱扣钱 / 提前搬走 / 修房子）经 SYNONYMS 扩展后能在真实
  语料 data/legal_corpus.jsonl 上命中对应正式表述的条文，reasoning 里带
  expanded_terms 与 index_version。
- 同义词只增不删：规则包关键词查询（改造 装修 改建 书面同意 改变房屋）
  不触发扩展，单个跨界 bigram 依旧过不了命中门槛——押金语料下
  modification 查询必须保持零命中（精确性回归）。
- ``_normalize_intent`` 从条款文本规则化提取金额/期限/条件/例外，未命中
  字段为 null，rule_ids 只列出真正提取到的维度。
- ``LegalIndex.content_version`` 是对 provisions 排序后的整体 sha256 前
  12 位：同一语料两次加载必须得到同一版本。
- /align 的 confirmed 记录上可见 intent 字段，reasoning 携带 index_version。
"""

from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.legal import LegalIndex
from app.main import _normalize_intent, create_app

CORPUS_PATH = Path(__file__).parent.parent / "data" / "legal_corpus.jsonl"

# 隔离真实 Jev 凭证：align 判定必须离线确定。
JUDGE_ENV_KEYS = ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "phase2-intent-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {file_type}\r\n\r\n'
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(app, method: str, path: str, *, body: bytes = b"", content_type: str = "") -> dict:
    result: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])

    path_only, _, query = path.partition("?")
    output = b"".join(app({
        "REQUEST_METHOD": method,
        "PATH_INFO": path_only,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }, start_response))
    result["body"] = json.loads(output)
    return result


class SynonymRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = LegalIndex.from_jsonl(CORPUS_PATH)

    def test_colloquial_deposit_query_hits_deposit_provisions_in_real_corpus(self) -> None:
        results = self.index.search("房东乱扣钱")
        self.assertTrue(results, "口语查询「房东乱扣钱」应在真实语料上命中条文")
        deposit_hits = [item for item in results if "押金" in item["quote"]]
        self.assertTrue(deposit_hits, "命中结果里应包含含「押金」的条文")
        self.assertEqual(results[0]["reasoning"]["retrieval"], "bigram-idf")
        self.assertIn("出租人", results[0]["reasoning"]["expanded_terms"])

    def test_colloquial_moveout_and_repair_queries_hit(self) -> None:
        moveout = self.index.search("我能提前搬走吗")
        self.assertTrue(moveout)
        self.assertIn("退租", moveout[0]["reasoning"]["expanded_terms"])
        self.assertTrue(any("退租" in item["quote"] or "提前" in item["quote"] for item in moveout[:3]))
        repair = self.index.search("修房子")
        self.assertTrue(repair)
        self.assertIn("房屋", repair[0]["reasoning"]["expanded_terms"])

    def test_exact_queries_are_not_expanded(self) -> None:
        results = self.index.search("租赁物安全")
        self.assertTrue(results)
        for item in results:
            self.assertEqual(item["reasoning"]["expanded_terms"], [])

    def test_synonym_expansion_keeps_cross_boundary_bigram_precision(self) -> None:
        # 精确性回归：只有一条押金条文时，modification 关键词查询里的单个
        # 跨界 bigram「房屋」不得触发命中（test_matters_projection 钉死的行为）；
        # 同一份语料下口语查询经同义词扩展可以命中。
        with TemporaryDirectory() as directory:
            corpus = Path(directory) / "legal.jsonl"
            corpus.write_text(json.dumps({
                "source": "示范法规",
                "article": "第十条",
                "version": "2026-01-01",
                "quote": "出租人收取押金的，应当约定押金的数额、返还时间以及扣减押金的情形。",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            index = LegalIndex.from_jsonl(corpus)
            self.assertEqual(index.search("改造 装修 改建 书面同意 改变房屋"), [])
            colloquial = index.search("房东扣押金不退")
            self.assertTrue(colloquial)
            self.assertIn("押金", colloquial[0]["quote"])
            self.assertIn("出租人", colloquial[0]["reasoning"]["expanded_terms"])


class IndexVersionTests(unittest.TestCase):
    def test_content_version_is_stable_across_loads(self) -> None:
        first = LegalIndex.from_jsonl(CORPUS_PATH)
        second = LegalIndex.from_jsonl(CORPUS_PATH)
        self.assertRegex(first.content_version, r"^[0-9a-f]{12}$")
        self.assertEqual(first.content_version, second.content_version)

    def test_content_version_changes_with_content(self) -> None:
        base = {"source": "示范法规", "article": "第十条", "version": "2026-01-01", "quote": "押金应当返还"}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legal.jsonl"
            path.write_text(json.dumps(base, ensure_ascii=False) + "\n", encoding="utf-8")
            original = LegalIndex.from_jsonl(path).content_version
            base["quote"] = "押金应当在退租后返还"
            path.write_text(json.dumps(base, ensure_ascii=False) + "\n", encoding="utf-8")
            changed = LegalIndex.from_jsonl(path).content_version
        self.assertNotEqual(original, changed)

    def test_search_reasoning_carries_index_version(self) -> None:
        results = LegalIndex.from_jsonl(CORPUS_PATH).search("押金 返还")
        self.assertTrue(results)
        for item in results:
            self.assertEqual(item["reasoning"]["index_version"], LegalIndex.from_jsonl(CORPUS_PATH).content_version)


class IntentNormalizationTests(unittest.TestCase):
    def test_amount_duration_condition_extracted(self) -> None:
        intent = _normalize_intent("押金为3000元，提前30日书面通知")
        self.assertEqual(intent["amount"], "3000元")
        self.assertEqual(intent["duration"], "30日")
        # 条件按优先级取书面类写法：该文本里的条件是「书面通知」。
        self.assertTrue(intent["condition"] and intent["condition"].startswith("书面"))
        self.assertIn("intent.amount.v1", intent["rule_ids"])
        self.assertIn("intent.duration.v1", intent["rule_ids"])
        self.assertIn("intent.condition.v1", intent["rule_ids"])
        self.assertNotIn("intent.exception.v1", intent["rule_ids"])
        self.assertIsNone(intent["exception"])

    def test_written_consent_and_exception_extracted(self) -> None:
        intent = _normalize_intent("未经出租人书面同意，承租人不得改造房屋，但双方另有约定的除外。")
        self.assertEqual(intent["condition"], "书面同意")
        self.assertIsNotNone(intent["exception"])

    def test_cjk_numerals_and_ratios(self) -> None:
        intent = _normalize_intent("承租人提前三十日通知，押金两个月内返还，按千分之五计违约金。")
        self.assertEqual(intent["duration"], "三十日")
        self.assertEqual(intent["amount"], "千分之")

    def test_no_match_yields_nulls_and_empty_rule_ids(self) -> None:
        intent = _normalize_intent("本合同一式两份，双方各执一份。")
        self.assertEqual(
            intent,
            {"rule_ids": [], "amount": None, "duration": None, "condition": None, "exception": None},
        )


class AlignIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self._old_jev = {key: os.environ.pop(key, None) for key in JUDGE_ENV_KEYS}
        self.app = create_app(Path(self.temp.name) / "app.db")

    def tearDown(self) -> None:
        for key, value in self._old_jev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def test_align_response_carries_intent_and_index_version(self) -> None:
        corpus = Path(self.temp.name) / "legal.jsonl"
        corpus.write_text(json.dumps({
            "source": "示范法规",
            "article": "第十条",
            "version": "2026-01-01",
            "quote": "押金为一个月租金，退租后七日内返还。",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)
        try:
            body, content_type = multipart("押金为3000元，提前30日书面通知退租。\n双方各执一份。".encode("utf-8"))
            uploaded = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type)["body"]
            response = request(
                self.app,
                "POST",
                f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        finally:
            if old is None:
                os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            else:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        findings = {item["type"]: item for item in payload["findings"]}
        deposit = findings["deposit"]
        self.assertEqual(deposit["alignment_status"], "matched")
        intent = deposit["intent"]
        self.assertEqual(intent["amount"], "3000元")
        self.assertEqual(intent["duration"], "30日")
        expected_version = LegalIndex.from_jsonl(corpus).content_version
        for item in payload["findings"]:
            self.assertEqual(item["reasoning"]["index_version"], expected_version)
        for provision in deposit["legal_provisions"]:
            self.assertEqual(provision["reasoning"]["index_version"], expected_version)


if __name__ == "__main__":
    unittest.main()
