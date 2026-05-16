"""Phase 4 tests for plan skill.

Covers testable BC-x / EH-x from P1 spec v2.
Run: `python3 -m unittest tests.test_plan -v` from skill root.

Interactive BC-1 / BC-4 (round dialogues) are NOT auto-tested
(require stdin mock — covered by manual integration smoke).
"""

from __future__ import annotations

import datetime
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts/ to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT.parent / "ar2:dgx-comfyui-gen" / "scripts"))

import plan_schema as ps  # noqa: E402
import plan_promote  # noqa: E402
import plan_loader  # noqa: E402


# ---------- BC-2 / BC-3 / EH-1 / EH-2 / EH-3 / EH-11 ----------


class TestSchemaParse(unittest.TestCase):
    """Covers BC-3 (schema valid), EH-1/2/3 (parse errors)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tpl = (ROOT / "templates" / "default_outline.md").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def _fill_template(self) -> str:
        return (self.tpl
                .replace("PLACEHOLDER_ID", "t_a1b2")
                .replace("PLACEHOLDER_TITLE", "smoke")
                .replace("PLACEHOLDER_CREATED", ps.now_iso())
                .replace("PLACEHOLDER_UPDATED", ps.now_iso()))

    def test_parse_template_ok(self):
        """BC-3: template parses without error."""
        p = self._write("t_a1b2_outline.md", self._fill_template())
        plan = ps.parse(p)
        self.assertEqual(plan.id, "t_a1b2")
        self.assertEqual(len(plan.items), 1)

    def test_eh1_missing_frontmatter(self):
        """EH-1: missing frontmatter raises ValueError."""
        p = self._write("bad.md", "no frontmatter here\n# Story / Vision\n")
        with self.assertRaisesRegex(ValueError, "EH-1"):
            ps.parse(p)

    def test_eh1_unclosed_frontmatter(self):
        p = self._write("bad.md", "---\nid: x\n# Story / Vision\n")
        with self.assertRaisesRegex(ValueError, "EH-1"):
            ps.parse(p)

    def test_eh1_missing_required_field(self):
        """EH-1: missing required field (no version)."""
        p = self._write("bad.md", self._fill_template().replace(
            "version: 1\n", ""
        ))
        with self.assertRaisesRegex(ValueError, "EH-1"):
            ps.parse(p)

    def test_eh1_bad_status_enum(self):
        p = self._write("bad.md", self._fill_template().replace(
            "status: ready", "status: launched"
        ))
        with self.assertRaisesRegex(ValueError, "EH-1"):
            ps.parse(p)

    def test_eh2_missing_section(self):
        """EH-2: missing # Items section."""
        content = self._fill_template().split("# Items")[0]
        p = self._write("bad.md", content + "\n# Open notes\n(empty)\n")
        with self.assertRaisesRegex(ValueError, "EH-2"):
            ps.parse(p)

    def test_eh3_items_table_bad_header(self):
        """EH-3: items table header malformed."""
        content = self._fill_template().replace(
            "| # | slug | prompt | full? |",
            "| index | slug | prompt | full? |",
        )
        p = self._write("bad.md", content)
        with self.assertRaisesRegex(ValueError, "EH-3"):
            ps.parse(p)


# ---------- BC-18 (prompt 字符邊界) ----------


class TestPromptCharBoundary(unittest.TestCase):
    """BC-18: items table prompt char rules."""

    def _build_items_section(self, prompt: str) -> str:
        return (
            "# Items\n"
            "| # | slug | prompt | full? |\n"
            "|---|------|--------|-------|\n"
            f"| 1 | test | {prompt} | |\n"
        )

    def _full_doc(self, items_section: str) -> str:
        return (
            "---\n"
            "id: t_a1b2\ntitle: t\nversion: 1\n"
            f"created: {ps.now_iso()}\nupdated: {ps.now_iso()}\n"
            "status: ready\nworkflow: flux_basic\nsize: [1024, 1024]\n"
            "steps: 20\nbatch_per_item: 1\n"
            "seed_strategy:\n  type: fixed\n  base: 42\n  step: 0\n"
            "---\n\n"
            "# Story / Vision\n(empty)\n\n"
            "# Style anchor\n**Prefix**: (none)\n**Suffix**: (none)\n**Negative**: (none)\n\n"
            "# Output\n- dir: outputs/test/\n- naming: {NN}_{slug}.png\n\n"
            f"{items_section}\n"
            "# Open notes\n(empty)\n"
        )

    def test_prompt_with_pipe_unescaped_rejected(self):
        """BC-18: raw `|` in prompt → parse error (col count mismatch)."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False) as f:
            f.write(self._full_doc(self._build_items_section("foo | bar")))
            f.flush()
            with self.assertRaises(ValueError):
                ps.parse(Path(f.name))

    def test_prompt_with_escaped_pipe_ok(self):
        r"""BC-18: `\|` resolves to literal `|`."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False) as f:
            f.write(self._full_doc(self._build_items_section(r"foo \| bar")))
            f.flush()
            plan = ps.parse(Path(f.name))
            self.assertEqual(plan.items[0].prompt, "foo | bar")

    def test_prompt_with_fullwidth_pipe_ok(self):
        """BC-18: U+FF5C 全形 `｜` retained as normal char."""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False) as f:
            f.write(self._full_doc(self._build_items_section("foo ｜ bar")))
            f.flush()
            plan = ps.parse(Path(f.name))
            self.assertIn("｜", plan.items[0].prompt)

    def test_prompt_empty_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False) as f:
            f.write(self._full_doc(self._build_items_section("")))
            f.flush()
            with self.assertRaises(ValueError):
                ps.parse(Path(f.name))


# ---------- BC-2 id_gen + slugify + collision ----------


class TestIdGen(unittest.TestCase):

    def test_slugify_zh(self):
        s = ps.slugify("12 生肖動漫風")
        self.assertRegex(s, r"^[a-z0-9_]+$")
        self.assertLessEqual(len(s), 20)

    def test_slugify_empty_fallback(self):
        s = ps.slugify("中文中文中文")  # all non-ascii → empty → fallback
        self.assertEqual(s, "plan")

    def test_gen_id_format(self):
        new_id = ps.gen_id("test", lambda _id: False)
        self.assertRegex(new_id, r"^[a-z0-9_]+_[0-9a-f]{4}$")

    def test_gen_id_collision_raises(self):
        with self.assertRaises(RuntimeError):
            ps.gen_id("test", lambda _id: True)  # always collision


# ---------- BC-3 / Round-trip ----------


class TestRoundTrip(unittest.TestCase):

    def test_serialize_parse_idempotent(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            tpl = (ROOT / "templates" / "default_outline.md").read_text()
            tpl = tpl.replace("PLACEHOLDER_ID", "rt_a1b2")
            tpl = tpl.replace("PLACEHOLDER_TITLE", "round-trip")
            tpl = tpl.replace("PLACEHOLDER_CREATED", ps.now_iso())
            tpl = tpl.replace("PLACEHOLDER_UPDATED", ps.now_iso())
            (tmp / "rt_a1b2_outline.md").write_text(tpl)
            p1 = ps.parse(tmp / "rt_a1b2_outline.md")
            out = ps.serialize(p1)
            (tmp / "rt2_outline.md").write_text(out)
            p2 = ps.parse(tmp / "rt2_outline.md")
            self.assertEqual(p1.id, p2.id)
            self.assertEqual(p1.title, p2.title)
            self.assertEqual(len(p1.items), len(p2.items))
            self.assertEqual(p1.items[0].slug, p2.items[0].slug)
        finally:
            shutil.rmtree(tmp)


# ---------- EH-11 atomic_write ----------


class TestAtomicWrite(unittest.TestCase):

    def test_atomic_write_replaces(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            p = tmp / "x.md"
            p.write_text("old")
            ps.atomic_write(p, "new")
            self.assertEqual(p.read_text(), "new")
            # no stale .tmp
            self.assertFalse((tmp / "x.md.tmp").exists())
        finally:
            shutil.rmtree(tmp)


# ---------- Security: validate_id (R-1 sec) ----------


class TestValidateId(unittest.TestCase):
    """BC-2 + sec R-1: id is safe path component."""

    def test_valid_ids(self):
        for good in ["zodiac_a1b2", "test_0000", "x_z_z_z_z",
                     "a1b2c3", "plan_dead"]:
            ps.validate_id(good)  # should not raise

    def test_path_traversal_rejected(self):
        for bad in ["/etc/passwd", "../sneaky", "..\\sneaky",
                    "~/.ssh/id_rsa", "C:/Users/bob",
                    "has space", "has-dash", "UPPER",
                    "", "x" * 65, "._hidden",
                    "/", "..", "~"]:
            with self.assertRaises(ValueError,
                                   msg=f"should reject: {bad!r}"):
                ps.validate_id(bad)


# ---------- Security: sanitize (R-2 / R-3 / R-4) ----------


class TestSanitize(unittest.TestCase):

    def test_face_ref_posix(self):
        self.assertEqual(
            plan_promote._sanitize_face_ref("/Users/alice/face.png"),
            "<set face_ref locally>",
        )

    def test_face_ref_windows_backslash(self):
        self.assertEqual(
            plan_promote._sanitize_face_ref("C:\\Users\\bob\\face.png"),
            "<set face_ref locally>",
        )

    def test_face_ref_env_var(self):
        for v in ["$HOME/face.png", "%USERPROFILE%\\face.png", "~/face.png"]:
            self.assertEqual(
                plan_promote._sanitize_face_ref(v),
                "<set face_ref locally>",
            )

    def test_face_ref_relative_ok(self):
        self.assertEqual(
            plan_promote._sanitize_face_ref("face.png"),
            "face.png",
        )

    def test_face_ref_none_ok(self):
        self.assertIsNone(plan_promote._sanitize_face_ref(None))

    def test_output_dir_abs(self):
        out = plan_promote._sanitize_output_dir("/abs/path", "x_a1b2")
        self.assertIn("x_a1b2", out)

    def test_output_dir_traversal(self):
        out = plan_promote._sanitize_output_dir("../../../etc", "x_a1b2")
        self.assertIn("x_a1b2", out)

    def test_output_dir_windows(self):
        out = plan_promote._sanitize_output_dir("C:\\Users\\bob", "x_a1b2")
        self.assertIn("x_a1b2", out)

    def test_output_dir_relative_ok(self):
        # MVP: any-non-leak → keep as-is
        self.assertEqual(
            plan_promote._sanitize_output_dir("outputs/foo/", "x_a1b2"),
            "outputs/foo/",
        )


# ---------- Loader / IF-3 ----------


class TestLoaderExpand(unittest.TestCase):

    def test_strip_workflow_metadata(self):
        wf = {"_comment": "x", "1": {"class_type": "X"}, "_meta": "y",
              "2": {"class_type": "Y"}}
        cleaned = plan_loader.strip_workflow_metadata(wf)
        self.assertEqual(set(cleaned.keys()), {"1", "2"})

    def test_seed_iter_fixed(self):
        gen = plan_loader._build_seed_iter(
            {"type": "fixed", "base": 42, "step": 0}, 3,
        )
        self.assertEqual(list(gen), [42, 42, 42])

    def test_seed_iter_incremental(self):
        gen = plan_loader._build_seed_iter(
            {"type": "incremental", "base": 100, "step": 10}, 4,
        )
        self.assertEqual(list(gen), [100, 110, 120, 130])

    def test_seed_iter_random_length(self):
        gen = plan_loader._build_seed_iter(
            {"type": "random", "base": 0, "step": 0}, 5,
        )
        self.assertEqual(len(list(gen)), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
