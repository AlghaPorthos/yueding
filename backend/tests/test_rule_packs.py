"""Per-contract-type rule packs: privacy / labor uploads get their own clause
cards while the rental path stays byte-identical.

- ``_detect_contract_type`` classifies an upload by deterministic keyword
  frequency over the parsed page text (no LLM).
- privacy / labor uploads are analyzed with PRIVACY_RULES / LABOR_RULES via
  RULE_PACKS; align and matters keep working because clause_type strings
  pass through unchanged.
- The rental findings below are a byte-identical golden capture of the
  pre-pack implementation (phase0 keyword analyzer) for the same upload.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from app.judge import JudgeResult
from app.llm import LLMRouter, StaticProvider
from app.main import (
    CLAUSE_ORDER,
    LABOR_CLAUSE_ORDER,
    LABOR_RULES,
    LEGAL_AID_CLAUSE_ORDER,
    PRIVACY_CLAUSE_ORDER,
    PRIVACY_RULES,
    create_app,
)

REAL_CORPUS = Path(__file__).resolve().parents[1] / "data" / "legal_corpus.jsonl"
PIPL_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E4%B8%AA%E4%BA%BA%E4%BF%A1%E6%81%AF%E4%BF%9D%E6%8A%A4%E6%B3%95"
)
LABOR_LAW_SOURCE = (
    "https://zh.wikisource.org/wiki/"
    "%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E5%8A%B3%E5%8A%A8%E5%90%88%E5%90%8C%E6%B3%95"
)

RENTAL_SAMPLE = "\n".join((
    "房屋租赁合同",
    "押金为一个月租金，退租后七日内返还。",
    "未经出租人书面同意，承租人不得改造房屋。",
    "房屋及其设施的自然损坏由出租人负责维修。",
    "承租人提前退租，应提前三十日通知并承担违约金。",
    "本合同一式两份，双方各执一份。",
))

PRIVACY_SAMPLE = "\n".join((
    "隐私政策",
    "我们收集您的个人信息，用于提供和改进产品与服务。",
    "您可以在账号设置中随时撤回同意，撤回后我们将停止相应处理。",
    "未经您的单独同意，我们不会与第三方共享您的个人信息，委托处理将约定目的与期限。",
    "您的个人信息保存期限以实现处理目的所必需的最短时间为限，到期后即删除。",
    "我们采取加密与访问控制等安全措施，发生个人信息泄露时将立即补救并通知您。",
))

LABOR_SAMPLE = "\n".join((
    "劳动合同",
    "甲方（用人单位）：某某科技有限公司",
    "乙方（劳动者）：某某",
    "本合同期限为三年，自2026年1月1日起至2028年12月31日止。",
    "甲方每月10日以货币形式足额支付乙方工资，不得克扣或者无故拖欠。",
    "试用期不超过六个月，试用期工资不低于转正工资的百分之八十。",
    "甲方安排加班的，应当支付加班费或者安排同等时间调休。",
    "乙方提前三十日书面通知甲方，可以解除本劳动合同。",
    "双方可以约定竞业限制条款，竞业限制期限不得超过二年，并按月支付经济补偿。",
    "甲方为乙方提供专项培训费用的，可以约定服务期及违约金。",
))

# Golden capture: findings the pre-pack rental implementation returned for
# RENTAL_SAMPLE. Serialized exactly like the app's wire format so the rental
# analyze output is pinned byte for byte. Re-captured for Phase 3: findings now
# carry deterministic severity/consequences/provenance (early_termination hits
# the 违约金 stance rule -> high; deposit 返还 -> medium; the rest low).
RENTAL_FINDINGS_BASELINE_JSON = "[{\"type\":\"deposit\",\"status\":\"confirmed\",\"confidence\":0.97,\"content\":\"押金为一个月租金，退租后七日内返还。\",\"contract_evidence\":[{\"page\":1,\"span_id\":\"p1-s1\",\"quote\":\"押金为一个月租金，退租后七日内返还。\"}],\"action_card\":{\"question\":\"押金退还期限、扣除条件和凭证是什么？\",\"impact\":\"核对押金金额、返还期限和扣除依据。\",\"suggested_revision\":\"补充押金金额、返还期限、扣除情形和结算凭证。\"},\"severity\":\"medium\",\"consequences\":[\"核对押金金额、返还期限和扣除依据。\"],\"provenance\":\"deterministic\",\"legal_provisions\":[],\"reasoning\":{\"rules\":[\"phase0-deposit-keyword-v1\"],\"retrieval\":\"phrase\"},\"disclaimer\":\"结果仅整理合同事实，不构成针对个案的法律意见\"},{\"type\":\"modification\",\"status\":\"confirmed\",\"confidence\":0.97,\"content\":\"未经出租人书面同意，承租人不得改造房屋。\",\"contract_evidence\":[{\"page\":1,\"span_id\":\"p1-s1\",\"quote\":\"未经出租人书面同意，承租人不得改造房屋。\"}],\"action_card\":{\"question\":\"哪些装修或改造需要书面同意，恢复责任由谁承担？\",\"impact\":\"在装修或添置设施前确认书面同意和恢复责任。\",\"suggested_revision\":\"明确可实施项目、书面同意流程和退租恢复标准。\"},\"severity\":\"low\",\"consequences\":[\"在装修或添置设施前确认书面同意和恢复责任。\"],\"provenance\":\"deterministic\",\"legal_provisions\":[],\"reasoning\":{\"rules\":[\"phase0-modification-keyword-v1\"],\"retrieval\":\"phrase\"},\"disclaimer\":\"结果仅整理合同事实，不构成针对个案的法律意见\"},{\"type\":\"repair\",\"status\":\"confirmed\",\"confidence\":0.97,\"content\":\"房屋及其设施的自然损坏由出租人负责维修。\",\"contract_evidence\":[{\"page\":1,\"span_id\":\"p1-s1\",\"quote\":\"房屋及其设施的自然损坏由出租人负责维修。\"}],\"action_card\":{\"question\":\"日常维修和设施故障的报修、响应及费用由谁负责？\",\"impact\":\"保存报修记录并确认费用和响应时限。\",\"suggested_revision\":\"补充维修责任、响应时限和费用承担规则。\"},\"severity\":\"low\",\"consequences\":[\"保存报修记录并确认费用和响应时限。\"],\"provenance\":\"deterministic\",\"legal_provisions\":[],\"reasoning\":{\"rules\":[\"phase0-repair-keyword-v1\"],\"retrieval\":\"phrase\"},\"disclaimer\":\"结果仅整理合同事实，不构成针对个案的法律意见\"},{\"type\":\"early_termination\",\"status\":\"confirmed\",\"confidence\":0.97,\"content\":\"承租人提前退租，应提前三十日通知并承担违约金。\",\"contract_evidence\":[{\"page\":1,\"span_id\":\"p1-s1\",\"quote\":\"承租人提前退租，应提前三十日通知并承担违约金。\"}],\"action_card\":{\"question\":\"提前退租的通知期限、违约金和例外情形是什么？\",\"impact\":\"需要提前退租时核对通知期限、费用和交接要求。\",\"suggested_revision\":\"明确提前解除通知期限、违约金上限和例外情形。\"},\"severity\":\"high\",\"consequences\":[\"需要提前退租时核对通知期限、费用和交接要求。\"],\"provenance\":\"deterministic\",\"legal_provisions\":[],\"reasoning\":{\"rules\":[\"phase0-early_termination-keyword-v1\"],\"retrieval\":\"phrase\"},\"disclaimer\":\"结果仅整理合同事实，不构成针对个案的法律意见\"}]"

PRIVACY_EXPECTED_QUOTES = {
    "processing_scope": "我们收集您的个人信息，用于提供和改进产品与服务。",
    "consent_withdrawal": "您可以在账号设置中随时撤回同意，撤回后我们将停止相应处理。",
    "sharing_delegation": "未经您的单独同意，我们不会与第三方共享您的个人信息，委托处理将约定目的与期限。",
    "retention_period": "您的个人信息保存期限以实现处理目的所必需的最短时间为限，到期后即删除。",
    "security_breach_notice": "我们采取加密与访问控制等安全措施，发生个人信息泄露时将立即补救并通知您。",
}

LABOR_EXPECTED_QUOTES = {
    "probation_period": "试用期不超过六个月，试用期工资不低于转正工资的百分之八十。",
    "compensation": "甲方每月10日以货币形式足额支付乙方工资，不得克扣或者无故拖欠。",
    "overtime": "甲方安排加班的，应当支付加班费或者安排同等时间调休。",
    "termination": "乙方提前三十日书面通知甲方，可以解除本劳动合同。",
    "non_compete": "双方可以约定竞业限制条款，竞业限制期限不得超过二年，并按月支付经济补偿。",
}


def multipart(text: bytes, *, filename: str = "doc.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "rule-pack-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {file_type}\r\n\r\n"
    ).encode("utf-8") + text + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def request(app: Any, method: str, path: str, *, body: bytes = b"", content_type: str = "") -> dict:
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": sys.stderr,
    }
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = int(status.split()[0])

    payload = b"".join(app(environ, start_response))
    return {"status": captured["status"], "body": json.loads(payload)}


class RulePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        # 隔离真实 Jev 凭证，保证 align 断言不依赖网络。
        self._old_jev = {k: os.environ.pop(k, None) for k in ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")}
        # Keep the rule-pack suite offline; semantic-provider paths are tested explicitly below.
        self.app = create_app(Path(self.temp.name) / "app.db", llm_router=LLMRouter([]))

    def tearDown(self) -> None:
        for key, value in self._old_jev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def upload(self, content: str, *, filename: str = "doc.txt") -> dict:
        body, content_type = multipart(content.encode("utf-8"), filename=filename)
        response = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type)
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def analyze(self, content: str, *, filename: str = "doc.txt") -> list[dict[str, Any]]:
        uploaded = self.upload(content, filename=filename)
        response = request(
            self.app,
            "POST",
            f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/analyze",
        )
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["body"]["quality_status"], "ready", response)
        return response["body"]["findings"]

    @contextmanager
    def real_corpus(self) -> Iterator[None]:
        old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(REAL_CORPUS)
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            else:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

    def test_rental_analyze_output_is_byte_identical(self) -> None:
        findings = self.analyze(RENTAL_SAMPLE, filename="lease.txt")
        canonical = json.dumps(findings, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(
            canonical,
            RENTAL_FINDINGS_BASELINE_JSON,
            "租房合同的 analyze 输出必须与旧实现逐字节一致",
        )
        self.assertEqual(tuple(finding["type"] for finding in findings), CLAUSE_ORDER)

    def test_privacy_policy_uses_privacy_pack(self) -> None:
        findings = self.analyze(PRIVACY_SAMPLE, filename="privacy.txt")
        self.assertEqual(tuple(finding["type"] for finding in findings), PRIVACY_CLAUSE_ORDER)
        for finding in findings:
            clause_type = finding["type"]
            with self.subTest(clause_type=clause_type):
                self.assertEqual(finding["status"], "confirmed", finding)
                self.assertEqual(finding["confidence"], 0.97, finding)
                expected_quote = PRIVACY_EXPECTED_QUOTES[clause_type]
                self.assertEqual(finding["content"], expected_quote, finding)
                self.assertEqual(
                    finding["contract_evidence"],
                    [{"page": 1, "span_id": "p1-s1", "quote": expected_quote}],
                    finding,
                )
                rule = PRIVACY_RULES[clause_type]
                self.assertEqual(
                    finding["action_card"],
                    {
                        "question": rule["question"],
                        "impact": rule["impact"],
                        "suggested_revision": rule["suggested_revision"],
                    },
                    finding,
                )
                self.assertEqual(
                    finding["reasoning"]["rules"],
                    [f"phase0-{clause_type}-keyword-v1"],
                    finding,
                )

    def test_labor_contract_uses_labor_pack(self) -> None:
        findings = self.analyze(LABOR_SAMPLE, filename="labor.txt")
        self.assertEqual(tuple(finding["type"] for finding in findings), LABOR_CLAUSE_ORDER)
        for finding in findings:
            clause_type = finding["type"]
            with self.subTest(clause_type=clause_type):
                self.assertEqual(finding["status"], "confirmed", finding)
                self.assertEqual(finding["confidence"], 0.97, finding)
                expected_quote = LABOR_EXPECTED_QUOTES[clause_type]
                self.assertEqual(finding["content"], expected_quote, finding)
                self.assertEqual(
                    finding["contract_evidence"],
                    [{"page": 1, "span_id": "p1-s1", "quote": expected_quote}],
                    finding,
                )
                rule = LABOR_RULES[clause_type]
                self.assertEqual(
                    finding["action_card"],
                    {
                        "question": rule["question"],
                        "impact": rule["impact"],
                        "suggested_revision": rule["suggested_revision"],
                    },
                    finding,
                )

    def test_neutral_document_stays_rental(self) -> None:
        findings = self.analyze("本合同一式两份，双方各执一份。")
        self.assertEqual(tuple(finding["type"] for finding in findings), CLAUSE_ORDER)
        self.assertTrue(all(finding["status"] == "not_found" for finding in findings))

    def test_general_legal_statute_is_not_misclassified_as_labor(self) -> None:
        statute = "\n".join((
            "中华人民共和国法律援助法",
            "第一章 总则",
            "法律援助是国家建立的公共法律服务制度。",
            "本法保障劳动者依法获得法律帮助。",
            "申请法律援助应由法律援助机构受理。",
        ))
        findings = self.analyze(statute, filename="law.md")
        self.assertEqual(tuple(finding["type"] for finding in findings), LEGAL_AID_CLAUSE_ORDER)
        self.assertTrue(any(finding["status"] == "confirmed" for finding in findings))

    def test_semantic_jev_classifier_can_override_keyword_candidate(self) -> None:
        class JudgeStub:
            def judge(self, state: str, questions: dict) -> JudgeResult:
                del state, questions
                return JudgeResult(
                    model="jev-test",
                    answers={"contract_type": {"type": "choice", "choice": "legal_aid"}},
                )

        self.app._judge_provider = lambda: JudgeStub()
        findings = self.analyze(
            "本合同载明工资、加班和劳动者义务，但内容是法律援助申请流程。",
            filename="law.md",
        )
        self.assertEqual(tuple(finding["type"] for finding in findings), LEGAL_AID_CLAUSE_ORDER)

    def test_semantic_llm_classifier_is_used_when_jev_unavailable(self) -> None:
        app = create_app(
            Path(self.temp.name) / "llm-classifier.db",
            llm_router=LLMRouter([StaticProvider({"contract_type": "legal_aid"})]),
        )
        app._judge_provider = lambda: None
        pages = [type("Page", (), {"number": 1, "text": "法律援助材料与劳动者相关，但应按援助机构申请流程处理。"})()]
        contract_type, engine = app._classify_contract_type(pages)
        self.assertEqual((contract_type, engine), ("legal_aid", "llm"))

    def test_semantic_classifier_failure_keeps_deterministic_candidate(self) -> None:
        app = create_app(
            Path(self.temp.name) / "llm-fallback.db",
            llm_router=LLMRouter([StaticProvider({"contract_type": "not-a-rule-pack"})]),
        )
        app._judge_provider = lambda: None
        pages = [type("Page", (), {"number": 1, "text": "中华人民共和国法律援助法。法律援助机构负责受理申请。"})()]
        contract_type, engine = app._classify_contract_type(pages)
        self.assertEqual((contract_type, engine), ("legal_aid", "deterministic"))

    def test_privacy_align_matches_real_pipl_corpus(self) -> None:
        with self.real_corpus():
            uploaded = self.upload(PRIVACY_SAMPLE, filename="privacy.txt")
            response = request(
                self.app,
                "POST",
                f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        self.assertEqual(response["status"], 200, response)
        alignments = response["body"]["findings"]
        self.assertEqual(tuple(item["type"] for item in alignments), PRIVACY_CLAUSE_ORDER)
        self.assertTrue(all(item["status"] == "confirmed" for item in alignments), alignments)
        # The phrase retrieval is type-agnostic: privacy clause queries surface
        # the curated 个人信息保护法 provisions from the real corpus.
        for item in alignments:
            self.assertTrue(item["legal_provisions"], item)
            self.assertEqual(item["legal_provisions"][0]["source"], PIPL_SOURCE, item)

    def test_labor_align_matches_real_labor_corpus(self) -> None:
        with self.real_corpus():
            uploaded = self.upload(LABOR_SAMPLE, filename="labor.txt")
            response = request(
                self.app,
                "POST",
                f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        self.assertEqual(response["status"], 200, response)
        alignments = response["body"]["findings"]
        self.assertEqual(tuple(item["type"] for item in alignments), LABOR_CLAUSE_ORDER)
        sources = {
            provision["source"]
            for item in alignments
            for provision in item["legal_provisions"]
        }
        self.assertIn(LABOR_LAW_SOURCE, sources, alignments)

    def test_matters_projects_privacy_findings(self) -> None:
        with self.real_corpus():
            uploaded = self.upload(PRIVACY_SAMPLE, filename="privacy.txt")
            request(
                self.app,
                "POST",
                f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
            response = request(
                self.app,
                "POST",
                f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/matters",
            )
        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        privacy_questions = {rule["question"] for rule in PRIVACY_RULES.values()}
        issue_questions = {issue["question"] for issue in payload["issues"]}
        self.assertTrue(
            issue_questions.issubset(privacy_questions),
            (issue_questions, privacy_questions),
        )
        actions = payload["actions"]
        self.assertEqual(len(actions), len(PRIVACY_RULES))
        self.assertTrue(all(action["kind"] == "negotiate" for action in actions))


if __name__ == "__main__":
    unittest.main()
