import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app


class DocumentAPITests(unittest.TestCase):
    def test_upload_reuse_reanalyze_and_search(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DOCUMENTS_DB_PATH": str(Path(directory) / "documents.db")}), patch("app.main.extract_text_from_pdf", return_value=("본문", 1, 0, 0)), patch("app.main.analyze_pdf", return_value={"extracted_text": "본문", "summary": "매출 증가", "keyword": "매출"}) as analyze:
            with TestClient(app) as client:
                def upload(force=False):
                    return client.post("/ai/pdf", files={"file": ("보고서.pdf", b"pdf-content", "application/pdf")}, data={"force": str(force).lower()})
                first = upload()
                self.assertEqual(first.status_code, 200, first.text)
                duplicate = upload()
                self.assertTrue(duplicate.json()["existing"])
                self.assertEqual(analyze.call_count, 1)
                again = upload(True)
                self.assertEqual(again.status_code, 200, again.text)
                self.assertEqual(analyze.call_count, 2)
                self.assertEqual(first.json()["document_id"], again.json()["document_id"])
                listing = client.get("/documents", params={"q": "매출"}).json()
                self.assertEqual(listing["total"], 1)
                self.assertEqual(listing["items"][0]["summary_count"], 2)
                detail = client.get(f'/documents/{first.json()["document_id"]}').json()
                self.assertEqual(len(detail["summaries"]), 2)
                self.assertEqual(client.get("/documents/999").status_code, 404)
                self.assertEqual(client.get("/documents?limit=0").status_code, 422)

    def test_delete_scope_and_empty_document(self):
        from app.database import save_summary, find_existing
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DOCUMENTS_DB_PATH": str(Path(directory) / "documents.db")}):
            response = {"filename": "보고서.pdf", "summary": "첫 요약", "keyword": "실적"}
            first = save_summary("one", response)
            latest = save_summary("one", {**response, "summary": "최신 요약"}, force=True)
            other = save_summary("two", response)
            doc_id = first["document_id"]
            with TestClient(app) as client:
                wrong = client.delete(f'/documents/{doc_id}/summaries/{other["summary_id"]}')
                self.assertEqual(wrong.status_code, 404)
                self.assertEqual(client.delete(f'/documents/{doc_id}/summaries/{latest["summary_id"]}').status_code, 200)
                self.assertEqual(find_existing("one")["summary_id"], first["summary_id"])
                self.assertEqual(client.delete(f'/documents/{doc_id}/summaries/{first["summary_id"]}').status_code, 200)
                self.assertEqual(client.get(f'/documents/{doc_id}').json()["summaries"], [])
                listing = client.get('/documents').json()
                self.assertEqual(listing["total"], 2)
                self.assertEqual(len(listing["items"]), 2)
                empty = next(item for item in listing["items"] if item["id"] == doc_id)
                self.assertEqual(empty["summary_count"], 0)
                self.assertIsNone(find_existing("one"))
                self.assertEqual(save_summary("one", response)["document_id"], doc_id)
                save_summary("one", response, force=True)
                self.assertEqual(client.delete(f'/documents/{doc_id}').status_code, 200)
                self.assertIsNone(find_existing("one"))
                self.assertEqual(client.get(f'/documents/{doc_id}').status_code, 404)
                self.assertEqual(client.delete(f'/documents/{doc_id}').status_code, 404)
                self.assertEqual(len(client.get(f'/documents/{other["document_id"]}').json()["summaries"]), 1)
