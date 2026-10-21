import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.partner_memory import PARTNER_NAMES

PARTNERS_TS = Path(__file__).resolve().parent.parent / "src" / "lib" / "partners.ts"


class PartnersParityTest(unittest.TestCase):
    def test_ids_and_names_match_partners_ts(self):
        source = PARTNERS_TS.read_text(encoding="utf-8")
        entries = re.findall(r"^    id: '([a-z]+)',\n    name: '([^']+)',", source, re.MULTILINE)
        friends = {pid: name for pid, name in entries if pid != "park"}

        self.assertEqual(friends, PARTNER_NAMES)


if __name__ == "__main__":
    unittest.main()
