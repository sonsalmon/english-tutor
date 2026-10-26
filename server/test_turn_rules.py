import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import turn_rules
from server.call_bot import CallConfig


def config(mode, partner="jake"):
    return CallConfig(system_instruction="BASE INSTRUCTION", mode=mode, partner=partner)


class ParseRulesTest(unittest.TestCase):
    def test_unset_means_both_rules(self):
        self.assertEqual(turn_rules.parse_rules({}), ("hesitation", "backchannel"))

    def test_off_and_empty_mean_no_rules(self):
        self.assertEqual(turn_rules.parse_rules({"LIVE_TURN_RULES": "off"}), ())
        self.assertEqual(turn_rules.parse_rules({"LIVE_TURN_RULES": ""}), ())

    def test_single_rule_and_unknown_names(self):
        self.assertEqual(turn_rules.parse_rules({"LIVE_TURN_RULES": "backchannel"}), ("backchannel",))
        self.assertEqual(turn_rules.parse_rules({"LIVE_TURN_RULES": " Hesitation , nonsense "}), ("hesitation",))


class WithTurnRulesTest(unittest.TestCase):
    def test_chat_modes_get_both_blocks_after_the_base(self):
        for mode in ("smalltalk", "freetalk"):
            out = turn_rules.with_turn_rules(config(mode), {})
            self.assertTrue(out.system_instruction.startswith("BASE INSTRUCTION"))
            self.assertIn(turn_rules.HESITATION, out.system_instruction)
            self.assertIn(turn_rules.BACKCHANNEL, out.system_instruction)

    def test_switch_removes_one_or_all_blocks(self):
        only_h = turn_rules.with_turn_rules(config("smalltalk"), {"LIVE_TURN_RULES": "hesitation"})
        self.assertIn(turn_rules.HESITATION, only_h.system_instruction)
        self.assertNotIn(turn_rules.BACKCHANNEL, only_h.system_instruction)
        off = config("smalltalk")
        self.assertIs(turn_rules.with_turn_rules(off, {"LIVE_TURN_RULES": "off"}), off)

    def test_other_modes_are_untouched(self):
        for mode in ("mission", "teachback"):
            cfg = config(mode, partner=None)
            self.assertIs(turn_rules.with_turn_rules(cfg, {}), cfg)

    def test_suffix_stays_within_word_limit(self):
        text = turn_rules.suffix(turn_rules.DEFAULT_RULES)
        self.assertLessEqual(len(text.split()), turn_rules.SUFFIX_MAX_WORDS)


if __name__ == "__main__":
    unittest.main()
