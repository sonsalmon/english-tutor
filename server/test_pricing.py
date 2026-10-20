import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import types

from server import pricing, tutor
from server.pricing import UsageTotals


def usage_metadata(prompt, candidates, thoughts=0, audio_in=0, audio_out=0):
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        tool_use_prompt_token_count=0,
        prompt_tokens_details=[SimpleNamespace(modality=types.MediaModality.AUDIO, token_count=audio_in)] if audio_in else None,
        candidates_tokens_details=[SimpleNamespace(modality=types.MediaModality.AUDIO, token_count=audio_out)] if audio_out else None,
    )


class PriceTableTest(unittest.TestCase):
    def test_constants_match_the_published_table(self):
        self.assertEqual(pricing.PRICING_SOURCE_URL, "https://ai.google.dev/gemini-api/docs/pricing")
        self.assertEqual(pricing.PRICING_DATE, "2026-10-20")
        self.assertEqual(
            pricing.PRICES["gemini-live-2.5-flash-native-audio"],
            {"input_text": 0.50, "input_audio": 3.00, "output_text": 2.00, "output_audio": 12.00},
        )
        tutor_prices = pricing.PRICES["gemini-2.5-flash"]
        self.assertEqual((tutor_prices["input_text"], tutor_prices["input_audio"], tutor_prices["output_text"]), (0.30, 1.00, 2.50))

    def test_one_million_tokens_of_each_kind_costs_its_price(self):
        for model, prices in pricing.PRICES.items():
            for key, price in prices.items():
                with self.subTest(model=model, key=key):
                    self.assertEqual(pricing.estimate_cost(model, UsageTotals(**{key: 1_000_000})), price)

    def test_cost_math_mixes_the_four_kinds(self):
        usage = UsageTotals(input_text=2_000, input_audio=10_000, output_text=500, output_audio=3_000)

        self.assertEqual(usage.cost(pricing.LIVE_MODEL), round((2000 * 0.5 + 10_000 * 3.0 + 500 * 2.0 + 3000 * 12.0) / 1e6, 6))

    def test_unknown_model_has_no_cost(self):
        self.assertIsNone(pricing.estimate_cost("some-other-model", UsageTotals(input_text=5)))

    def test_combine_cost(self):
        self.assertEqual(pricing.combine_cost(0.01, 0.002), {"live": 0.01, "tutoring": 0.002, "total": 0.012})
        self.assertEqual(pricing.combine_cost(0.01, None), {"live": 0.01, "tutoring": None, "total": 0.01})
        self.assertEqual(pricing.combine_cost(None, None), {"live": None, "tutoring": None, "total": None})


class UsageSumTest(unittest.TestCase):
    def test_add_tokens_splits_audio_from_text_and_clamps(self):
        usage = UsageTotals()
        usage.add_tokens(1000, 200, 800, 150)
        usage.add_tokens(500, 50, None, None)
        usage.add_tokens(100, 10, 999, 999)

        self.assertEqual((usage.input_text, usage.input_audio, usage.output_text, usage.output_audio), (200 + 500, 800 + 100, 50 + 50, 150 + 10))

    def test_metadata_counts_thinking_as_output_and_audio_from_details(self):
        usage = UsageTotals()
        usage.add_metadata(usage_metadata(1000, 100, thoughts=50, audio_in=900))
        usage.add_metadata(None)

        self.assertEqual((usage.input_text, usage.input_audio, usage.output_text, usage.output_audio), (100, 900, 150, 0))
        self.assertFalse(usage.is_empty())
        self.assertTrue(UsageTotals().is_empty())


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        if isinstance(contents, list):
            return SimpleNamespace(text="I just start my day", usage_metadata=usage_metadata(1000, 20, audio_in=900))
        body = {"corrections": [{"said": "I just start", "better": "I just started", "why": "과거형을 써요."}]}
        return SimpleNamespace(text=json.dumps(body), usage_metadata=usage_metadata(2000, 300, thoughts=100))


class RunTutoringCostTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = {"AUDIO_DIR": str(root / "audio"), "TUTORING_DIR": str(root / "tutoring"), "TEACHBACK_DIR": str(root / "teachback")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("TUTOR_MODEL", None)
        (root / "audio").mkdir()
        self.root = root
        self.md = root / "2026-10-20-090000.md"
        self.md.write_text("**Me:** I just start my day\n", encoding="utf-8")
        self.models = FakeModels()
        client = mock.patch.object(tutor, "_make_client", return_value=SimpleNamespace(models=self.models))
        client.start()
        self.addCleanup(client.stop)

    def test_every_vertex_call_of_the_analysis_is_summed_into_cost_usd(self):
        (self.root / "audio" / "2026-10-20-090000.wav").write_bytes(b"RIFF")

        data, saved = tutor.run_tutoring(self.md)

        expected = round((2100 * 0.30 + 900 * 1.00 + 420 * 2.50) / 1_000_000, 6)
        self.assertEqual(len(self.models.calls), 2)
        self.assertEqual(data["cost_usd"], expected)
        self.assertTrue(saved)
        stored = json.loads((self.root / "tutoring" / "2026-10-20-090000.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["cost_usd"], expected)

    def test_without_audio_only_the_text_analysis_counts(self):
        data, _saved = tutor.run_tutoring(self.md)

        self.assertEqual(data["cost_usd"], round((2000 * 0.30 + 400 * 2.50) / 1_000_000, 6))

    def test_injected_fakes_leave_no_cost(self):
        fake = json.dumps({"corrections": [{"said": "a", "better": "b", "why": "c"}]})

        data, _saved = tutor.run_tutoring(self.md, generate_text=lambda prompt: fake)

        self.assertNotIn("cost_usd", data)

    def test_unknown_tutor_model_leaves_no_cost(self):
        with mock.patch.dict(os.environ, {"TUTOR_MODEL": "some-other-model"}):
            data, _saved = tutor.run_tutoring(self.md)

        self.assertNotIn("cost_usd", data)

    def test_usage_is_not_recorded_outside_a_tracked_analysis(self):
        tutor.record_usage(SimpleNamespace(usage_metadata=usage_metadata(10, 10)))

        with tutor.track_usage() as usage:
            pass
        self.assertTrue(usage.is_empty())


if __name__ == "__main__":
    unittest.main()
