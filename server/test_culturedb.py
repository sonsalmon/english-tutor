import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_culture_db  # noqa: E402
import culturedb  # noqa: E402


def _ann(en, ko, count):
    return {"answers": [ko], "en_answers": [en], "count": count}


KR = {
    "Food-01": {"en_question": "What do people eat for breakfast?", "annotations": [
        _ann("rice", "밥", 5), _ann("toast", "토스트", 3), _ann("soup", "국", 9)]},
    "Work-01": {"en_question": "How do people greet at a meeting?", "annotations": [_ann("bow", "인사", 2)]},
}
US = {
    "Food-01": {"en_question": "What do people eat for breakfast?", "annotations": [
        _ann("cereal", "", 7), _ann("eggs", "", 4)]},
    "Work-01": {"en_question": "How do people greet at a meeting?", "annotations": [_ann("handshake", "", 6)]},
}
BANK = [
    ("reddit", "US", "American", "coffee shop", "customer", "tips the barista", "tipping", 0.9, "Americans tip baristas at a cafe."),
    ("tiktok", "KR", "South Korean", "cafe", "student", "stays for hours", "cafe", 0.8, "Koreans study at a cafe for hours."),
    ("tiktok", "US", "American", "cafe", "person", "orders loudly", "cafe", 0.3, "Low agreement cafe behavior."),
]


class CultureDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "culture.db"
        build_culture_db.write_db(self.db, build_culture_db.blend_rows(KR, US), BANK)
        self.old = os.environ.get("CULTUREDB_PATH")
        os.environ["CULTUREDB_PATH"] = str(self.db)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CULTUREDB_PATH", None)
        else:
            os.environ["CULTUREDB_PATH"] = self.old
        self.tmp.cleanup()

    def test_blend_rows_top_by_count(self):
        rows = {r[0]: r for r in build_culture_db.blend_rows(KR, US)}
        self.assertEqual(rows["Food-01"][2], '["soup", "rice", "toast"]')
        self.assertEqual(rows["Food-01"][3], '["cereal", "eggs"]')

    def test_blend_search(self):
        res = culturedb.search(["breakfast"])
        self.assertEqual(res["blend"][0]["id"], "Food-01")
        self.assertEqual(res["blend"][0]["korea"][0], "soup")
        self.assertEqual(res["blend"][0]["us"][0], "cereal")

    def test_bank_filters_low_agreement(self):
        res = culturedb.search(["cafe"], limit_bank=5)
        texts = [b["text"] for b in res["bank"]]
        self.assertEqual(len(texts), 2)
        self.assertNotIn("Low agreement cafe behavior.", texts)

    def test_classify_group(self):
        c = build_culture_db.classify_group
        for g in ("American", "Americans", "US citizens", "People in the US", "African Americans", "Southern Americans"):
            self.assertEqual(c(g), "US", g)
        for g in ("Korean", "Koreans", "South Korean", "South Koreans", "Teens in South Korea"):
            self.assertEqual(c(g), "KR", g)
        for g in ("North Korean", "North Koreans", "Latin Americans", "Latin American", "British", "Koreatown locals"):
            self.assertIsNone(c(g), g)

    def test_bank_returns_country(self):
        res = culturedb.search(["cafe"], limit_bank=5)
        self.assertEqual({b["country"] for b in res["bank"]}, {"US", "KR"})
        self.assertTrue(all(b["group"] for b in res["bank"]))

    def test_or_terms_and_quotes(self):
        res = culturedb.search(['meeting', 'say "hi"'])
        self.assertEqual(res["blend"][0]["id"], "Work-01")

    def test_read_only(self):
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM blend")
        conn.close()

    def test_missing_db(self):
        os.environ["CULTUREDB_PATH"] = str(Path(self.tmp.name) / "none.db")
        self.assertFalse(culturedb.available())
        self.assertEqual(culturedb.search(["cafe"]), {"blend": [], "bank": []})

    def test_empty_terms(self):
        self.assertEqual(culturedb.search([]), {"blend": [], "bank": []})

    def test_attribution(self):
        self.assertEqual(culturedb.ATTRIBUTION, "출처: BLEnD (CC BY-SA 4.0), CultureBank (MIT)")


if __name__ == "__main__":
    unittest.main()
