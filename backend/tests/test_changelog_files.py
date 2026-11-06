from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG_DIR = ROOT / "frontend" / "public" / "changelog"
FORBIDDEN = ("0RDCKGQT5LVS", "lbkhkkkmnbhnnmimhadmjappokdfkpgd")


class ChangelogFilesTests(unittest.TestCase):
    def test_markdown_entries_have_frontmatter(self):
        files = sorted(p for p in CHANGELOG_DIR.glob("*.md") if p.name.lower() != "readme.md")
        self.assertGreaterEqual(len(files), 2)
        versions = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), path.name)
            _, rest = text.split("---\n", 1)
            fm, body = rest.split("\n---", 1)
            self.assertIn("version:", fm, path.name)
            self.assertIn("date:", fm, path.name)
            self.assertRegex(fm, r"date:\s+\d{4}-\d{2}-\d{2}", path.name)
            self.assertTrue(body.strip(), path.name)
            versions.append(path.name)
        self.assertIn("client-v0.9.0.md", versions)
        self.assertIn("client-v0.1.0.md", versions)

    def test_no_internal_store_identifiers_in_changelog(self):
        for path in CHANGELOG_DIR.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            for needle in FORBIDDEN:
                self.assertNotIn(needle, text, path.name)


if __name__ == "__main__":
    unittest.main()
