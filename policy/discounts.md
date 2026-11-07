# Discount policy (FY27)

The `pricing` agent checks every discount request against this page. The rules are
coded in `scripts/deskctl.py`, and `tests/test_policy.py` holds that code to the
examples at the bottom. When you change a number here, change it there too.

## Definitions

| Term | Meaning |
|---|---|
| List price | Per seat, per year, from the `list_price` column of `data/deals.csv` |
| List TCV | seats × list price × term years |
| Net TCV | List TCV × (1 − discount) |
| Cost to serve | **30% of list TCV** (hosting, support, success). It does not change with the discount. |
| Gross margin | (Net TCV − cost to serve) ÷ Net TCV |

## 1. Auto-approve cap

The `pricing` agent may approve a discount on its own up to this cap:

**auto cap = min(term base + seat bonus, segment cap)**

| Term length | Term base |
|---|---|
| 1 year | 5% |
| 2 years | 10% |
| 3+ years | 15% |

| Seats | Seat bonus |
|---|---|
| < 100 | +0 pts |
| 100–499 | +5 pts |
| 500+ | +10 pts |

| Segment | Segment cap |
|---|---|
| SMB | 10% |
| Mid-Market | 20% |
| Enterprise | 25% |

## 2. Margin floor

**Gross margin must stay at or above 55%.** With a 30% cost to serve, the deepest
discount allowed is 1 − 0.30 ÷ 0.45 = **33.3%**. Quotes use whole percentages, so in
practice the limit is **33%**.

## 3. Who decides

| Requested discount | Verdict | Who approves |
|---|---|---|
| ≤ auto cap | `AUTO_APPROVE` | Policy. The `pricing` agent hands the deal to the `quote` agent. |
| > auto cap, margin ≥ 55% | `NEEDS_FINANCE` | The Finance approver (deal-desk lead), in the room |
| margin < 55% | `BLOCKED` | Nobody. Below-floor discounts need a counter-offer. `quote` refuses them, even with an "Approved". |

## 4. Counter-offers

- **NEEDS_FINANCE:** suggest the auto cap plus annual prepay upfront. The rep keeps a
  discount that needs no exception, and Finance gets the cash up front.
- **BLOCKED:** suggest the deepest discount the margin floor allows (33%) for Finance
  to decide on, or the auto cap with prepay.

## 5. Guardrails

- Every deal must exist in `data/deals.csv`. If an account is missing or matches more
  than one deal, ask the rep. Never invent seats, terms or prices.
- Deals already `approved` or `rejected`, or in `Closed Won` / `Closed Lost`, are
  reported back and not re-priced.
- Every decision, whether automatic, human or rejected, is appended to
  `data/approvals_log.csv`.

## Worked examples (the demo seed data)

| Deal | Request | Auto cap | Margin | Verdict |
|---|---|---|---|---|
| D-1002 Brightline Health, Mid-Market, 120 seats, 3 yrs | 15% | 15 + 5 = 20% | 64.7% | AUTO_APPROVE |
| D-1001 Acme Corp, Mid-Market, 200 seats, 3 yrs | 25% | 15 + 5 = 20% | 60.0% | NEEDS_FINANCE (counter: 20% + prepay) |
| D-1003 Kestrel Logistics, SMB, 60 seats, 1 yr | 40% | min(5, 10) = 5% | 50.0% | BLOCKED (counter: 33%) |
