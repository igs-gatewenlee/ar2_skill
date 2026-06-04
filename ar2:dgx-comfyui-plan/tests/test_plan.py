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
from dataclasses import replace  # BC-G9-4: #009-safe fixture construction
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


# ---------- pulid_weight (issue #4) ----------


class TestPulidWeightParse(unittest.TestCase):
    """Covers _parse_pulid_weight BC-1/2/3, EH-1/2/3 from P1 spec."""

    def test_none_passthrough(self):
        """BC-1: missing key → None."""
        self.assertIsNone(ps._parse_pulid_weight(None))

    def test_valid_float(self):
        """BC-2: in-range float → float."""
        self.assertEqual(ps._parse_pulid_weight(0.9), 0.9)

    def test_int_coerced_to_float(self):
        """BC-2: int 1 → 1.0 (numeric tolerance)."""
        self.assertEqual(ps._parse_pulid_weight(1), 1.0)

    def test_min_boundary(self):
        """BC-7: 0.0 is valid (boundary)."""
        self.assertEqual(ps._parse_pulid_weight(0.0), 0.0)

    def test_max_boundary(self):
        """3.0 is valid (boundary)."""
        self.assertEqual(ps._parse_pulid_weight(3.0), 3.0)

    def test_string_input_raises(self):
        """EH-1: non-numeric → ValueError."""
        with self.assertRaisesRegex(ValueError, "numeric"):
            ps._parse_pulid_weight("abc")

    def test_negative_raises(self):
        """EH-2: < 0.0 → out-of-range ValueError."""
        with self.assertRaisesRegex(ValueError, "out of range"):
            ps._parse_pulid_weight(-0.1)

    def test_over_max_raises(self):
        """EH-3: > 3.0 → out-of-range ValueError."""
        with self.assertRaisesRegex(ValueError, "out of range"):
            ps._parse_pulid_weight(3.5)


class TestPulidWeightRoundTrip(unittest.TestCase):
    """R-1 fix: pulid_weight must survive parse → serialize → parse.

    Round-trip coverage prevents the silent-drop regression where promote /
    from-preset would lose the field during YAML re-emission.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tpl = (ROOT / "templates" / "default_outline.md").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write_plan_with_weight(self, weight_yaml_line: str) -> Path:
        """Drop a custom pulid_weight line into the default outline template."""
        text = self.tpl.replace(
            "face_ref: null\n",
            f"face_ref: null\n{weight_yaml_line}\n",
        )
        path = self.tmp / "test.md"
        path.write_text(text)
        return path

    def test_serialized_yaml_contains_pulid_weight(self):
        """Set value → serialize → YAML body contains pulid_weight."""
        path = self._write_plan_with_weight("pulid_weight: 0.7")
        plan = ps.parse(path)
        self.assertEqual(plan.pulid_weight, 0.7)
        yaml_text = ps.serialize(plan)
        self.assertIn("pulid_weight", yaml_text)
        self.assertIn("0.7", yaml_text)

    def test_round_trip_preserves_value(self):
        """parse → serialize → parse keeps the same pulid_weight."""
        path = self._write_plan_with_weight("pulid_weight: 1.5")
        plan = ps.parse(path)
        round_trip = self.tmp / "round_trip.md"
        round_trip.write_text(ps.serialize(plan))
        plan_again = ps.parse(round_trip)
        self.assertEqual(plan_again.pulid_weight, 1.5)

    def test_round_trip_none_stays_none(self):
        """Unset pulid_weight stays unset after round-trip (no spurious key)."""
        plan = ps.parse(ROOT / "templates" / "default_outline.md")
        self.assertIsNone(plan.pulid_weight)
        yaml_text = ps.serialize(plan)
        self.assertNotIn("pulid_weight", yaml_text)


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


# ============================================================
# Design Dimensions tests (BC-1/2/3a/3b/4/5/6/14 + EH-1/2/2b/3)
# ============================================================


_DD_SECTION_FULL = """\
# Design Dimensions

```yaml
season_structure:
  theme: 奇幻冒險
  grouping_axis: chapter
  groups:
    ch1: {count: 12, label: 啟程}
    ch2: {count: 12, label: 試煉}
  cross_group_progression:
    composition:
      ch1: half_body
      ch2: full_body
  character_continuity: brown_braids_girl
  acceptance: 每張需明確敘事節點

narrative_direction:
  character_seed: 12 歲女孩,棕髮辮子
  group_arc:
    ch1: 離家啟程
    ch2: 森林精靈導師
  emotion_palette: 希望 + 冒險

visual_lock:
  hair:
    value: 棕色辮子
    scope: locked
  outfit:
    value: 皮製旅行斗篷
    scope: locked
  composition:
    scope: per_group
  background:
    scope: per_group
  lighting:
    value: 自然光
    scope: locked
  expression:
    scope: unspecified
  style_intensity:
    value: Pixar 3D
    scope: locked
  view_angle:
    scope: unspecified
  color_palette:
    value: 暖色系
    scope: locked
```
"""


def _outline_with_dd(template: str, dd_section: str = _DD_SECTION_FULL) -> str:
    """Inject Design Dimensions between Story/Vision and Style anchor."""
    return template.replace("# Style anchor", f"{dd_section}\n# Style anchor", 1)


class TestDesignDimensionsParse(unittest.TestCase):
    """BC-1: parse Design Dimensions section → layer_b/c/a."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tpl = (ROOT / "templates" / "default_outline.md").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _fill(self) -> str:
        return (self.tpl
                .replace("PLACEHOLDER_ID", "dd_test")
                .replace("PLACEHOLDER_TITLE", "dd smoke")
                .replace("PLACEHOLDER_CREATED", ps.now_iso())
                .replace("PLACEHOLDER_UPDATED", ps.now_iso()))

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def test_bc1_parse_full_dd(self):
        """BC-1: full Design Dimensions section → all 3 layers populated."""
        outline = _outline_with_dd(self._fill())
        p = self._write("dd_test_outline.md", outline)
        plan = ps.parse(p)
        self.assertIsNotNone(plan.layer_b)
        self.assertIsNotNone(plan.layer_c)
        self.assertIsNotNone(plan.layer_a)
        self.assertEqual(plan.layer_b.theme, "奇幻冒險")
        self.assertEqual(plan.layer_b.grouping_axis, "chapter")
        self.assertEqual(plan.layer_c.character_seed, "12 歲女孩,棕髮辮子")
        self.assertEqual(plan.layer_a.hair.value, "棕色辮子")
        self.assertEqual(plan.layer_a.hair.scope, "locked")
        self.assertEqual(plan.layer_a.expression.scope, "unspecified")
        self.assertIsNone(plan.layer_a.expression.value)

    def test_bc1_no_dd_section(self):
        """BC-1: no Design Dimensions section → all 3 layers None."""
        p = self._write("nodd_outline.md", self._fill())
        plan = ps.parse(p)
        self.assertIsNone(plan.layer_b)
        self.assertIsNone(plan.layer_c)
        self.assertIsNone(plan.layer_a)

    def test_bc4_missing_dim_defaults_unspecified(self):
        """BC-4: Layer A 缺欄位 → 該維度為 Dimension(None, 'unspecified')."""
        partial = """\
# Design Dimensions

```yaml
visual_lock:
  hair:
    value: short
    scope: locked
```
"""
        outline = _outline_with_dd(self._fill(), partial)
        p = self._write("partial_outline.md", outline)
        plan = ps.parse(p)
        self.assertIsNotNone(plan.layer_a)
        self.assertEqual(plan.layer_a.hair.value, "short")
        self.assertEqual(plan.layer_a.outfit.scope, "unspecified")
        self.assertIsNone(plan.layer_a.outfit.value)
        # 8 of 9 dims default unspecified
        unspec = sum(
            1 for n in ps._LAYER_A_DIMENSION_NAMES
            if getattr(plan.layer_a, n).scope == "unspecified"
        )
        self.assertEqual(unspec, 8)


class TestDesignDimensionsErrors(unittest.TestCase):
    """EH-1, EH-2, EH-2b, EH-3."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tpl = (ROOT / "templates" / "default_outline.md").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _fill(self) -> str:
        return (self.tpl
                .replace("PLACEHOLDER_ID", "eh_test")
                .replace("PLACEHOLDER_TITLE", "eh")
                .replace("PLACEHOLDER_CREATED", ps.now_iso())
                .replace("PLACEHOLDER_UPDATED", ps.now_iso()))

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def test_eh1_invalid_yaml(self):
        """EH-1: malformed YAML in Design Dimensions."""
        bad = "# Design Dimensions\n\n```yaml\nseason_structure: [unclosed\n```\n"
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-1.*Design Dimensions"):
            ps.parse(p)

    def test_eh1_non_mapping(self):
        """EH-1: Design Dimensions root not a mapping."""
        bad = "# Design Dimensions\n\n```yaml\n- just a list\n- of items\n```\n"
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-1.*mapping"):
            ps.parse(p)

    def test_eh2_invalid_scope(self):
        """EH-2: invalid scope value."""
        bad = """\
# Design Dimensions

```yaml
visual_lock:
  hair:
    scope: bogus_scope
```
"""
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-2.*invalid scope"):
            ps.parse(p)

    def test_eh2b_unknown_dimension(self):
        """EH-2b: unknown dimension name."""
        bad = """\
# Design Dimensions

```yaml
visual_lock:
  not_a_real_dim:
    scope: locked
```
"""
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-2b.*unknown dimension"):
            ps.parse(p)

    def test_eh3_invalid_grouping_axis(self):
        """EH-3: grouping_axis not in enum."""
        bad = """\
# Design Dimensions

```yaml
season_structure:
  theme: x
  grouping_axis: invalid_axis
  groups: {}
```
"""
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-3.*grouping_axis"):
            ps.parse(p)

    def test_eh2_value_without_explicit_scope(self):
        """R-6: dim 填 value 但無 explicit scope key → EH-2."""
        bad = """\
# Design Dimensions

```yaml
visual_lock:
  hair:
    value: brown
```
"""
        outline = _outline_with_dd(self._fill(), bad)
        p = self._write("bad.md", outline)
        with self.assertRaisesRegex(ValueError, "EH-2.*scope must be specified"):
            ps.parse(p)


class TestDesignDimensionsRoundTrip(unittest.TestCase):
    """BC-3a (行為等價) + BC-3b (序列化對稱、4 狀態)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tpl = (ROOT / "templates" / "default_outline.md").read_text()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _fill(self) -> str:
        return (self.tpl
                .replace("PLACEHOLDER_ID", "rt_test")
                .replace("PLACEHOLDER_TITLE", "rt")
                .replace("PLACEHOLDER_CREATED", ps.now_iso())
                .replace("PLACEHOLDER_UPDATED", ps.now_iso()))

    def _roundtrip(self, content: str) -> "ps.Plan":
        p = self.tmp / "rt_outline.md"
        p.write_text(content)
        plan = ps.parse(p)
        serialized = ps.serialize(plan)
        p2 = self.tmp / "rt_outline2.md"
        p2.write_text(serialized)
        return ps.parse(p2)

    def test_state_a_all_none(self):
        """BC-3b state (a): layer_a/b/c all None — section omitted."""
        plan = self._roundtrip(self._fill())
        self.assertIsNone(plan.layer_a)
        self.assertIsNone(plan.layer_b)
        self.assertIsNone(plan.layer_c)

    def test_state_b_partial_fill(self):
        """BC-3b state (b): only layer_a filled."""
        partial = """\
# Design Dimensions

```yaml
visual_lock:
  hair: {value: black, scope: locked}
  outfit: {value: red, scope: per_group}
```
"""
        plan = self._roundtrip(_outline_with_dd(self._fill(), partial))
        self.assertIsNone(plan.layer_b)
        self.assertIsNone(plan.layer_c)
        self.assertIsNotNone(plan.layer_a)
        self.assertEqual(plan.layer_a.hair.value, "black")
        self.assertEqual(plan.layer_a.outfit.scope, "per_group")

    def test_state_c_all_filled(self):
        """BC-3b state (c): all 3 layers filled (uses _DD_SECTION_FULL)."""
        plan = self._roundtrip(_outline_with_dd(self._fill()))
        self.assertIsNotNone(plan.layer_b)
        self.assertIsNotNone(plan.layer_c)
        self.assertIsNotNone(plan.layer_a)
        self.assertEqual(plan.layer_b.theme, "奇幻冒險")
        self.assertEqual(
            plan.layer_b.cross_group_progression["composition"]["ch1"],
            "half_body",
        )
        self.assertEqual(plan.layer_c.group_arc["ch1"], "離家啟程")
        self.assertEqual(plan.layer_a.hair.value, "棕色辮子")

    def test_state_d_all_unspecified_normalizes_to_none(self):
        """BC-3b state (d): layer_a all-unspecified + b/c None → serialize omits section."""
        # Build a plan whose layer_a is "all unspecified" (no explicit dims set).
        all_unspec = """\
# Design Dimensions

```yaml
visual_lock: {}
```
"""
        plan = self._roundtrip(_outline_with_dd(self._fill(), all_unspec))
        # Normalize: after round-trip layer_a should be None (no section emitted)
        self.assertIsNone(plan.layer_a)

    def test_bc3a_behavior_none_vs_all_unspecified(self):
        """BC-3a: layer_a=None vs LayerA(all unspecified) behave equivalently.

        Both should be 'empty layer A' — serialized output omits the section
        either way. (derive_prompt EH-4 behavior tested in test_derive.py.)
        """
        # Build directly via dataclass.
        empty_a = ps.LayerA(
            **{n: ps.Dimension(None, "unspecified")
               for n in ps._LAYER_A_DIMENSION_NAMES}
        )
        # BC-G9-4 (#009): one base Plan/Item + replace → v1.3/future fields inherit.
        _base = ps.Plan(
            id="t", title="t", version=1,
            created=ps.now_iso(), updated=ps.now_iso(),
            status="ready", workflow="flux_basic",
            size=[512, 512], steps=20, batch_per_item=1,
            seed_strategy={"type": "fixed", "base": 0, "step": 0},
            items=[ps.Item("a", "p")],
        )
        plan_none = replace(_base, layer_a=None)
        plan_unspec = replace(_base, layer_a=empty_a)
        s_none = ps.serialize(plan_none)
        s_unspec = ps.serialize(plan_unspec)
        # Both omit Design Dimensions section.
        self.assertNotIn("# Design Dimensions", s_none)
        self.assertNotIn("# Design Dimensions", s_unspec)


class TestBackwardCompat(unittest.TestCase):
    """BC-14: old outline (no Design Dimensions, manual prompts) unchanged."""

    def test_cards_a11c_outline_still_parses(self):
        """Existing cards_a11c outline (60 items, no DD section) parses unchanged."""
        existing = Path(
            "/Users/gatewenlee/Code/ai_cards/plans/cards_a11c_outline.md"
        )
        if not existing.exists():
            self.skipTest("cards_a11c_outline.md not present")
        plan = ps.parse(existing)
        self.assertIsNone(plan.layer_a)
        self.assertIsNone(plan.layer_b)
        self.assertIsNone(plan.layer_c)
        # 5 chapters × 12 items = 60
        self.assertEqual(len(plan.items), 60)
        self.assertTrue(plan.items[0].prompt)  # non-empty manual prompt

    def test_template_default_no_dd_section(self):
        """Default template (no DD) still parses & round-trips."""
        tpl = (ROOT / "templates" / "default_outline.md").read_text()
        filled = (tpl
                  .replace("PLACEHOLDER_ID", "bc_test")
                  .replace("PLACEHOLDER_TITLE", "x")
                  .replace("PLACEHOLDER_CREATED", ps.now_iso())
                  .replace("PLACEHOLDER_UPDATED", ps.now_iso()))
        tmp = Path(tempfile.mkdtemp())
        try:
            p = tmp / "bc.md"
            p.write_text(filled)
            plan = ps.parse(p)
            s = ps.serialize(plan)
            self.assertNotIn("# Design Dimensions", s)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
