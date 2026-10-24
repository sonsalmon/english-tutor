import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from types import SimpleNamespace

from google.genai.types import ActivityHandling, AutomaticActivityDetection, LiveConnectConfig, RealtimeInputConfig
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

from server import call_bot


def connect(env, config=None):
    """상속 클래스의 _connection_task_handler를 네트워크 없이 돌려 super()가 받은 config를 돌려준다."""
    service = object.__new__(call_bot.live_service_class())
    config = config or LiveConnectConfig()
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

    def test_barge_in_turns_off_gemini_interruption_only_with_gemini_vad(self):
        def vad_config(disabled=False):
            return LiveConnectConfig(realtime_input_config=RealtimeInputConfig(
                automatic_activity_detection=AutomaticActivityDetection(disabled=disabled)))

        handling = lambda env, cfg: connect(env, cfg).realtime_input_config.activity_handling
        self.assertEqual(handling({}, vad_config()), ActivityHandling.NO_INTERRUPTION)
        self.assertIsNone(handling({"LIVE_BARGE_IN_WORDS": "0"}, vad_config()))
        self.assertIsNone(handling({}, vad_config(disabled=True)))  # TURN_MODE=smart: 로컬 VAD가 끊는다
        self.assertIsNone(connect({}).realtime_input_config)

    def test_partner_keeps_talking_through_backchannel_and_stops_on_real_words(self):
        service = object.__new__(call_bot.live_service_class())
        service._barge_in_words, service._partner_speaking, service._heard_words = 3, True, 0
        service._drop_rest_of_turn, service._bot_is_responding, service._turn_complete_pending_idle = False, True, None
        service.broadcast_interruption = mock.AsyncMock()
        say = lambda text: asyncio.run(service._handle_msg_input_transcription(
            SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text=text)))))
        base = mock.AsyncMock()
        with mock.patch.object(GeminiLiveLLMService, "_handle_msg_input_transcription", base):
            say("Mm-hmm, yeah.")
            say(" Uh-huh {}")
            service.broadcast_interruption.assert_not_awaited()
            say(" Wait, I")
            service.broadcast_interruption.assert_not_awaited()
            say(" have")
        service.broadcast_interruption.assert_awaited_once()
        self.assertEqual(base.await_count, 4)  # 자막은 끊기와 상관없이 그대로 나간다
        self.assertTrue(service._drop_rest_of_turn)

        model_turn, turn_complete = mock.AsyncMock(), mock.AsyncMock()
        with mock.patch.object(GeminiLiveLLMService, "_handle_msg_model_turn", model_turn), mock.patch.object(
            GeminiLiveLLMService, "_handle_msg_turn_complete", turn_complete
        ):
            asyncio.run(service._handle_msg_model_turn("rest of the old turn"))
            model_turn.assert_not_awaited()
            asyncio.run(service._handle_msg_turn_complete("done"))
            asyncio.run(service._handle_msg_model_turn("the answer"))
        model_turn.assert_awaited_once()
        turn_complete.assert_awaited_once()

    def test_barge_in_after_generation_finished_drops_nothing(self):
        # 생성이 이미 끝난(재생만 남은) 차례를 끊으면 다음 turn_complete는 대답의 것이다. 버리면 대답이 사라진다.
        for responding, pending in ((False, None), (True, object())):
            service = object.__new__(call_bot.live_service_class())
            service._barge_in_words, service._partner_speaking, service._heard_words = 3, True, 0
            service._drop_rest_of_turn, service._bot_is_responding = False, responding
            service._turn_complete_pending_idle = pending
            service.broadcast_interruption = mock.AsyncMock()
            msg = SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text="wait a second please")))
            with mock.patch.object(GeminiLiveLLMService, "_handle_msg_input_transcription", mock.AsyncMock()):
                asyncio.run(service._handle_msg_input_transcription(msg))
            service.broadcast_interruption.assert_awaited_once()
            self.assertFalse(service._drop_rest_of_turn)

    def test_unset_env_uses_default_languages(self):
        self.assertEqual(call_bot.live_input_languages({}), ["en-US", "ko-KR"])
        self.assertEqual(call_bot.live_input_languages({"LIVE_INPUT_LANGUAGES": ""}), [])


if __name__ == "__main__":
    unittest.main()
