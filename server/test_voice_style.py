import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import voice_style
from server.call_bot import CHAT_MODES, MODES, CallConfig

BASE = "You are Jake, a friendly peer."


def make(mode: str, **kw) -> CallConfig:
    return CallConfig(system_instruction=BASE, mode=mode, **kw)


class VoiceStyleTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(voice_style.VOICE_STYLE_ENV, None)
        os.environ.pop(voice_style.PROSODY_STYLE_ENV, None)

    def test_word_cap(self):
        self.assertLessEqual(len(voice_style.VOICE_STYLE.split()), voice_style.MAX_WORDS)

    def test_chat_modes_get_suffix_after_existing_text(self):
        for mode in CHAT_MODES:
            out = voice_style.with_voice_style(make(mode))
            self.assertEqual(out.system_instruction, f"{BASE}\n\n{voice_style.VOICE_STYLE}")

    def test_other_modes_unchanged(self):
        for mode in set(MODES) - set(CHAT_MODES):
            config = make(mode)
            self.assertIs(voice_style.with_voice_style(config), config)

    def test_mode_argument_overrides_config_mode(self):
        config = make("smalltalk")
        self.assertEqual(voice_style.with_voice_style(config, "mission").system_instruction, BASE)

    def test_switch_off_is_identical(self):
        for value in ("off", "OFF", "0", "false", "no"):
            os.environ[voice_style.VOICE_STYLE_ENV] = value
            config = make("smalltalk")
            self.assertIs(voice_style.with_voice_style(config), config)
            self.assertEqual(voice_style.with_voice_style(config).system_instruction.encode(), BASE.encode())

    def test_other_fields_kept_and_not_applied_twice(self):
        config = make("smalltalk", partner="jake", engine="gemini_live_38", voice="Puck")
        once = voice_style.with_voice_style(config)
        self.assertEqual((once.partner, once.engine, once.voice, once.mode), ("jake", "gemini_live_38", "Puck", "smalltalk"))
        self.assertIs(voice_style.with_voice_style(once), once)

    def test_no_tags_or_stage_directions_in_text(self):
        text = voice_style.VOICE_STYLE
        for bad in ("<", ">", "[", "]", "*"):
            self.assertNotIn(bad, text)


class ProsodyStyleTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(voice_style.VOICE_STYLE_ENV, None)
        os.environ.pop(voice_style.PROSODY_STYLE_ENV, None)

    def test_word_cap_and_no_tags(self):
        self.assertLessEqual(len(voice_style.PROSODY_STYLE.split()), voice_style.PROSODY_MAX_WORDS)
        for bad in ("<", ">", "[", "]", "*"):
            self.assertNotIn(bad, voice_style.PROSODY_STYLE)

    def test_default_off_and_off_values_leave_prompt_identical(self):
        expected = f"{BASE}\n\n{voice_style.VOICE_STYLE}".encode()
        for value in (None, "off", "OFF", "0", "false", "no"):
            if value is not None:
                os.environ[voice_style.PROSODY_STYLE_ENV] = value
            out = voice_style.with_voice_style(make("smalltalk"))
            self.assertEqual(out.system_instruction.encode(), expected)
            self.assertNotIn(voice_style.PROSODY_STYLE, out.system_instruction)

    def test_on_appends_after_voice_style(self):
        os.environ[voice_style.PROSODY_STYLE_ENV] = "on"
        for mode in CHAT_MODES:
            out = voice_style.with_voice_style(make(mode))
            self.assertEqual(out.system_instruction, f"{BASE}\n\n{voice_style.VOICE_STYLE}\n\n{voice_style.PROSODY_STYLE}")

    def test_on_without_voice_style(self):
        os.environ[voice_style.PROSODY_STYLE_ENV] = "on"
        os.environ[voice_style.VOICE_STYLE_ENV] = "off"
        out = voice_style.with_voice_style(make("smalltalk"))
        self.assertEqual(out.system_instruction, f"{BASE}\n\n{voice_style.PROSODY_STYLE}")

    def test_on_other_modes_unchanged_and_not_applied_twice(self):
        os.environ[voice_style.PROSODY_STYLE_ENV] = "on"
        for mode in set(MODES) - set(CHAT_MODES):
            config = make(mode)
            self.assertIs(voice_style.with_voice_style(config), config)
        once = voice_style.with_voice_style(make("smalltalk", partner="jake", engine="gemini_live_38"))
        self.assertIs(voice_style.with_voice_style(once), once)
        self.assertEqual((once.partner, once.engine), ("jake", "gemini_live_38"))


if __name__ == "__main__":
    unittest.main()
