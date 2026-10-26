import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from scripts import naturalness_metrics as M


def db_track(total_s, loud_ranges, frame_s=0.02):
    """loud_ranges 구간은 -20 dB, 나머지는 -90 dB인 프레임별 dB 목록."""
    db = [-90.0] * int(round(total_s / frame_s))
    for start, end in loud_ranges:
        for i in range(int(round(start / frame_s)), int(round(end / frame_s))):
            db[i] = -20.0
    return db


class SegmentsTest(unittest.TestCase):
    def test_merges_short_gaps_and_drops_blips(self):
        db = db_track(5.0, [(0.5, 1.0), (1.2, 1.6), (3.0, 3.04)])

        segs = M.speech_segments(db, merge_gap_s=0.3, min_speech_s=0.12)

        self.assertEqual(segs, [(0.5, 1.6)])

    def test_gap_longer_than_merge_keeps_two_segments(self):
        db = db_track(5.0, [(0.5, 1.0), (2.0, 2.5)])

        self.assertEqual(M.speech_segments(db), [(0.5, 1.0), (2.0, 2.5)])

    def test_frame_db_reads_int16_levels(self):
        loud = (np.ones(16000) * 3277).astype(np.int16)
        quiet = np.zeros(16000, dtype=np.int16)

        db = M.frame_db(np.concatenate([quiet, loud]), 16000)

        self.assertEqual(len(db), 100)
        self.assertLess(db[10], -100)
        self.assertAlmostEqual(db[60], -20.0, delta=0.5)

    def test_leading_speech_returns_first_word_only(self):
        db = db_track(2.0, [(0.2, 0.5), (0.8, 1.6)])

        self.assertEqual(M.leading_speech(db, gap_s=0.1), (0.2, 0.5))

    def test_speech_bounds_spans_first_to_last_sound(self):
        db = db_track(3.0, [(0.3, 0.6), (1.5, 2.4)])

        self.assertEqual(M.speech_bounds(db), (0.3, 2.4))


class TimingMetricsTest(unittest.TestCase):
    def test_response_gap_skips_greeting_that_ended_before_learner(self):
        segs = [(1.0, 4.0), (9.5, 12.0)]

        self.assertEqual(M.response_gap_ms(8.0, segs), 1500)

    def test_response_gap_is_negative_when_partner_talks_over(self):
        segs = [(1.0, 4.0), (7.5, 12.0)]

        self.assertEqual(M.response_gap_ms(8.0, segs), -500)

    def test_response_gap_none_without_reply(self):
        self.assertIsNone(M.response_gap_ms(8.0, [(1.0, 4.0)]))

    def test_pause_false_starts_counts_onsets_inside_pause_only(self):
        segs = [(1.0, 4.0), (6.2, 6.8), (9.0, 11.0)]

        self.assertEqual(M.pause_false_starts(5.0, 8.0, segs), [6.2])
        self.assertEqual(M.pause_false_starts(7.0, 8.0, segs), [])

    def test_stop_latency_when_partner_stops_after_barge_in(self):
        segs = [(1.0, 4.4), (6.0, 9.0)]

        result = M.stop_latency(segs, 3.0)

        self.assertEqual(result["status"], "stopped")
        self.assertAlmostEqual(result["latency_s"], 1.4)

    def test_stop_latency_reports_no_stop_and_not_speaking(self):
        segs = [(1.0, 20.0)]

        self.assertEqual(M.stop_latency(segs, 3.0, limit_s=6.0)["status"], "no_stop")
        self.assertEqual(M.stop_latency(segs, 25.0)["status"], "not_speaking")

    def test_backchannel_kept_going_when_speech_continues_past_hold(self):
        segs = [(1.0, 9.0)]

        self.assertEqual(M.backchannel_outcome(segs, 2.5, 3.1, hold_s=1.0)["status"], "kept_going")

    def test_backchannel_stopped_reports_when_and_next_onset(self):
        segs = [(1.0, 3.4), (5.0, 8.0)]

        result = M.backchannel_outcome(segs, 2.5, 3.1, hold_s=1.0)

        self.assertEqual(result["status"], "stopped")
        self.assertAlmostEqual(result["stopped_after_s"], 0.9)
        self.assertAlmostEqual(result["next_onset_s"], 1.6)

    def test_backchannel_invalid_when_partner_silent(self):
        self.assertEqual(M.backchannel_outcome([(1.0, 2.0)], 2.5, 3.1)["status"], "invalid")

    def test_reengage_seconds_within_and_beyond_horizon(self):
        segs = [(1.0, 4.0), (11.5, 13.0)]

        self.assertAlmostEqual(M.reengage_seconds(segs, 4.0, 18.0), 7.5)
        self.assertIsNone(M.reengage_seconds(segs, 4.0, 5.0))
        self.assertIsNone(M.reengage_seconds([(1.0, 4.0)], 4.0, 18.0))

    def test_in_range_uses_thresholds(self):
        self.assertTrue(M.in_range(1200, "gap_ms"))
        self.assertFalse(M.in_range(300, "gap_ms"))
        self.assertTrue(M.in_range(0, "false_starts"))
        self.assertFalse(M.in_range(1, "false_starts"))
        self.assertTrue(M.in_range(800, "stop_latency_ms"))
        self.assertFalse(M.in_range(None, "stop_latency_ms"))


class TextMetricsTest(unittest.TestCase):
    def test_parse_transcript_reads_both_speakers(self):
        md = "# Call\n- partner: jake\n\n**Partner:** Hey there! How are you?\n**Me:** Pretty good.\n**Partner:** Nice."

        self.assertEqual(
            M.parse_transcript(md),
            [("Partner", "Hey there! How are you?"), ("Me", "Pretty good."), ("Partner", "Nice.")],
        )

    def test_ends_with_question_ignores_trailing_quote(self):
        self.assertTrue(M.ends_with_question('He said "really?"'))
        self.assertFalse(M.ends_with_question("That is fine."))

    def test_statement_words_ignores_question_sentences(self):
        text = "Yeah, I had the same thing last week at work. Did you sleep well?"

        self.assertEqual(M.statement_words(text), 10)

    def test_partner_turn_stats_median_and_question_rate(self):
        turns = [
            ("Partner", "Hey! How is your day going?"),
            ("Me", "Fine."),
            ("Partner", "Nice. I just got back from a long run and my legs feel like jelly."),
            ("Partner", "Anyway."),
        ]

        stats = M.partner_turn_stats(turns)

        self.assertEqual(stats["turns"], 3)
        self.assertEqual(stats["words"], [6, 15, 1])
        self.assertEqual(stats["words_median"], 6)
        self.assertAlmostEqual(stats["question_rate"], 0.333, places=3)

    def test_partner_turn_stats_empty(self):
        self.assertIsNone(M.partner_turn_stats([("Me", "hi")])["words_median"])


class PauseIntrusionsTest(unittest.TestCase):
    P0, P1 = 10.0, 12.0

    def judge(self, segs, texts, rest_words=(), rest_text=""):
        return M.pause_intrusions(self.P0, self.P1, segs, texts, rest_words, rest_text)

    def test_no_onset_in_pause_is_waited(self):
        out = self.judge([(5.0, 9.0), (12.5, 14.0)], [])

        self.assertEqual((out["verdict"], out["kind"]), ("PASS", "waited"))

    def test_take_your_time_passes(self):
        out = self.judge([(10.5, 11.4)], [(10.6, "Take your time.")])

        self.assertEqual((out["verdict"], out["kind"]), ("PASS", "wait_signal"))

    def test_mm_hm_take_your_time_passes_at_five_words(self):
        out = self.judge([(10.5, 11.6)], [(10.6, "Mm-hm, take your time.")])

        self.assertEqual((out["verdict"], out["kind"]), ("PASS", "wait_signal"))

    def test_question_fails(self):
        for text in ("No rush, dude. You good?", "Oh, no way! Your internship?"):
            out = self.judge([(10.5, 12.1)], [(10.6, text)])

            self.assertEqual((out["verdict"], out["kind"]), ("FAIL", "question"), text)

    def test_two_signals_fail_as_multiple(self):
        out = self.judge([(10.4, 10.9), (11.2, 11.8)], [(10.5, "Mm-hm."), (11.3, "Take your time.")])

        self.assertEqual((out["verdict"], out["kind"]), ("FAIL", "multiple"))

    def test_silent_short_sound_passes_and_long_one_cannot_be_verified(self):
        short = self.judge([(10.5, 11.3)], [])
        long = self.judge([(10.5, 11.9)], [])

        self.assertEqual((short["verdict"], short["kind"]), ("PASS", "wait_signal"))
        self.assertEqual((long["verdict"], long["kind"]), ("FAIL", "unverifiable"))

    def test_finishing_the_learners_sentence_fails(self):
        out = self.judge(
            [(10.5, 11.5)], [(10.6, "Cloud subscription.")], rest_words=M.content_words("Uh cloud sub uh subscription"),
        )

        self.assertEqual((out["verdict"], out["kind"]), ("FAIL", "finished_sentence"))

    def test_six_words_and_off_topic_fail(self):
        long = self.judge([(10.5, 11.5)], [(10.6, "Mm-hm take your time, I'm listening.")])
        off = self.judge([(10.5, 11.5)], [(10.6, "Pizza tonight.")])

        self.assertEqual(long["kind"], "long")
        self.assertEqual((off["verdict"], off["kind"]), ("FAIL", "off_topic"))

    def test_sound_running_on_after_the_learner_resumes_fails(self):
        out = self.judge([(11.5, 12.6)], [(11.6, "Take your time.")])

        self.assertEqual((out["verdict"], out["kind"]), ("FAIL", "long"))


class YeahFollowupTest(unittest.TestCase):
    def test_counter_question_to_the_mac_mishearing_is_question_only(self):
        out = M.yeah_followup("Wait, were you thinking of a Mac or maybe something else?")

        self.assertEqual((out["kind"], out["statement_words"]), ("question_only", 0))

    def test_story_then_question_and_question_first(self):
        story_q = "Yeah, I had the same thing last week at work. Did you sleep well?"
        q_first = "Did you sleep well? I had the same thing last week at work, and it was rough."

        self.assertEqual(M.yeah_followup(story_q)["kind"], "story_then_question")
        self.assertEqual(M.yeah_followup(q_first)["kind"], "question_first")

    def test_story_and_missing_replies(self):
        self.assertEqual(M.yeah_followup("I had the same thing last week at work. It took me three days to recover.")["kind"], "story")
        self.assertEqual(M.yeah_followup("", partner_spoke=False)["kind"], "no_reply")
        self.assertEqual(M.yeah_followup("", partner_spoke=True)["kind"], "unverifiable")


class ReengageKindTest(unittest.TestCase):
    def test_presence_check(self):
        for text in ("You still there?", "Are you there?", "Hello? Can you hear me?"):
            self.assertEqual(M.reengage_kind(text), "presence_check", text)

    def test_question_content_and_none(self):
        self.assertEqual(M.reengage_kind("What about you?"), "question")
        self.assertEqual(M.reengage_kind("So anyway, I was thinking about that trip we talked about."), "content")
        self.assertEqual(M.reengage_kind(""), "none")

    def test_threshold_is_nine_to_fourteen_seconds(self):
        self.assertTrue(M.in_range(10.9, "reengage_s"))
        self.assertFalse(M.in_range(8.0, "reengage_s"))
        self.assertFalse(M.in_range(15.0, "reengage_s"))


class BargeHeardTest(unittest.TestCase):
    def test_pass_when_the_partner_answers_a_sentence_with_the_content_words(self):
        turns = [("Partner", "Long story..."), ("Me", "I have a time limit for this conversation."), ("Partner", "Oh, got it.")]

        self.assertEqual(M.barge_heard(turns)["verdict"], "PASS")

    def test_fail_when_missing_or_unanswered(self):
        self.assertEqual(M.barge_heard([("Me", "Hello."), ("Partner", "Hi.")])["verdict"], "FAIL")
        self.assertEqual(M.barge_heard([("Me", "I have a time limit.")])["verdict"], "FAIL")

    def test_scored_metric_keeps_verdict_and_reason_in_their_fields(self):
        from scripts import naturalness_qa as Q

        heard = Q.barge_heard_metric([("Partner", "Long story..."), ("Me", "I have a time limit for this conversation."), ("Partner", "Oh, got it.")])
        missed = Q.barge_heard_metric([("Me", "Hello."), ("Partner", "Hi.")])

        self.assertEqual((heard["verdict"], type(heard["note"])), ("PASS", str))
        self.assertEqual((missed["verdict"], type(missed["note"])), ("FAIL", str))


if __name__ == "__main__":
    unittest.main()
