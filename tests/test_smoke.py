"""Smoke tests for critical paths - config loading, i18n, meta persistence, splash import.
Run: python -m pytest tests/ -v   (or: python -m unittest discover tests)
No GUI is created - these test pure logic only, per "no visible window launches" constraint."""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import i18n, meta

ROOT = Path(__file__).resolve().parent.parent
T_CALL_RE = re.compile(r"""\bt\(\s*["']([A-Za-z0-9_]+)["']""")


class TestI18n(unittest.TestCase):
    def test_locale_files_exist_and_parse(self):
        for lang in ("en", "he"):
            path = Path(__file__).resolve().parent.parent / "locales" / f"{lang}.json"
            self.assertTrue(path.exists(), f"missing locales/{lang}.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertGreater(len(data), 0)

    def test_en_he_key_parity(self):
        base = Path(__file__).resolve().parent.parent / "locales"
        with open(base / "en.json", "r", encoding="utf-8") as f:
            en_keys = set(json.load(f).keys())
        with open(base / "he.json", "r", encoding="utf-8") as f:
            he_keys = set(json.load(f).keys())
        missing_in_he = en_keys - he_keys
        self.assertEqual(missing_in_he, set(), f"keys missing from he.json: {missing_in_he}")

    def test_t_falls_back_to_key_when_missing(self):
        self.assertEqual(i18n.t("__nonexistent_key__"), "__nonexistent_key__")

    def test_set_language_rejects_unknown(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.get_language(), "en")

    def test_rtl_helpers_flip_with_language(self):
        i18n.set_language("en")
        self.assertFalse(i18n.is_rtl())
        self.assertEqual(i18n.anchor(), "w")
        i18n.set_language("he")
        self.assertTrue(i18n.is_rtl())
        self.assertEqual(i18n.anchor(), "e")
        i18n.set_language("en")  # reset for other tests

    def test_every_t_call_in_source_has_a_locale_key(self):
        """Catches typo'd or renamed translation keys that a plain syntax check
        would never notice (t() silently falls back to the raw key at runtime)."""
        with open(ROOT / "locales" / "en.json", "r", encoding="utf-8") as f:
            known_keys = set(json.load(f).keys())

        missing = {}
        for py_file in (ROOT / "app").glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for key in T_CALL_RE.findall(text):
                if key not in known_keys:
                    missing.setdefault(py_file.name, set()).add(key)

        self.assertEqual(missing, {}, f"t() calls referencing undefined locale keys: {missing}")


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(rgb):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast_ratio(hex1, hex2):
    l1, l2 = _relative_luminance(_hex_to_rgb(hex1)), _relative_luminance(_hex_to_rgb(hex2))
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


class TestAccessibility(unittest.TestCase):
    """WCAG AA contrast (4.5:1 for normal text) for the actual foreground/background
    pairs the UI renders - not just "colors exist", but "colors are readable". Does
    NOT create any window (importing app.dashboard only reads its module-level C
    dict; building a Dashboard instance is what would need a live Tk root).
    STANDARDS.md 14.3. These are real pairs that have failed before (dashboard.py's
    "teal" and "red" tokens each needed splitting into a fill variant and a text
    variant after this check caught them at 2.25:1 and 3.4-3.97:1)."""

    def test_light_theme_text_pairs(self):
        from app.dashboard import C

        bg = C["bg"][0]
        card = C["card"][0]
        pairs = [
            ("text", "text", bg),
            ("text", "text", card),
            ("text_soft", "text_soft", bg),
            ("teal_text (headings)", "teal_text", bg),
            ("red_text (error labels)", "red_text", bg),
            ("red_text (error labels)", "red_text", card),
        ]
        for label, token, bg_hex in pairs:
            fg_hex = C[token][0]
            ratio = _contrast_ratio(fg_hex, bg_hex)
            self.assertGreaterEqual(ratio, 4.5, f"{label} on {bg_hex}: only {ratio:.2f}:1 (need >=4.5)")

    def test_dark_theme_text_pairs(self):
        from app.dashboard import C

        bg = C["bg"][1]
        card = C["card"][1]
        pairs = [
            ("text", "text", bg),
            ("text", "text", card),
            ("text_soft", "text_soft", bg),
            ("teal_text (headings)", "teal_text", bg),
            ("red_text (error labels)", "red_text", bg),
        ]
        for label, token, bg_hex in pairs:
            fg_hex = C[token][1]
            ratio = _contrast_ratio(fg_hex, bg_hex)
            self.assertGreaterEqual(ratio, 4.5, f"{label} on {bg_hex}: only {ratio:.2f}:1 (need >=4.5)")

    def test_button_fill_vs_its_own_text_color(self):
        """The fill tokens meant to carry white/light button text ("red", the primary
        teal action button's fixed dark text) - checked as actually-paired-in-code,
        not just each color validated in isolation."""
        from app.dashboard import C

        for theme_idx, theme_name in ((0, "light"), (1, "dark")):
            ratio = _contrast_ratio("#ffffff", C["red"][theme_idx])
            self.assertGreaterEqual(ratio, 4.5, f'white text on C["red"][{theme_name}]: only {ratio:.2f}:1')
            ratio = _contrast_ratio("#062824", C["teal"][theme_idx])
            self.assertGreaterEqual(ratio, 4.5, f'#062824 text on C["teal"][{theme_idx}]: only {ratio:.2f}:1')


class TestMeta(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            meta.save_meta(d, {"tags": "sales, client-x", "notes": "test"})
            loaded = meta.load_meta(d)
            self.assertEqual(loaded["tags"], "sales, client-x")

    def test_load_missing_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(meta.load_meta(Path(tmp)), {})

    def test_update_merges_not_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            meta.save_meta(d, {"tags": "a"})
            meta.update_meta(d, notes="b")
            loaded = meta.load_meta(d)
            self.assertEqual(loaded["tags"], "a")
            self.assertEqual(loaded["notes"], "b")


class TestConfig(unittest.TestCase):
    def test_version_json_is_valid_and_matches_config(self):
        from app.config import VERSION

        root = Path(__file__).resolve().parent.parent
        with open(root / "version.json", "r", encoding="utf-8") as f:
            version_data = json.load(f)
        self.assertEqual(VERSION, version_data["version"])

    def test_defaults_have_no_none_required_keys(self):
        from app.config import DEFAULTS

        # mic_device_index is the one intentionally-nullable default (auto-detect)
        for key, value in DEFAULTS.items():
            if key == "mic_device_index":
                continue
            self.assertIsNotNone(value, f"DEFAULTS[{key!r}] should not be None")

    def test_analytics_defaults_off(self):
        """Privacy-first product with no analytics backend - must ship opt-in (off),
        not silently on. (Was actually True at one point - regression guard.)"""
        from app.config import DEFAULTS

        self.assertFalse(DEFAULTS["enable_analytics"])


class TestLikelyNoiseHeuristic(unittest.TestCase):
    """Meeting.likely_noise (app/meetings.py) - local word-count-vs-duration heuristic
    used to hide background-noise/silence clutter from the recordings list on request."""

    def _meeting(self, transcript, duration_seconds, is_processing=False):
        from app.meetings import Meeting

        return Meeting(
            dir=Path("x"), timestamp=datetime.now(), summary="", transcript=transcript,
            has_audio=True, is_processing=is_processing, duration_seconds=duration_seconds,
        )

    def test_sparse_long_recording_is_flagged(self):
        # ~40s recording with only 2 words transcribed - almost certainly noise/silence.
        self.assertTrue(self._meeting("hello there", 40).likely_noise)

    def test_normal_conversation_is_not_flagged(self):
        transcript = " ".join(["word"] * 80)  # 80 words over 40s = 120 wpm, a real conversation
        self.assertFalse(self._meeting(transcript, 40).likely_noise)

    def test_short_recording_never_flagged_regardless_of_word_count(self):
        # Below NOISE_MIN_DURATION_SECONDS - too little signal either way, must not badge
        # a short deliberate test recording as "noise".
        self.assertFalse(self._meeting("hi", 10).likely_noise)

    def test_empty_transcript_not_flagged(self):
        # Still processing / genuinely no transcript yet - not a noise verdict, just no data.
        self.assertFalse(self._meeting("", 60).likely_noise)

    def test_processing_recording_never_flagged(self):
        self.assertFalse(self._meeting("", 60, is_processing=True).likely_noise)


class TestExportFormats(unittest.TestCase):
    """export.py's txt/markdown/srt exporters - the concrete fix for the dead
    `export_format` setting (settings offered docx/txt/md but only docx ever worked),
    plus the new .srt captions export."""

    def _meeting(self, **overrides):
        from app.meetings import Meeting

        defaults = dict(
            dir=Path("x"), timestamp=datetime(2026, 1, 1, 10, 0), summary="## Summary\nWe discussed pricing.",
            transcript="Hello\nWe discussed pricing.", has_audio=False, tags=["sales"], notes="follow up",
            duration_seconds=12.0,
        )
        defaults.update(overrides)
        return Meeting(**defaults)

    def test_export_meeting_txt_contains_summary_and_transcript(self):
        from app.export import export_meeting_txt

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.txt"
            export_meeting_txt(self._meeting(), out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("pricing", content)
            self.assertIn("follow up", content)
            self.assertIn("#sales", content)

    def test_export_meeting_md_keeps_markdown_heading(self):
        from app.export import export_meeting_md

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.md"
            export_meeting_md(self._meeting(), out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("## Summary", content)

    def test_export_meeting_srt_uses_real_segment_timestamps(self):
        from app.export import export_meeting_srt

        segments = [{"start": 0.0, "end": 1.5, "text": "Hello"}, {"start": 1.5, "end": 3.0, "text": "World"}]
        meeting = self._meeting(segments=segments)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.srt"
            export_meeting_srt(meeting, out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("00:00:00,000 --> 00:00:01,500", content)
            self.assertIn("Hello", content)
            self.assertIn("World", content)

    def test_export_meeting_srt_falls_back_to_even_split_without_segments(self):
        from app.export import export_meeting_srt

        meeting = self._meeting(transcript="Line one\nLine two", duration_seconds=10.0, segments=[])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.srt"
            export_meeting_srt(meeting, out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("Line one", content)
            self.assertIn("Line two", content)
            self.assertIn("00:00:00,000 -->", content)

    def test_export_dispatcher_routes_by_format(self):
        from app.export import export_meeting

        meeting = self._meeting()
        with tempfile.TemporaryDirectory() as tmp:
            txt_out = Path(tmp) / "out.txt"
            export_meeting(meeting, txt_out, "txt")
            self.assertIn("pricing", txt_out.read_text(encoding="utf-8"))

            md_out = Path(tmp) / "out.md"
            export_meeting(meeting, md_out, "md")
            self.assertIn("## Summary", md_out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
