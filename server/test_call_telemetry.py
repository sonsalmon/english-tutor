import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.call_bot import format_telemetry

SAMPLE = {
    "t": 35,
    "vis": "visible",
    "ice": "connected",
    "conn": "connected",
    "dc": "open",
    "pair": "host/host/udp",
    "net": "vpn",
    "rtt": 213,
    "out_pk": 1750,
    "out_kb": 40,
    "in_pk": 1700,
    "in_lost": 3,
    "in_jit": 12,
    "in_kb": 38,
    "jbuf": 60,
    "rin_lost": 2,
    "rin_jit": 5,
    "mic": "live",
    "paused": 0,
    "rd": 0,
}


class FormatTelemetryTest(unittest.TestCase):
    def test_sample_becomes_one_compact_line(self):
        line = format_telemetry(SAMPLE)

        self.assertNotIn("\n", line)
        for part in ("vis=visible", "pair=host/host/udp", "rtt=213", "in_pk=1700", "mic=live", "paused=0", "rd=0"):
            self.assertIn(part, line)

    def test_missing_items_are_skipped(self):
        self.assertEqual(format_telemetry({"t": 5, "vis": "hidden"}), "vis=hidden t=5")

    def test_dead_reason_is_kept(self):
        self.assertIn("dead=silence", format_telemetry({**SAMPLE, "dead": "silence"}))

    def test_unknown_keys_and_unsafe_values_are_dropped(self):
        line = format_telemetry({"t": 1, "evil": "x", "vis": "visible\nINFO fake line", "pair": "a b", "mic": "x" * 40, "rtt": "9"})

        self.assertEqual(line, "t=1")

    def test_bad_numbers_are_dropped(self):
        line = format_telemetry({"t": True, "rtt": float("nan"), "in_pk": 10**15, "jbuf": 12.34})

        self.assertEqual(line, "jbuf=12.3")

    def test_non_dict_or_empty_yields_none(self):
        self.assertIsNone(format_telemetry(None))
        self.assertIsNone(format_telemetry("t=1"))
        self.assertIsNone(format_telemetry([1, 2]))
        self.assertIsNone(format_telemetry({}))
        self.assertIsNone(format_telemetry({"evil": 1}))


if __name__ == "__main__":
    unittest.main()
