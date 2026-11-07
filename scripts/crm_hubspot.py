#!/usr/bin/env python3
"""HubSpot backend for the deal desk. Standard library only.

With DESK_BACKEND=hubspot (in .env), deskctl reads and writes deals in HubSpot
instead of data/deals.csv:

- the deal record lives on a HubSpot deal, in custom properties grouped under
  "Deal desk" (dd_deal_id, dd_seats, dd_term_years, ...);
- an approval sets the deal's amount to the net TCV, moves it to the
  "contract sent" stage, and stamps who approved it;
- every decision adds a note to the deal's timeline with the calculation.

The local data/approvals_log.csv is still written, as the desk's own audit log.

    python3 scripts/crm_hubspot.py setup   # create the property group + properties
    python3 scripts/crm_hubspot.py seed    # upsert the 15 demo deals from data/seed/
    python3 scripts/crm_hubspot.py status  # account, deal count, links

Auth: HUBSPOT_TOKEN, a HubSpot service key (Development > Keys > Service keys)
with crm.objects.deals.read/write and crm.schemas.deals.read/write.
"""

from __future__ import annotations

import csv
import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = os.environ.get("HUBSPOT_API", "https://api.hubapi.com")
GROUP = "deal_desk"

# deskctl field -> HubSpot deal property
FIELD_TO_PROP = {
    "deal_id": "dd_deal_id",
    "account": "dealname",
    "owner": "dd_owner_name",
    "segment": "dd_segment",
    "plan": "dd_plan",
    "seats": "dd_seats",
    "term_years": "dd_term_years",
    "list_price": "dd_list_price",
    "stage": "dd_stage",
    "status": "dd_status",
    "requested_pct": "dd_requested_pct",
    "discount_pct": "dd_discount_pct",
    "updated_at": "dd_updated_at",
}
NUMBER_PROPS = {"dd_seats", "dd_term_years", "dd_list_price", "dd_requested_pct", "dd_discount_pct"}
EXTRA_PROPS = {  # written on decisions only
    "dd_approved_by": ("Approved by", "string", "text"),
    "dd_quote_file": ("Quote file", "string", "text"),
    "dd_last_decision": ("Last deal-desk decision", "string", "textarea"),
}
LABELS = {
    "dd_deal_id": "Deal desk ID", "dd_owner_name": "Account owner (desk)",
    "dd_segment": "Segment", "dd_plan": "Plan", "dd_seats": "Seats",
    "dd_term_years": "Term (years)", "dd_list_price": "List price / seat / year",
    "dd_stage": "Desk stage", "dd_status": "Desk status",
    "dd_requested_pct": "Requested discount %", "dd_discount_pct": "Approved discount %",
    "dd_updated_at": "Desk updated",
}
# Desk stage -> HubSpot default-pipeline stage id (checked against the account)
STAGE_MAP = {"Discovery": "appointmentscheduled", "Proposal": "presentationscheduled",
             "Negotiation": "decisionmakerboughtin", "Closed Won": "closedwon",
             "Closed Lost": "closedlost"}
QUOTE_STAGE = "contractsent"


class CRMError(Exception):
    pass


# --- HTTP -------------------------------------------------------------------
def _token() -> str:
    tok = os.environ.get("HUBSPOT_TOKEN", "").strip()
    if not tok:
        raise CRMError("HUBSPOT_TOKEN is not set. Put it in .env (see .env.example).")
    return tok


def _http(method: str, path: str, body: dict | None = None) -> dict:
    """One HubSpot API call. Tests replace this function."""
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise CRMError(f"HubSpot {method} {path} -> {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise CRMError(f"HubSpot unreachable: {e.reason}") from None


# --- schema -----------------------------------------------------------------
def setup() -> list[str]:
    done = []
    try:
        _http("POST", "/crm/v3/properties/deals/groups",
              {"name": GROUP, "label": "Deal desk", "displayOrder": -1})
        done.append("created group Deal desk")
    except CRMError as e:
        if "409" not in str(e):
            raise
    specs = {p: (LABELS[p], "number" if p in NUMBER_PROPS else "string",
                 "number" if p in NUMBER_PROPS else "text")
             for p in FIELD_TO_PROP.values() if p.startswith("dd_")}
    specs.update(EXTRA_PROPS)
    for name, (label, typ, field_type) in specs.items():
        body = {"name": name, "label": label, "type": typ, "fieldType": field_type,
                "groupName": GROUP}
        if name == "dd_deal_id":
            body["hasUniqueValue"] = True
        try:
            _http("POST", "/crm/v3/properties/deals", body)
            done.append(f"created property {name}")
        except CRMError as e:
            if "409" not in str(e):
                raise
    return done


def _stage_ids() -> set[str]:
    try:
        res = _http("GET", "/crm/v3/pipelines/deals")
    except CRMError:
        return set()
    for p in res.get("results", []):
        if p.get("id") == "default":
            return {s["id"] for s in p.get("stages", [])}
    return set()


# --- deals ------------------------------------------------------------------
def _to_props(deal: dict) -> dict:
    props = {}
    for field, prop in FIELD_TO_PROP.items():
        v = deal.get(field, "")
        props[prop] = "" if v is None else str(v)
    return props


def _from_record(rec: dict) -> dict:
    p = rec.get("properties", {})
    deal = {}
    for field, prop in FIELD_TO_PROP.items():
        v = p.get(prop) or ""
        if prop in NUMBER_PROPS and v:
            f = float(v)
            v = f"{f:g}"
        deal[field] = v
    deal["_hs_id"] = rec["id"]
    return deal


_SNAPSHOT: dict[str, dict] = {}


def load_deals() -> list[dict]:
    props = ",".join(list(FIELD_TO_PROP.values()) + list(EXTRA_PROPS))
    deals, after = [], None
    while True:
        q = f"/crm/v3/objects/deals?limit=100&archived=false&properties={props}"
        if after:
            q += f"&after={after}"
        res = _http("GET", q)
        for rec in res.get("results", []):
            if (rec.get("properties") or {}).get("dd_deal_id"):
                deals.append(_from_record(rec))
        after = (res.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    deals.sort(key=lambda d: d["deal_id"])
    _SNAPSHOT.clear()
    _SNAPSHOT.update({d["deal_id"]: dict(d) for d in deals})
    return deals


def save_deals(deals: list[dict]) -> None:
    """PATCH only the deals deskctl changed since load_deals()."""
    for d in deals:
        before = _SNAPSHOT.get(d["deal_id"])
        changed = {FIELD_TO_PROP[f]: str(d[f]) for f in FIELD_TO_PROP
                   if before is None or str(before.get(f, "")) != str(d.get(f, ""))}
        if changed:
            _http("PATCH", f"/crm/v3/objects/deals/{d['_hs_id']}", {"properties": changed})
            _SNAPSHOT[d["deal_id"]] = dict(d)


def deal_url(hs_id: str) -> str:
    try:
        info = _http("GET", "/account-info/v3/details")
        portal, domain = info.get("portalId"), info.get("uiDomain") or "app.hubspot.com"
    except CRMError:
        portal, domain = os.environ.get("HUBSPOT_PORTAL_ID"), "app.hubspot.com"
    if not portal:
        return f"HubSpot deal {hs_id}"
    return f"https://{domain}/contacts/{portal}/record/0-3/{hs_id}"


def record_decision(deal: dict, row: dict, summary: str) -> str:
    """Stamp the decision on the deal and add a timeline note. Returns the deal URL."""
    props = {"dd_approved_by": row["decided_by"], "dd_quote_file": row["quote_file"],
             "dd_last_decision": summary}
    if row["decision"] != "rejected":
        props["amount"] = row["net_tcv"]
        if QUOTE_STAGE in _stage_ids():
            props["dealstage"] = QUOTE_STAGE
    _http("PATCH", f"/crm/v3/objects/deals/{deal['_hs_id']}", {"properties": props})
    body = "<br>".join(html.escape(line) for line in summary.splitlines())
    try:
        _http("POST", "/crm/v3/objects/notes", {
            "properties": {"hs_timestamp": datetime.now(timezone.utc).isoformat(),
                           "hs_note_body": f"<b>Deal desk</b><br>{body}"},
            "associations": [{"to": {"id": deal["_hs_id"]},
                              "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                         "associationTypeId": 214}]}]})
    except CRMError:
        pass  # the stamped properties already carry the decision
    return deal_url(deal["_hs_id"])


def seed(seed_csv: Path) -> str:
    with open(seed_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    existing = {d["deal_id"]: d["_hs_id"] for d in load_deals()}
    stages = _stage_ids()
    created = updated = 0
    for r in rows:
        props = _to_props(r)
        props.update({"dd_approved_by": "", "dd_quote_file": "", "dd_last_decision": ""})
        list_tcv = int(r["seats"]) * float(r["list_price"]) * int(r["term_years"])
        props["amount"] = f"{list_tcv:.0f}"
        stage = STAGE_MAP.get(r["stage"])
        if stage in stages:
            props["pipeline"], props["dealstage"] = "default", stage
        if r["deal_id"] in existing:
            _http("PATCH", f"/crm/v3/objects/deals/{existing[r['deal_id']]}", {"properties": props})
            updated += 1
        else:
            _http("POST", "/crm/v3/objects/deals", {"properties": props})
            created += 1
    return f"HubSpot seeded: {created} created, {updated} reset."


def _load_env() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: list[str]) -> int:
    _load_env()
    cmd = argv[0] if argv else "status"
    root = Path(__file__).resolve().parent.parent
    try:
        if cmd == "setup":
            done = setup()
            print("\n".join(done) or "Deal desk properties already exist.")
        elif cmd == "seed":
            print(seed(root / "data" / "seed" / "deals.csv"))
        elif cmd == "status":
            deals = load_deals()
            print(f"{len(deals)} deal-desk deals in HubSpot.")
            if deals:
                print("Example:", deals[0]["deal_id"], deals[0]["account"], deal_url(deals[0]["_hs_id"]))
        else:
            print(__doc__)
            return 1
    except CRMError as e:
        print(f"ERROR: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
