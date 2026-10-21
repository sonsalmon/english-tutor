import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.transcript_clean import clean_learner_text

# src/lib/transcript.test.ts가 같은 표를 쓴다. 한쪽을 고치면 다른 쪽도 고친다.
CASES = [
    ("嗯", "(mm)"),
    ("嗯嗯嗯", "(mm)"),
    ("呃…", "(mm)"),
    ("こんにちは", "(mm)"),
    ("嗯" * 12, "(mm)"),
    ("嗯" * 13, "(unclear)"),
    ("嗯 I think", "I think"),
    ("我想去 the store", "the store"),
    ("嗯 음 hello", "음 hello"),
    ("음", "음"),
    ("mm", "mm"),
    ("I think so", "I think so"),
    ("(mm)", "(mm)"),
    ("", ""),
]


class CleanLearnerTextTest(unittest.TestCase):
    def test_input_table(self):
        for text, expected in CASES:
            with self.subTest(text=text):
                self.assertEqual(clean_learner_text(text), expected)


if __name__ == "__main__":
    unittest.main()
