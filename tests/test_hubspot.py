"""HubSpot backend against an in-memory fake of the HubSpot API (no network).

Run: python3 -m unittest discover -s tests -v
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import crm_hubspot  # noqa: E402
import deskctl  # noqa: E402


class FakeHubSpot:
    def __init__(self):
        self.deals, self.notes, self.props, self.next_id = {}, [], set(), 9000

    def __call__(self, method, path, body=None):
        url = urlparse(path)
        p = url.path
        if p == "/crm/v3/properties/deals/groups":
            return {}
        if p == "/crm/v3/properties/deals":
            if body["name"] in self.props:
                raise crm_hubspot.CRMError("409 conflict")
            self.props.add(body["name"])
            return {}
        if p == "/crm/v3/pipelines/deals":
            ids = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled",
                   "decisionmakerboughtin", "contractsent", "closedwon", "closedlost"]
            return {"results": [{"id": "default", "stages": [{"id": i} for i in ids]}]}
        if p == "/account-info/v3/details":
            return {"portalId": 4242, "uiDomain": "app.hubspot.com"}
        if p == "/crm/v3/objects/deals" and method == "GET":
            assert "dd_deal_id" in parse_qs(url.query)["properties"][0]
            return {"results": [{"id": i, "properties": dict(d)} for i, d in self.deals.items()]}
        if p == "/crm/v3/objects/deals" and method == "POST":
            self.next_id += 1
            self.deals[str(self.next_id)] = dict(body["properties"])
            return {"id": str(self.next_id)}
        if p.startswith("/crm/v3/objects/deals/") and method == "PATCH":
            self.deals[p.rsplit("/", 1)[1]].update(body["properties"])
            return {}
        if p == "/crm/v3/objects/notes":
            self.notes.append(body)
            return {"id": "n1"}
        raise AssertionError(f"unexpected {method} {path}")

    def by_desk_id(self, deal_id):
        return next(d for d in self.deals.values() if d["dd_deal_id"] == deal_id)


class HubSpotFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data").mkdir()
        for f in ("deals.csv", "approvals_log.csv"):
            shutil.copy(REPO / "data" / "seed" / f, self.tmp / "data" / f)
        os.environ.update(DESK_ROOT=str(self.tmp), DESK_BACKEND="hubspot",
                          DESK_NOW="2026-11-07T12:00:00+05:30")
        self.fake = FakeHubSpot()
        self._real = crm_hubspot._http
        crm_hubspot._http = self.fake
        crm_hubspot.setup()
        crm_hubspot.seed(REPO / "data" / "seed" / "deals.csv")

    def tearDown(self):
        crm_hubspot._http = self._real
        shutil.rmtree(self.tmp)
        for k in ("DESK_ROOT", "DESK_BACKEND", "DESK_NOW"):
            os.environ.pop(k, None)

    def cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = deskctl.main(list(args))
        return code, buf.getvalue()

    def test_seed_is_idempotent(self):
        self.assertEqual(len(self.fake.deals), 15)
        self.assertIn("15 reset", crm_hubspot.seed(REPO / "data" / "seed" / "deals.csv"))
        self.assertEqual(len(self.fake.deals), 15)
        acme = self.fake.by_desk_id("D-1001")
        self.assertEqual((acme["dealname"], acme["amount"], acme["dealstage"]),
                         ("Acme Corp", "360000", "decisionmakerboughtin"))

    def test_counter_flow_updates_hubspot(self):
        code, out = self.cli("check", "D-1001", "25", "--record")
        self.assertIn("NEEDS_FINANCE", out)
        self.assertEqual(self.fake.by_desk_id("D-1001")["dd_status"], "pending_approval")

        code, out = self.cli("approve", "D-1001", "20", "--by", "user",
                             "--decision", "countered", "--note", "20% + annual prepay")
        self.assertEqual(code, 0, out)
        self.assertIn("https://app.hubspot.com/contacts/4242/record/0-3/", out)
        acme = self.fake.by_desk_id("D-1001")
        self.assertEqual((acme["dd_status"], acme["dd_discount_pct"], acme["dd_requested_pct"]),
                         ("approved", "20", "25"))
        self.assertEqual((acme["amount"], acme["dealstage"], acme["dd_approved_by"]),
                         ("288000", "contractsent", "user"))
        self.assertIn("Decided by: user", self.fake.notes[-1]["properties"]["hs_note_body"])
        self.assertEqual(self.fake.notes[-1]["associations"][0]["types"][0]["associationTypeId"], 214)
        self.assertTrue((self.tmp / "quotes" / "D-1001.md").exists())

    def test_guards_hold_in_crm_mode(self):
        code, out = self.cli("approve", "D-1003", "40", "--by", "user", "--decision", "approved")
        self.assertEqual(code, 2)
        self.assertEqual(self.fake.by_desk_id("D-1003")["dd_status"], "open")
        self.assertEqual(self.fake.notes, [])

    def test_crm_error_is_reported_not_raised(self):
        def down(*a, **k):
            raise crm_hubspot.CRMError("HubSpot unreachable: timed out")
        crm_hubspot._http = down
        code, out = self.cli("pending")
        self.assertEqual(code, 3)
        self.assertIn("CRM ERROR", out)


if __name__ == "__main__":
    unittest.main()
