"""Projection of stored findings + alignments into the protocol output shape.

``POST /v1/contracts/{cid}/versions/{vid}/matters`` deterministically maps the
phase-0 findings and phase-2 ``legal_alignments`` rows into the 法律事项工作台
输入输出协议 ``output`` contract:

- ``extracted_facts``: confirmed findings -> ``supported`` with ``source_refs``
  built from the contract_evidence page/quote; quality-blocked (needs_review)
  findings -> ``user_only`` with no refs at all.
- ``issues``: clauses whose alignment is not_found/needs_review -> the RULES
  question, ``rule_refs`` from the alignment's legal_provisions source+article,
  status ``supported`` when provisions are recorded, else ``unknown``.
- ``missing_items`` mapped from stored quality reasons: an OCR-blocked upload
  asks for a clearer original or a text version; ``low_text_coverage`` asks
  for 补充合同页.
- ``actions``: one ``negotiate`` action per confirmed action_card, always with
  ``requires_user_approval`` true (all external messages/signing/submissions
  require user confirmation).
- ``drafts``: ``[]`` — this path never calls an LLM.

Before emission each citation quote is re-validated as a substring of the
stored page text and each cited article as present in the loaded corpus under
its recorded version; mismatches downgrade that fact from ``supported`` rather
than emitting an unverifiable conclusion.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from app.main import RULES, create_app

DEPOSIT_LINE = "押金为一个月租金，退租后七日内返还。"
MODIFICATION_LINE = "未经出租人书面同意，承租人不得改造房屋。"
EARLY_TERMINATION_LINE = "承租人提前退租，应提前三十日通知并承担违约金。"
NEUTRAL_LINE = "本合同一式两份，双方各执一份。"

DEPOSIT_PROVISION = {
    "source": "示范法规",
    "article": "第十条",
    "version": "2026-01-01",
    "quote": f"房屋租赁中，{DEPOSIT_LINE}",
}

# Keeping the optional Jev judge out of these tests: /align refines results
# through it when a key is configured, which would make the projection input
# nondeterministic on developer machines that export one.
JUDGE_ENV_KEYS = ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "matters-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {file_type}\r\n\r\n'
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(app: Any, method: str, path: str, *, body: bytes = b"", content_type: str = "") -> dict:
    result: dict[str, Any] = {}

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


class MattersProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "app.db")
        self._saved_judge_env = {key: os.environ.pop(key, None) for key in JUDGE_ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved_judge_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    @contextmanager
    def _corpus(self, records: list[dict[str, Any]]) -> Iterator[Path]:
        path = Path(self.temp.name) / "legal.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(path)
        try:
            yield path
        finally:
            if old is None:
                os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            else:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

    def upload(self, content: str, *, filename: str = "lease.txt", file_type: str = "text/plain") -> dict:
        body, content_type = multipart(content.encode("utf-8"), filename=filename, file_type=file_type)
        response = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type)
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def align(self, contract_id: str, version_id: str) -> dict:
        return request(self.app, "POST", f"/v1/contracts/{contract_id}/versions/{version_id}/align")

    def matters(self, contract_id: str, version_id: str) -> dict:
        return request(self.app, "POST", f"/v1/contracts/{contract_id}/versions/{version_id}/matters")

    def _upload_and_align(
        self,
        content: str,
        *,
        filename: str = "lease.txt",
        file_type: str = "text/plain",
    ) -> dict:
        uploaded = self.upload(content, filename=filename, file_type=file_type)
        response = self.align(uploaded["contract_id"], uploaded["version_id"])
        self.assertEqual(response["status"], 200, response)
        return uploaded

    def _execute(self, query: str, *params: object) -> None:
        with closing(sqlite3.connect(Path(self.temp.name) / "app.db")) as connection:
            connection.execute(query, params)
            connection.commit()

    def test_matters_projects_confirmed_findings_into_supported_facts(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]):
            uploaded = self._upload_and_align("\n".join((
                DEPOSIT_LINE,
                MODIFICATION_LINE,
                EARLY_TERMINATION_LINE,
            )))
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        contract_lines = {DEPOSIT_LINE, MODIFICATION_LINE, EARLY_TERMINATION_LINE}

        facts = payload["extracted_facts"]
        self.assertEqual(len(facts), 3)
        for fact in facts:
            self.assertEqual(fact["status"], "supported", fact)
            self.assertEqual(len(fact["source_refs"]), 1, fact)
            ref = fact["source_refs"][0]
            self.assertEqual(ref["page"], 1, fact)
            self.assertTrue(ref["doc_id"], fact)
            self.assertIn(ref["quote"], contract_lines)
        self.assertEqual(
            {ref["quote"] for fact in facts for ref in fact["source_refs"]},
            contract_lines,
        )

        issues = payload["issues"]
        self.assertEqual(
            {issue["question"] for issue in issues},
            {RULES[key]["question"] for key in ("modification", "early_termination", "repair")},
        )
        for issue in issues:
            self.assertEqual(issue["status"], "unknown", issue)
            self.assertEqual(issue["rule_refs"], [], issue)

        actions = payload["actions"]
        self.assertEqual(len(actions), 3)
        for action in actions:
            self.assertEqual(action["kind"], "negotiate", action)
            self.assertIs(action["requires_user_approval"], True, action)
            self.assertTrue(isinstance(action["text"], str) and action["text"].strip(), action)

        self.assertEqual(payload["missing_items"], [])
        self.assertEqual(payload["drafts"], [])

    def test_quality_blocked_findings_project_to_user_only_facts_without_refs(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]):
            uploaded = self._upload_and_align("扫描件图片内容", filename="scan.png", file_type="image/png")
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]

        facts = payload["extracted_facts"]
        self.assertEqual(len(facts), 4)
        for fact in facts:
            self.assertEqual(fact["status"], "user_only", fact)
            self.assertEqual(fact["source_refs"], [], fact)

        self.assertEqual(
            {issue["question"] for issue in payload["issues"]},
            {RULES[key]["question"] for key in RULES},
        )
        for issue in payload["issues"]:
            self.assertEqual(issue["status"], "unknown", issue)
            self.assertEqual(issue["rule_refs"], [], issue)

        self.assertEqual(payload["actions"], [])
        self.assertEqual(payload["drafts"], [])
        self.assertTrue(
            any("更清晰" in item and "文字版" in item for item in payload["missing_items"]),
            payload["missing_items"],
        )

    def test_low_text_coverage_missing_item_asks_for_contract_pages(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]):
            uploaded = self._upload_and_align("押金")
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertIn("补充合同页", payload["missing_items"])
        for fact in payload["extracted_facts"]:
            self.assertEqual(fact["status"], "user_only", fact)
            self.assertEqual(fact["source_refs"], [], fact)

    def test_citation_quote_missing_from_page_text_downgrades_fact(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]) as corpus_path:
            uploaded = self._upload_and_align(f"{DEPOSIT_LINE}\n{NEUTRAL_LINE}")
            self._execute(
                "UPDATE document_pages SET text = ? WHERE version_id = ?",
                "本页内容已损坏，原文无法核对。",
                uploaded["version_id"],
            )
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual([fact for fact in payload["extracted_facts"] if fact["status"] == "supported"], [])
        downgraded = [fact for fact in payload["extracted_facts"] if "押金" in fact["text"]]
        self.assertEqual(len(downgraded), 1, payload["extracted_facts"])
        self.assertEqual(downgraded[0]["status"], "user_only")
        self.assertEqual(downgraded[0]["source_refs"], [])

    def test_cited_article_missing_from_corpus_downgrades_fact(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]) as corpus_path:
            uploaded = self._upload_and_align(f"{DEPOSIT_LINE}\n{NEUTRAL_LINE}")
            corpus_path.write_text(
                json.dumps(
                    {
                        "source": "示范法规",
                        "article": "第十条",
                        "version": "2027-07-01",
                        "quote": "押金事项按新版租赁条例执行。",
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual([fact for fact in payload["extracted_facts"] if fact["status"] == "supported"], [])
        downgraded = [fact for fact in payload["extracted_facts"] if "押金" in fact["text"]]
        self.assertEqual(len(downgraded), 1, payload["extracted_facts"])
        self.assertEqual(downgraded[0]["status"], "user_only")
        self.assertEqual(downgraded[0]["source_refs"], [])

    def test_issue_with_recorded_provisions_is_supported_with_rule_refs(self) -> None:
        with self._corpus([DEPOSIT_PROVISION]):
            uploaded = self._upload_and_align(f"{DEPOSIT_LINE}\n{NEUTRAL_LINE}")
            self._execute(
                "UPDATE legal_alignments SET legal_provisions = ? WHERE version_id = ? AND clause_type = ?",
                json.dumps([DEPOSIT_PROVISION], ensure_ascii=False),
                uploaded["version_id"],
                "repair",
            )
            response = self.matters(uploaded["contract_id"], uploaded["version_id"])

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]

        issues = {issue["question"]: issue for issue in payload["issues"]}
        repair_issue = issues[RULES["repair"]["question"]]
        self.assertEqual(repair_issue["status"], "supported", repair_issue)
        self.assertTrue(
            any("示范法规" in ref and "第十条" in ref for ref in repair_issue["rule_refs"]),
            repair_issue,
        )

        self.assertTrue(
            any(
                fact["status"] == "supported"
                and any(ref["quote"] == DEPOSIT_LINE for ref in fact["source_refs"])
                for fact in payload["extracted_facts"]
            ),
            payload["extracted_facts"],
        )


if __name__ == "__main__":
    unittest.main()
