#!/usr/bin/env python3
"""deskctl: the deal desk's single source of arithmetic and record-keeping.

The Switch agents in the #deal-desk room call this instead of doing maths in
their heads, so every number posted in chat is reproducible and every write to
data/ goes through one guarded path. Standard library only.

    python3 scripts/deskctl.py find "acme"
    python3 scripts/deskctl.py check D-1001 25 [--record]
    python3 scripts/deskctl.py approve D-1001 25 --by <name> --decision approved|countered|auto
    python3 scripts/deskctl.py reject D-1001 --by <name> --reason "..."
    python3 scripts/deskctl.py pending

Policy lives in policy/discounts.md; the constants below must match it.
Set DESK_ROOT to point at another copy of the data (the tests do).
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- policy (keep in step with policy/discounts.md) -------------------------
COST_RATIO = 0.30          # cost to serve, as a share of list TCV
MARGIN_FLOOR = 0.55        # minimum gross margin after discount
TERM_BASE = {1: 5, 2: 10, 3: 15}          # 3 means "3 or more years"
SEAT_BONUS = [(500, 10), (100, 5), (0, 0)]  # (min seats, bonus pts), high first
SEGMENT_CAP = {"SMB": 10, "Mid-Market": 20, "Enterprise": 25}

AUTO, FINANCE, BLOCKED = "AUTO_APPROVE", "NEEDS_FINANCE", "BLOCKED"
DECIDED_STATUSES = {"approved", "rejected"}
CLOSED_STAGES = {"Closed Won", "Closed Lost"}
IST = timezone(timedelta(hours=5, minutes=30))

DEAL_FIELDS = ["deal_id", "account", "owner", "segment", "plan", "seats", "term_years",
               "list_price", "stage", "status", "requested_pct", "discount_pct", "updated_at"]
LOG_FIELDS = ["timestamp", "deal_id", "account", "requested_pct", "final_pct", "decision",
              "decided_by", "net_tcv", "margin_pct", "quote_file", "note"]


class DeskError(Exception):
    """A refusal the agent should relay to the room verbatim."""


# --- pure policy ------------------------------------------------------------
def max_discount_at_floor() -> int:
    """Deepest whole-percent discount that keeps margin >= floor (33)."""
    exact = 1 - COST_RATIO / (1 - MARGIN_FLOOR)
    return math.floor(exact * 100 + 1e-9)


def auto_cap(segment: str, seats: int, term_years: int) -> tuple[int, int, int, int]:
    """Return (cap, term_base, seat_bonus, segment_cap)."""
    if segment not in SEGMENT_CAP:
        raise DeskError(f"Unknown segment {segment!r}; policy covers {', '.join(SEGMENT_CAP)}.")
    base = TERM_BASE[min(max(term_years, 1), 3)]
    bonus = next(b for floor, b in SEAT_BONUS if seats >= floor)
    seg = SEGMENT_CAP[segment]
    return min(base + bonus, seg), base, bonus, seg


@dataclass
class Evaluation:
    deal: dict
    discount: float
    list_tcv: float
    discount_amt: float
    net_tcv: float
    net_annual: float
    cost: float
    margin: float            # 0..1
    cap: int
    term_base: int
    seat_bonus: int
    segment_cap: int
    floor_max: int
    verdict: str
    counter: str
    warnings: list


def evaluate(deal: dict, discount: float) -> Evaluation:
    if not 0 <= discount < 100:
        raise DeskError(f"Discount must be between 0 and 99%, got {discount:g}%.")
    seats, years, price = int(deal["seats"]), int(deal["term_years"]), float(deal["list_price"])
    list_tcv = seats * price * years
    net = list_tcv * (1 - discount / 100)
    cost = list_tcv * COST_RATIO
    margin = (net - cost) / net if net else -1.0
    cap, base, bonus, seg = auto_cap(deal["segment"], seats, years)
    floor_max = max_discount_at_floor()

    if margin < MARGIN_FLOOR - 1e-9:
        verdict = BLOCKED
        counter = (f"{floor_max}% (deepest discount at the {MARGIN_FLOOR:.0%} margin floor; needs Finance), "
                   f"or {cap}% + annual prepay upfront (auto-approvable)")
    elif discount <= cap + 1e-9:
        verdict, counter = AUTO, "none needed"
    else:
        verdict = FINANCE
        counter = f"{cap}% + annual prepay upfront (auto-approvable)"

    warnings = []
    if deal["status"] in DECIDED_STATUSES or deal["stage"] in CLOSED_STAGES:
        warnings.append(f"{deal['deal_id']} is already {deal['status']} ({deal['stage']}); "
                        "not re-pricing without the rep confirming a new request.")
    if deal["status"] == "pending_approval":
        warnings.append(f"{deal['deal_id']} already has a request pending: "
                        f"{deal['requested_pct']}%.")
    return Evaluation(deal, discount, list_tcv, list_tcv - net, net, net / years, cost, margin,
                      cap, base, bonus, seg, floor_max, verdict, counter, warnings)


# --- formatting -------------------------------------------------------------
def usd(x: float) -> str:
    return f"${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:g}%"


def render_check(ev: Evaluation) -> str:
    d = ev.deal
    seats, years, price = int(d["seats"]), int(d["term_years"]), float(d["list_price"])
    over = ev.discount - ev.cap
    if ev.verdict == AUTO:
        why = f"{pct(ev.discount)} is within the {ev.cap}% auto cap"
    elif ev.verdict == FINANCE:
        why = (f"{pct(ev.discount)} is {over:g} pts over the {ev.cap}% auto cap; "
               f"margin {ev.margin:.1%} is above the {MARGIN_FLOOR:.0%} floor")
    else:
        why = (f"margin {ev.margin:.1%} is below the {MARGIN_FLOOR:.0%} floor "
               f"(max {ev.floor_max}% discount)")
    lines = [
        f"**{d['deal_id']} · {d['account']}** · {d['segment']} · {d['plan']} plan · "
        f"{seats} seats × {years} yr · owner {d['owner']}",
        "",
        "| | Calculation |",
        "|---|---|",
        f"| List TCV | {seats} × {usd(price)} × {years} = {usd(ev.list_tcv)} |",
        f"| Discount {pct(ev.discount)} | −{usd(ev.discount_amt)} |",
        f"| Net TCV | {usd(ev.net_tcv)} ({usd(ev.net_annual)}/yr) |",
        f"| Cost to serve (30% of list) | {usd(ev.cost)} |",
        f"| Gross margin | ({usd(ev.net_tcv)} − {usd(ev.cost)}) ÷ {usd(ev.net_tcv)} = {ev.margin:.1%} |",
        f"| Auto cap | min({ev.term_base}% term + {ev.seat_bonus} pts seats, "
        f"{d['segment']} cap {ev.segment_cap}%) = {ev.cap}% |",
        f"| Margin floor | {MARGIN_FLOOR:.0%} → max discount {ev.floor_max}% |",
        "",
        f"VERDICT: {ev.verdict} ({why})",
        f"SUGGESTED COUNTER: {ev.counter}",
    ]
    lines += [f"WARNING: {w}" for w in ev.warnings]
    return "\n".join(lines)


# --- storage ----------------------------------------------------------------
def root() -> Path:
    return Path(os.environ.get("DESK_ROOT", Path(__file__).resolve().parent.parent))


def now() -> str:
    return os.environ.get("DESK_NOW") or datetime.now(IST).isoformat(timespec="seconds")


def _load_env() -> None:
    """Read KEY=VALUE lines from .env at the repo root; real env vars win."""
    env = root() / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def crm():
    """The HubSpot backend when DESK_BACKEND=hubspot, else None (CSV)."""
    if os.environ.get("DESK_BACKEND", "csv").lower() != "hubspot":
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import crm_hubspot
    return crm_hubspot


def load_deals() -> list[dict]:
    if crm():
        return crm().load_deals()
    with open(root() / "data" / "deals.csv", newline="") as f:
        return list(csv.DictReader(f))


def save_deals(deals: list[dict]) -> None:
    if crm():
        return crm().save_deals(deals)
    path = root() / "data" / "deals.csv"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DEAL_FIELDS)
        w.writeheader()
        w.writerows(deals)
    tmp.replace(path)


def append_log(row: dict) -> None:
    with open(root() / "data" / "approvals_log.csv", "a", newline="") as f:
        csv.DictWriter(f, fieldnames=LOG_FIELDS).writerow(row)


def get_deal(deals: list[dict], deal_id: str) -> dict:
    for d in deals:
        if d["deal_id"].lower() == deal_id.strip().lower():
            return d
    raise DeskError(f"No deal {deal_id!r} in data/deals.csv. Ask the rep for the deal ID; "
                    "do not invent one.")


def find(deals: list[dict], text: str) -> list[dict]:
    t = text.strip().lower()
    return [d for d in deals if t in d["account"].lower() or t == d["deal_id"].lower()]


# --- writes -----------------------------------------------------------------
QUOTE_TEMPLATE = """# Order form {quote_no}

| | |
|---|---|
| Customer | **{account}** |
| Deal | {deal_id} ({segment}) |
| Account owner | {owner} |
| Plan | {plan} |
| Seats | {seats} |
| Term | {years} year(s), billed annually |
| Issued | {issued} |
| Valid until | 30 days from issue |

## Pricing

| Line | Amount |
|---|---|
| List price | {price} per seat / year |
| List TCV | {seats} × {price} × {years} = {list_tcv} |
| Discount | {discount}% (−{discount_amt}) |
| **Net TCV** | **{net_tcv}** |
| Annual invoice | {net_annual} |

## Approval

| | |
|---|---|
| Decision | {decision} |
| Approved by | {decided_by} |
| Requested discount | {requested} |
| Gross margin at this price | {margin} (floor {floor}) |
| Audit | `data/approvals_log.csv`, entry at {issued} |

## Terms

1. Subscription starts on signature; seats may be added at the same per-seat rate
   for the remainder of the term.
2. Price is fixed for the full term. Renewal is at the list price then current,
   unless a new quote is approved.
3. Payment: net 30 from invoice.{prepay}

---

Customer signature: ______________________  Date: __________

Vendor signature: ______________________  Date: __________
"""


def approve(deal_id: str, discount: float, by: str, decision: str, note: str = "") -> str:
    if decision not in {"approved", "countered", "auto"}:
        raise DeskError("decision must be approved, countered or auto.")
    if not by.strip():
        raise DeskError("--by is required: who approved this, as they appear in the room.")
    deals = load_deals()
    deal = get_deal(deals, deal_id)
    ev = evaluate(deal, discount)
    if deal["status"] in DECIDED_STATUSES:
        raise DeskError(f"{deal['deal_id']} is already {deal['status']}; no new quote.")
    if ev.verdict == BLOCKED:
        raise DeskError(f"REFUSED: {pct(discount)} puts margin at {ev.margin:.1%}, below the "
                        f"{MARGIN_FLOOR:.0%} floor. No approval can override it. The most "
                        f"Finance can approve is {ev.floor_max}%.")
    if decision == "auto" and ev.verdict != AUTO:
        raise DeskError(f"REFUSED: {pct(discount)} is over the {ev.cap}% auto cap, so it needs "
                        "a human approval from Finance in the room.")

    issued = now()
    quote_rel = f"quotes/{deal['deal_id']}.md"
    requested = deal["requested_pct"] or f"{discount:g}"
    label = {"auto": "Auto-approved by policy (within auto cap)",
             "approved": "Approved by Finance",
             "countered": "Approved by Finance at a counter-offer"}[decision]
    text = QUOTE_TEMPLATE.format(
        quote_no=f"Q-{deal['deal_id']}", account=deal["account"], deal_id=deal["deal_id"],
        segment=deal["segment"], owner=deal["owner"], plan=deal["plan"], seats=deal["seats"],
        years=deal["term_years"], issued=issued, price=usd(float(deal["list_price"])),
        list_tcv=usd(ev.list_tcv), discount=f"{discount:g}", discount_amt=usd(ev.discount_amt),
        net_tcv=usd(ev.net_tcv), net_annual=usd(ev.net_annual), decision=label,
        decided_by=by, requested=f"{requested}%", margin=f"{ev.margin:.1%}",
        floor=f"{MARGIN_FLOOR:.0%}",
        prepay=("\n4. Annual fees are prepaid upfront for the full term." if "prepay" in note.lower() else ""))
    (root() / "quotes").mkdir(exist_ok=True)
    (root() / quote_rel).write_text(text)

    deal.update(status="approved", discount_pct=f"{discount:g}", requested_pct=requested,
                updated_at=issued[:10])
    save_deals(deals)
    row = {"timestamp": issued, "deal_id": deal["deal_id"], "account": deal["account"],
           "requested_pct": requested, "final_pct": f"{discount:g}",
           "decision": "auto_approved" if decision == "auto" else decision,
           "decided_by": "policy" if decision == "auto" else by,
           "net_tcv": f"{ev.net_tcv:.0f}", "margin_pct": f"{ev.margin * 100:.1f}",
           "quote_file": quote_rel, "note": note}
    append_log(row)
    out = (f"QUOTE WRITTEN: {quote_rel}\n"
           f"{deal['deal_id']} {deal['account']}: {discount:g}% off → net {usd(ev.net_tcv)} "
           f"({usd(ev.net_annual)}/yr), margin {ev.margin:.1%}. Status approved; logged.")
    return out + _crm_stamp(deal, row, out)


def reject(deal_id: str, by: str, reason: str) -> str:
    if not by.strip():
        raise DeskError("--by is required.")
    deals = load_deals()
    deal = get_deal(deals, deal_id)
    if deal["status"] in DECIDED_STATUSES:
        raise DeskError(f"{deal['deal_id']} is already {deal['status']}.")
    ts = now()
    deal.update(status="rejected", updated_at=ts[:10])
    save_deals(deals)
    row = {"timestamp": ts, "deal_id": deal["deal_id"], "account": deal["account"],
           "requested_pct": deal["requested_pct"], "final_pct": "0", "decision": "rejected",
           "decided_by": by, "net_tcv": "", "margin_pct": "", "quote_file": "", "note": reason}
    append_log(row)
    out = f"REJECTED: {deal['deal_id']} {deal['account']}. Status rejected; logged. No quote."
    return out + _crm_stamp(deal, row, f"{out}\nReason: {reason}")


def _crm_stamp(deal: dict, row: dict, summary: str) -> str:
    """In HubSpot mode, stamp the decision on the deal and return a line with its link."""
    if not crm():
        return ""
    url = crm().record_decision(deal, row, f"{summary}\nDecided by: {row['decided_by']}")
    return f"\nCRM: HubSpot deal updated: {url}"


def record_request(deal_id: str, discount: float, verdict: str) -> None:
    deals = load_deals()
    deal = get_deal(deals, deal_id)
    deal.update(requested_pct=f"{discount:g}", updated_at=now()[:10])
    if deal["status"] == "open" and verdict != AUTO:
        deal["status"] = "pending_approval"
    save_deals(deals)


def pending() -> str:
    rows = [d for d in load_deals() if d["status"] == "pending_approval"]
    if not rows:
        return "Nothing is pending approval."
    out = ["| Deal | Account | Owner | Request | Auto cap | Margin | Since |", "|---|---|---|---|---|---|---|"]
    for d in rows:
        ev = evaluate(d, float(d["requested_pct"] or 0))
        out.append(f"| {d['deal_id']} | {d['account']} | {d['owner']} | {d['requested_pct']}% | "
                   f"{ev.cap}% | {ev.margin:.1%} | {d['updated_at']} |")
    return "\n".join(out)


# --- CLI --------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deskctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("find", help="look up deals by account name or deal ID")
    s.add_argument("text")
    s = sub.add_parser("check", help="price a discount request against policy")
    s.add_argument("deal_id"); s.add_argument("discount", type=float)
    s.add_argument("--record", action="store_true",
                   help="store the request; marks NEEDS_FINANCE/BLOCKED deals pending_approval")
    s = sub.add_parser("approve", help="write the quote, update the deal, log the approval")
    s.add_argument("deal_id"); s.add_argument("discount", type=float)
    s.add_argument("--by", required=True)
    s.add_argument("--decision", required=True, choices=["approved", "countered", "auto"])
    s.add_argument("--note", default="")
    s = sub.add_parser("reject", help="mark a deal rejected and log it")
    s.add_argument("deal_id"); s.add_argument("--by", required=True)
    s.add_argument("--reason", required=True)
    sub.add_parser("pending", help="list deals waiting for Finance")
    a = p.parse_args(argv)
    _load_env()

    try:
        if a.cmd == "find":
            hits = find(load_deals(), a.text)
            if not hits:
                print(f"NOT FOUND: no deal matches {a.text!r}. Ask the rep for the account or deal ID.")
            for d in hits:
                print(f"{d['deal_id']} | {d['account']} | {d['segment']} | {d['plan']} | "
                      f"{d['seats']} seats | {d['term_years']} yr | {usd(float(d['list_price']))}/seat/yr | "
                      f"{d['stage']} | {d['status']} | owner {d['owner']}")
            if len(hits) > 1:
                print("AMBIGUOUS: more than one deal matches; ask the rep which one.")
        elif a.cmd == "check":
            deals = load_deals()
            ev = evaluate(get_deal(deals, a.deal_id), a.discount)
            print(render_check(ev))
            if a.record and not ev.warnings:
                record_request(a.deal_id, a.discount, ev.verdict)
                if ev.verdict != AUTO:
                    print(f"RECORDED: {ev.deal['deal_id']} is now pending_approval at {a.discount:g}%.")
        elif a.cmd == "approve":
            print(approve(a.deal_id, a.discount, a.by, a.decision, a.note))
        elif a.cmd == "reject":
            print(reject(a.deal_id, a.by, a.reason))
        elif a.cmd == "pending":
            print(pending())
    except DeskError as e:
        print(str(e))
        return 2
    except Exception as e:  # CRM errors: report, never a traceback in chat
        if type(e).__name__ != "CRMError":
            raise
        print(f"CRM ERROR: {e}. Nothing was written to HubSpot for this step; tell Finance.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
