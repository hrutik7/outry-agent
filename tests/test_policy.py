"""Policy + record-keeping tests. Run: python3 -m unittest discover -s tests -v

Each test works on a fresh copy of data/seed/, never on the live demo data.
"""

import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import deskctl  # noqa: E402


class DeskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data").mkdir()
        for f in ("deals.csv", "approvals_log.csv"):
            shutil.copy(REPO / "data" / "seed" / f, self.tmp / "data" / f)
        os.environ["DESK_ROOT"] = str(self.tmp)
        os.environ["DESK_NOW"] = "2026-11-07T12:00:00+05:30"

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("DESK_ROOT", None)
        os.environ.pop("DESK_NOW", None)

    def deal(self, deal_id):
        return deskctl.get_deal(deskctl.load_deals(), deal_id)

    def log(self):
        with open(self.tmp / "data" / "approvals_log.csv", newline="") as f:
            return list(csv.DictReader(f))

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = deskctl.main(list(args))
        return code, buf.getvalue()


class PolicyMath(DeskTest):
    def test_floor_max_is_33(self):
        self.assertEqual(deskctl.max_discount_at_floor(), 33)

    def test_in_policy_brightline(self):
        ev = deskctl.evaluate(self.deal("D-1002"), 15)
        self.assertEqual(ev.verdict, deskctl.AUTO)
        self.assertEqual(ev.cap, 20)
        self.assertEqual(ev.list_tcv, 216_000)
        self.assertEqual(ev.net_tcv, 183_600)
        self.assertAlmostEqual(ev.margin, 0.6471, places=4)

    def test_needs_finance_acme(self):
        ev = deskctl.evaluate(self.deal("D-1001"), 25)
        self.assertEqual(ev.verdict, deskctl.FINANCE)
        self.assertEqual(ev.cap, 20)
        self.assertEqual(ev.net_tcv, 270_000)
        self.assertAlmostEqual(ev.margin, 0.60)
        self.assertIn("20% + annual prepay", ev.counter)

    def test_blocked_kestrel(self):
        ev = deskctl.evaluate(self.deal("D-1003"), 40)
        self.assertEqual(ev.verdict, deskctl.BLOCKED)
        self.assertAlmostEqual(ev.margin, 0.50)
        self.assertIn("33%", ev.counter)

    def test_boundaries(self):
        acme = self.deal("D-1001")
        self.assertEqual(deskctl.evaluate(acme, 20).verdict, deskctl.AUTO)
        self.assertEqual(deskctl.evaluate(acme, 33).verdict, deskctl.FINANCE)
        self.assertEqual(deskctl.evaluate(acme, 34).verdict, deskctl.BLOCKED)

    def test_caps_by_segment_seats_term(self):
        self.assertEqual(deskctl.auto_cap("Enterprise", 850, 3)[0], 25)  # 15+10 capped at 25
        self.assertEqual(deskctl.auto_cap("SMB", 300, 3)[0], 10)         # 15+5 capped at 10
        self.assertEqual(deskctl.auto_cap("Mid-Market", 50, 2)[0], 10)   # 10+0
        self.assertEqual(deskctl.auto_cap("Enterprise", 640, 5)[0], 25)  # 5 yrs counts as 3+

    def test_closed_deal_warns(self):
        ev = deskctl.evaluate(self.deal("D-1011"), 5)
        self.assertTrue(ev.warnings)


class Records(DeskTest):
    def test_lookup_rules(self):
        self.assertEqual(len(deskctl.find(deskctl.load_deals(), "acme")), 1)
        self.assertEqual(len(deskctl.find(deskctl.load_deals(), "juniper")), 2)
        self.assertEqual(deskctl.find(deskctl.load_deals(), "wayne"), [])
        code, out = self.run_cli("check", "D-9999", "10")
        self.assertEqual(code, 2)
        self.assertIn("do not invent", out)

    def test_auto_path_writes_quote(self):
        self.run_cli("check", "D-1002", "15", "--record")
        self.assertEqual(self.deal("D-1002")["status"], "open")  # auto deals never wait
        code, out = self.run_cli("approve", "D-1002", "15", "--by", "pricing", "--decision", "auto")
        self.assertEqual(code, 0, out)
        quote = (self.tmp / "quotes" / "D-1002.md").read_text()
        self.assertIn("$183,600", quote)
        self.assertIn("Auto-approved by policy", quote)
        self.assertEqual(self.deal("D-1002")["status"], "approved")
        self.assertEqual(self.log()[-1]["decision"], "auto_approved")

    def test_auto_refused_over_cap(self):
        code, out = self.run_cli("approve", "D-1001", "25", "--by", "pricing", "--decision", "auto")
        self.assertEqual(code, 2)
        self.assertIn("needs a human approval", out)
        self.assertFalse((self.tmp / "quotes" / "D-1001.md").exists())

    def test_finance_path(self):
        code, out = self.run_cli("check", "D-1001", "25", "--record")
        self.assertIn("pending_approval", out)
        self.assertEqual(self.deal("D-1001")["status"], "pending_approval")
        code, _ = self.run_cli("pending")
        code, out = self.run_cli("approve", "D-1001", "25", "--by", "finance-lead",
                                 "--decision", "approved")
        self.assertEqual(code, 0, out)
        row = self.log()[-1]
        self.assertEqual((row["deal_id"], row["decision"], row["decided_by"], row["final_pct"]),
                         ("D-1001", "approved", "finance-lead", "25"))
        self.assertEqual(self.deal("D-1001")["discount_pct"], "25")

    def test_counter_records_requested_and_final(self):
        self.run_cli("check", "D-1001", "25", "--record")
        self.run_cli("approve", "D-1001", "20", "--by", "finance-lead", "--decision", "countered",
                     "--note", "20% + annual prepay")
        row = self.log()[-1]
        self.assertEqual((row["requested_pct"], row["final_pct"], row["decision"]),
                         ("25", "20", "countered"))
        self.assertIn("prepaid upfront", (self.tmp / "quotes" / "D-1001.md").read_text())

    def test_blocked_cannot_be_approved(self):
        code, out = self.run_cli("approve", "D-1003", "40", "--by", "finance-lead",
                                 "--decision", "approved")
        self.assertEqual(code, 2)
        self.assertIn("below the 55% floor", out)
        self.assertFalse((self.tmp / "quotes" / "D-1003.md").exists())

    def test_reject(self):
        self.run_cli("check", "D-1003", "40", "--record")
        code, out = self.run_cli("reject", "D-1003", "--by", "finance-lead", "--reason", "below floor")
        self.assertEqual(code, 0)
        self.assertEqual(self.deal("D-1003")["status"], "rejected")
        self.assertEqual(self.log()[-1]["decision"], "rejected")
        code, out = self.run_cli("approve", "D-1003", "20", "--by", "x", "--decision", "approved")
        self.assertEqual(code, 2)  # decided deals stay decided


if __name__ == "__main__":
    unittest.main()
