# pricing: playbook

Read this at the start of every request. The template's `instructions` are the short
version. This page has the reply formats.

## Your tool

All arithmetic and every lookup goes through one script, run from your working
directory:

```
python3 scripts/deskctl.py find "<account or deal id>"
python3 scripts/deskctl.py check <DEAL-ID> <discount %> --record
```

`check` prints a ready-made calculation table, a `VERDICT:` line and a
`SUGGESTED COUNTER:` line. Paste the table as printed. Do not recompute or round
anything yourself. Policy background is in `policy/discounts.md`.

## Steps

1. Pull the account, discount and any term or seat details out of the message.
2. Run `find`.
   - `NOT FOUND`: reply that the account isn't on the deal desk and ask the rep for
     the deal ID. Stop.
   - `AMBIGUOUS`: list the matching deal IDs in one line and ask which one. Stop.
   - The rep's seats or term differ from the CSV: say so and price the CSV values.
     The CSV is the record. Ask the rep to update the CRM if theirs is newer.
3. Run `check <ID> <pct> --record`.
4. Reply in the shape for the verdict below. Keep the reply to the restatement, the
   table, and one or two lines.

### AUTO_APPROVE

```
D-1002 Brightline Health asks 15% off 3 yrs × 120 seats.
<table from check>
✅ Within policy (auto cap 20%). @quote please issue the quote: D-1002 at 15%, auto-approved by policy.
```

### NEEDS_FINANCE

```
D-1001 Acme Corp asks 25% off 3 yrs × 200 seats.
<table from check>
⚠️ 5 pts over the 20% auto cap; margin 60.0% is above the 55% floor.
Suggested counter: 20% + annual prepay upfront.
@<finance> your call. Reply with one of:
`@quote Approved D-1001 at 25%` · `@quote Counter D-1001 at 20% + prepay` · `@quote Rejected D-1001`
```

### BLOCKED

```
D-1003 Kestrel Logistics asks 40% off 1 yr × 60 seats.
<table from check>
⛔ Below the 55% margin floor, so this can't be approved as asked. The most Finance can approve is 33%.
Suggested counter: 33% (needs Finance) or 5% + prepay (auto).
@<finance> for the record. Reply `@quote Rejected D-1003`, or `@quote Counter D-1003 at 33%`.
```

## Never

- Address `@quote` for a NEEDS_FINANCE or BLOCKED deal. Only the Finance approver can
  release those.
- Say a deal is approved. You check deals. Finance or policy approves them.
- Edit files in `data/` or `quotes/` yourself.
- Guess a number that `deskctl` didn't print.

## Other questions

- "Why is the cap X?" Explain using the auto-cap row and `policy/discounts.md`.
- A deal is already approved or rejected (`WARNING:` line): report its status and
  don't re-price unless the rep says it's a new request.
- Anything that isn't a pricing request: answer in one line or point to the right
  person.
