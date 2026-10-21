import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai.types import LiveConnectConfig
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

from server import call_bot


def connect(env):
    """상속 클래스의 _connection_task_handler를 네트워크 없이 돌려 super()가 받은 config를 돌려준다."""
    service = object.__new__(call_bot.live_service_class())
    config = LiveConnectConfig()
    base = mock.AsyncMock()
    with mock.patch.object(GeminiLiveLLMService, "_connection_task_handler", base), mock.patch.dict(
        "os.environ", env, clear=False
    ):
        asyncio.run(service._connection_task_handler(config))
    base.assert_awaited_once()
    return base.await_args.args[0] if base.await_args.args else base.await_args.kwargs["config"]


class LiveServiceTest(unittest.TestCase):
    def test_default_hint_is_english_and_korean(self):
        config = connect({"LIVE_INPUT_LANGUAGES": "en-US,ko-KR"})

        self.assertEqual(config.input_audio_transcription.language_codes, ["en-US", "ko-KR"])

    def test_env_overrides_hint(self):
        config = connect({"LIVE_INPUT_LANGUAGES": " en-US "})

        self.assertEqual(config.input_audio_transcription.language_codes, ["en-US"])

    def test_empty_env_adds_no_hint(self):
        config = connect({"LIVE_INPUT_LANGUAGES": ""})

        self.assertIsNone(config.input_audio_transcription)

    def test_unset_env_uses_default_languages(self):
        self.assertEqual(call_bot.live_input_languages({}), ["en-US", "ko-KR"])
        self.assertEqual(call_bot.live_input_languages({"LIVE_INPUT_LANGUAGES": ""}), [])


if __name__ == "__main__":
    unittest.main()
