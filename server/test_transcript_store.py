import unittest

from transcript_store import format_transcript

META = {"started_at": "2026-10-07 14:03:07", "duration_sec": 65, "model": "m", "mission": "x"}


def head(chunks, **extra):
    return format_transcript(chunks, {**META, **extra}).split("\n")


class CompletedTest(unittest.TestCase):
    def test_true(self):
        self.assertIn("- completed: yes", head([("Me", "hi")], completed=True))

    def test_false(self):
        self.assertIn("- completed: no", head([("Me", "hi")], completed=False))

    def test_missing(self):
        self.assertIn("- completed: no", head([("Me", "hi")]))


class CostTest(unittest.TestCase):
    def test_header_line_has_four_decimals_after_coach(self):
        lines = head([("Me", "hi")], cost_usd=0.01234)

        self.assertEqual(lines[lines.index("- coach: 0") + 1], "- cost_usd: 0.0123")

    def test_missing_or_unknown_cost_leaves_the_header_as_before(self):
        for extra in ({}, {"cost_usd": None}, {"cost_usd": "abc"}):
            with self.subTest(extra=extra):
                self.assertFalse([l for l in head([("Me", "hi")], **extra) if l.startswith("- cost_usd")])


class CoachTest(unittest.TestCase):
    def coach(self, chunks):
        line = [l for l in head(chunks) if l.startswith("- coach:")][0]
        return int(line.split(":")[1])

    def test_zero(self):
        self.assertEqual(self.coach([("Me", "hello there")]), 0)

    def test_multiple_in_merged_turn(self):
        self.assertEqual(
            self.coach([("Me", "Coach, I need a"), ("Me", "HINT. coach!"), ("Partner", "ok"), ("Me", "hint")]),
            4,
        )

    def test_partner_not_counted(self):
        self.assertEqual(self.coach([("Me", "hi"), ("Partner", "coach hint coach")]), 0)

    def test_coaching_not_counted(self):
        self.assertEqual(self.coach([("Me", "coaching hints coached")]), 0)


class VoiceTest(unittest.TestCase):
    def test_voice_line_follows_model(self):
        lines = head([("Me", "hi")], voice="Kore")
        self.assertEqual(lines[2:4], ["- model: m", "- voice: Kore"])

    def test_no_voice_leaves_header_as_before(self):
        self.assertFalse(any(l.startswith("- voice") for l in head([("Me", "hi")])))


class OrderTest(unittest.TestCase):
    def test_header_order(self):
        lines = head([("Me", "hi")], completed=True)
        self.assertTrue(lines[0].startswith("# Call "))
        self.assertEqual(
            [l.split(":")[0] for l in lines[1:6]],
            ["- mission", "- model", "- duration", "- completed", "- coach"],
        )
        self.assertEqual(lines[6], "")
        self.assertEqual(lines[7], "**Me:** hi")


if __name__ == "__main__":
    unittest.main()
