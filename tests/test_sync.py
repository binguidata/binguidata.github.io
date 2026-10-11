"""CLI regressions for shared-region validation using isolated site fixtures."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SyncCheckTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "sync.py", self.root / "sync.py")
        partials = self.root / "_partials"
        partials.mkdir()
        (partials / "data.json").write_text(json.dumps({"version": "test"}))
        self.bodies = {"head": "<title>Test</title>\n", "nav": "<nav>Test</nav>\n", "footer": "<footer>Test</footer>\n"}
        for name, body in self.bodies.items():
            (partials / f"{name}.html").write_text(body)
        self.page = self.root / "index.html"
        self.page.write_text("".join(self.region(name) for name in self.bodies))

    def region(self, name):
        return f"<!-- @shared:{name} -->\n{self.bodies[name]}<!-- @end:{name} -->\n"

    def run_sync(self, check=True):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = subprocess.run(
            [sys.executable, str(self.root / "sync.py"), *(["--check"] if check else [])],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.stderr, "")
        if check:
            after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
            self.assertEqual(after, before, "--check must not modify any fixture files")
        return result

    def assert_invalid(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 1)
        self.assertIn("index.html: missing or malformed markers for nav", result.stdout)
        self.assertNotIn("all pages current", result.stdout)

    def test_current_pages_pass(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0)
        self.assertIn("all pages current", result.stdout)

    def test_drift_fails_without_writing(self):
        self.page.write_text(self.page.read_text().replace("<nav>Test</nav>", "<nav>Stale</nav>"))
        result = self.run_sync()
        self.assertEqual(result.returncode, 1)
        self.assertIn("drift in: index.html", result.stdout)
        self.assertNotIn("all pages current", result.stdout)

    def test_missing_region_fails_without_drift(self):
        self.page.write_text(self.page.read_text().replace(self.region("nav"), ""))
        self.assert_invalid()

    def test_missing_start_or_end_marker_fails(self):
        original = self.page.read_text()
        for marker in ("<!-- @shared:nav -->", "<!-- @end:nav -->"):
            with self.subTest(marker=marker):
                self.page.write_text(original.replace(marker, ""))
                self.assert_invalid()

    def test_reversed_markers_fail(self):
        self.page.write_text(self.page.read_text().replace(
            self.region("nav"), "<!-- @end:nav -->\n<nav>Test</nav>\n<!-- @shared:nav -->\n"
        ))
        self.assert_invalid()

    def test_duplicate_start_or_end_marker_fails(self):
        original = self.page.read_text()
        for marker in ("<!-- @shared:nav -->", "<!-- @end:nav -->"):
            with self.subTest(marker=marker):
                self.page.write_text(original.replace(marker, marker + "\n" + marker))
                self.assert_invalid()

    def test_malformed_marker_fails(self):
        self.page.write_text(self.page.read_text().replace("<!-- @end:nav -->", "<!-- @end:nav -- >"))
        self.assert_invalid()

    def test_normal_sync_fails_for_missing_region(self):
        self.page.write_text(self.page.read_text().replace(self.region("nav"), ""))
        result = self.run_sync(check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or malformed markers for nav", result.stdout)
        self.assertNotIn("already current", result.stdout)

    def test_normal_sync_still_updates_drift(self):
        expected = self.page.read_text()
        self.page.write_text(expected.replace("<nav>Test</nav>", "<nav>Stale</nav>"))
        result = self.run_sync(check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.page.read_text(), expected)
        self.assertIn("index.html updated", result.stdout)


if __name__ == "__main__":
    unittest.main()
