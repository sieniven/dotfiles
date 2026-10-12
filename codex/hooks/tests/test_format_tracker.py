"""Tests for format_tracker.py's Rust edition lookup.

Run: python3 -m unittest discover -s codex/hooks/tests -v
"""

import os
import sys
import tempfile
import unittest

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOOKS)
from format_tracker import rust_edition  # noqa: E402


class RustEditionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def manifest(self, rel, text):
        os.makedirs(os.path.join(self.root, rel), exist_ok=True)
        with open(os.path.join(self.root, rel, "Cargo.toml"), "w") as fh:
            fh.write(text)

    def edition(self, rel="crates/x"):
        return rust_edition(os.path.join(self.root, rel, "src", "lib.rs"))

    def test_own_edition(self):
        self.manifest("crates/x", '[package]\nname = "x"\n# edition = "2015"\nedition = "2018"  # pinned\n')
        self.assertEqual(self.edition(), "2018")

    def test_inherited_edition_comes_from_the_workspace_root(self):
        self.manifest("", '[workspace]\nmembers = ["crates/x"]\n\n[workspace.package]\nedition = "2024"\n')
        for form in ("edition.workspace = true", "edition = { workspace = true }"):
            self.manifest("crates/x", '[package]\nname = "x"\n%s\n\n[[bin]]\nname = "x"\n' % form)
            self.assertEqual(self.edition(), "2024", form)
        self.assertEqual(self.edition(""), "2024")

    def test_root_package_is_its_own_workspace(self):
        self.manifest("", '[package]\nname = "r"\nedition.workspace = true\n\n[workspace.package]\nedition = "2024"\n')
        self.assertEqual(self.edition(""), "2024")

    def test_unresolved_edition_falls_back_to_2021(self):
        self.assertEqual(self.edition(), "2021")
        self.manifest("crates/x", '[package]\nname = "x"\nedition.workspace = true\n')
        self.assertEqual(self.edition(), "2021")


if __name__ == "__main__":
    unittest.main()
