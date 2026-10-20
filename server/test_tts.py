import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import tts


class FakeModels:
    def __init__(self, pcm=b"\x01\x00" * 2400, fail_models=()):
        self.pcm = pcm
        self.fail_models = fail_models
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model in self.fail_models:
            raise RuntimeError("404 model not found")
        inline = SimpleNamespace(data=self.pcm, mime_type="audio/L16;rate=24000")
        part = SimpleNamespace(inline_data=inline)
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


class FakeClient:
    def __init__(self, **kwargs):
        self.models = FakeModels(**kwargs)


class TtsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"TTS_DIR": self.tmp.name}, clear=False)
        patcher.start()
        os.environ.pop("TTS_MODEL", None)
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        model_patch = mock.patch.object(tts, "TTS_MODEL", tts.DEFAULT_TTS_MODEL)
        model_patch.start()
        self.addCleanup(model_patch.stop)

    def test_wav_header(self):
        client = FakeClient()
        wav = tts.synthesize("Hello there.", "Leda", client=client)
        pcm = client.models.pcm
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:16], b"WAVEfmt ")
        self.assertEqual(struct.unpack("<I", wav[4:8])[0], 36 + len(pcm))
        fmt = struct.unpack("<HHIIHH", wav[20:36])
        self.assertEqual(fmt, (1, 1, 24000, 48000, 2, 16))
        self.assertEqual(wav[36:40], b"data")
        self.assertEqual(struct.unpack("<I", wav[40:44])[0], len(pcm))
        self.assertEqual(wav[44:], pcm)

    def test_cache_hit_skips_second_call(self):
        client = FakeClient()
        first = tts.synthesize("Hello there.", "Leda", client=client)
        second = tts.synthesize("Hello there.", "Leda", client=client)
        self.assertEqual(first, second)
        self.assertEqual(len(client.models.calls), 1)
        tts.synthesize("Hello there.", "Kore", client=client)
        self.assertEqual(len(client.models.calls), 2)

    def test_fallback_cache_found_after_restart_before_any_model_call(self):
        first = FakeClient(fail_models=("gemini-2.5-flash-tts",))
        wav = tts.synthesize("Hi.", "Leda", client=first)
        # 재시작: 전역 모델이 기본값으로 돌아온 상태에서 같은 문장을 요청한다.
        with mock.patch.object(tts, "TTS_MODEL", tts.DEFAULT_TTS_MODEL):
            second = FakeClient(fail_models=("gemini-2.5-flash-tts",))
            self.assertEqual(tts.synthesize("Hi.", "Leda", client=second), wav)
        self.assertEqual(second.models.calls, [])

    def test_validation(self):
        client = FakeClient()
        for text, voice in [("", "Leda"), ("x" * 501, "Leda"), ("hi", "Le da"), ("hi", ""), ("hi", "../x"), ("hi", "Leda1")]:
            with self.assertRaises(ValueError):
                tts.synthesize(text, voice, client=client)
        self.assertEqual(client.models.calls, [])
        tts.synthesize("x" * 500, "Leda", client=client)

    def test_fallback_model(self):
        client = FakeClient(fail_models=("gemini-2.5-flash-tts",))
        tts.synthesize("Hi.", "Leda", client=client)
        self.assertEqual(client.models.calls, ["gemini-2.5-flash-tts", "gemini-2.5-flash-preview-tts"])

    def test_typed_error(self):
        client = FakeClient(fail_models=(tts.DEFAULT_TTS_MODEL, *tts.FALLBACK_MODELS))
        with self.assertRaises(tts.TTSError):
            tts.synthesize("Hi.", "Leda", client=client)

    def test_no_audio_is_typed_error(self):
        client = FakeClient(pcm=b"")
        with self.assertRaises(tts.TTSError):
            tts.synthesize("Hi.", "Leda", client=client)


if __name__ == "__main__":
    unittest.main()
