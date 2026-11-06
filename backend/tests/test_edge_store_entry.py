from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.config import Config

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
CRX_ID = "lbkhkkkmnbhnnmimhadmjappokdfkpgd"
STORE_ID = "0RDCKGQT5LVS"
FORBIDDEN = (CRX_ID, STORE_ID)
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".map", ".md", ".ts", ".tsx"}


def iter_text_files(*roots: Path):
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


class EdgeStoreEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "edge-store.db"

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
            MAIL_DEV_CONSOLE = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_endpoint_redirects_to_detail_page(self):
        response = self.client.get("/api/edge-store")
        self.assertEqual(response.status_code, 302)
        location = response.headers.get("Location", "")
        self.assertTrue(
            location.startswith("https://microsoftedge.microsoft.com/addons/detail/"),
            location,
        )
        self.assertIn(CRX_ID, location)
        self.assertNotIn("/addons/search", location)
        self.assertNotEqual(location.rstrip("/"), "https://microsoftedge.microsoft.com/addons")

    def test_category_target_is_not_redirected(self):
        self.app.config["EDGE_STORE_URL"] = "https://microsoftedge.microsoft.com/addons"
        response = self.client.get("/api/edge-store")
        self.assertEqual(response.status_code, 404)
        self.app.config["EDGE_STORE_URL"] = "https://microsoftedge.microsoft.com/addons/search"
        response = self.client.get("/api/edge-store")
        self.assertEqual(response.status_code, 404)

    def test_site_entry_is_application_endpoint(self):
        text = (FRONTEND / "src" / "site.ts").read_text(encoding="utf-8")
        self.assertIn('export const EDGE_STORE_URL = "/api/edge-store"', text)
        for needle in FORBIDDEN:
            self.assertNotIn(needle, text)

    def test_src_and_docs_do_not_embed_store_ids(self):
        roots = (
            FRONTEND / "src",
            FRONTEND / "public",
            ROOT / "docs",
        )
        for path in iter_text_files(*roots):
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN:
                self.assertNotIn(needle, text, path)

    def test_built_js_html_do_not_embed_store_ids(self):
        self.assertTrue(DIST.is_dir(), "先运行 cd frontend && npm run build")
        found_entry = False
        for path in iter_text_files(DIST):
            if path.suffix.lower() not in {".js", ".html", ".css", ".map"}:
                continue
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN:
                self.assertNotIn(needle, text, path)
            if path.suffix in {".js", ".html"} and "/api/edge-store" in text:
                found_entry = True
        self.assertTrue(found_entry, "构建产物应保留同源 /api/edge-store 入口")


if __name__ == "__main__":
    unittest.main()
