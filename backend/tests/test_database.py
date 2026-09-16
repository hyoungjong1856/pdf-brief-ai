import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.database import find_existing, get_document, list_documents, save_summary


class DocumentLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DOCUMENTS_DB_PATH": str(Path(self.temp.name) / "documents.db")})
        self.env.start()
        self.response = {"filename": "보고서.pdf", "summary": "매출 증가 10%", "keyword": "실적"}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_duplicate_and_history(self):
        first = save_summary("hash", self.response)
        duplicate = save_summary("hash", {**self.response, "filename": "다른이름.pdf"})
        self.assertEqual(first["summary_id"], duplicate["summary_id"])
        self.assertTrue(duplicate["existing"])
        second = save_summary("hash", {**self.response, "summary": "새 요약", "keyword": "변경"}, force=True)
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertNotEqual(first["summary_id"], second["summary_id"])
        self.assertEqual(find_existing("hash")["summary"], "새 요약")
        self.assertEqual(len(get_document(first["document_id"])["summaries"]), 2)
        self.assertEqual(list_documents("매출")["total"], 1)
        self.assertEqual(list_documents("실적")["total"], 1)
        self.assertIsNone(get_document(999))

    def test_literal_search_and_pagination(self):
        save_summary("one", self.response)
        save_summary("two", {**self.response, "summary": "다른 내용"})
        self.assertEqual(list_documents("%")["total"], 1)
        self.assertEqual(list_documents("_")["total"], 0)
        self.assertEqual(list_documents("' OR 1=1 --")["total"], 0)
        page = list_documents(limit=1, offset=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)

    def test_concurrent_duplicate_is_one_record(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda _: save_summary("same", self.response), range(4)))
        self.assertEqual(len({item["summary_id"] for item in records}), 1)
        self.assertEqual(list_documents()["total"], 1)


if __name__ == "__main__":
    unittest.main()
