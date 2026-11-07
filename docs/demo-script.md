# Demo script (about 3 minutes)

Two browser windows, side by side:
- **Finance**: your normal window, signed in to Mattermost as the account Switch
  linked to you (`user` on the bundled Mattermost). Keep a second tab open on the Acme
  deal in HubSpot.
- **Rep**: a private window, signed in as `rep.priya`.

Plus one terminal in the repo folder. Wait for each agent's reply before sending the
next message. Agents can take 10–40 seconds, so cut the waits in editing.

## Before recording

```bash
./scripts/reset_demo.sh
```

Open `#deal-desk` in both windows. The kickoff and the three hellos should be
visible. If an earlier take left threads behind, start a new room or scroll so the
screen is clean.

---

## Scene 0: the problem (narration, about 15 s)

> "Discount approvals live in DMs. Finance re-does the maths, and nobody can say
> later who approved what. This is the same flow in one Switch room: three named
> agents, a rep, and Finance."

Point at the channel's member list: `pricing`, `quote` and `pipeline` are bot members
next to the people.

## Scene 1: in policy, no human needed (Rep)

```
@pricing Brightline Health wants 15% off their 3-year, 120-seat deal.
```

**Expect:** pricing restates the request, posts the table (net $183,600, margin
64.7%, auto cap 20%) and says `AUTO_APPROVE`. It then addresses `@quote`, which
replies `📄 Quote issued: quotes/D-1002.md`, auto-approved by policy.

> "Inside the policy, the agents handle it on their own: pricing hands off to quote
> by name."

## Scene 2: out of policy, escalate to Finance (Rep)

```
@pricing Acme wants 25% off a 3-year, 200-seat deal.
```

**Expect:** the table (list $360,000 → net $270,000, margin 60.0%) and
`⚠️ 5 pts over the 20% auto cap`, a suggested counter of
`20% + annual prepay upfront`, then `@<finance>` with three reply options.

## Scene 3: the rep can't approve their own deal (Rep)

```
@quote Approved D-1001 at 25%
```

**Expect:** **no reply from quote.** Switch may post a notice that you can't address
it. Wait about 10 seconds on camera either way.

> "quote only accepts messages from Finance and Finance's own agents. That rule is
> Switch's `owner-agents` addressing, so it never reaches the model. The human
> approval isn't just a prompt instruction."

## Scene 4: Finance counters (Finance)

```
@quote Counter D-1001 at 20% + prepay
```

**Expect:** `📄 Quote issued: quotes/D-1001.md` with D-1001 Acme Corp at 20% off,
countered from 25%, net $288,000 ($96,000/yr), margin 62.5%, the line
"approved by <you>", and a **HubSpot link**.

Switch to the HubSpot tab and refresh the Acme deal. It should show **Amount
$288,000**, stage **Contract sent**, **Approved by** filled in, and a **Deal desk note**
on the timeline with the calculation.

> "The approval didn't stay in chat. The CRM now shows the approved price, the
> stage, who approved it, and why."

## Scene 5: below the margin floor (Rep, then Finance)

Rep:
```
@pricing Kestrel Logistics needs 40% off the 1-year, 60-seat deal or they walk.
```

**Expect:** margin 50.0%, so `⛔ Below the 55% margin floor`, with a counter of 33%
(needs Finance) or 5% + prepay.

Finance, to show that even Finance can't go below the floor:
```
@quote Approved D-1003 at 40%
```

**Expect:** `REFUSED: 40% puts margin at 50.0%, below the 55% floor ... The most
Finance can approve is 33%.`

Finance:
```
@quote Rejected D-1003, below margin floor; rep to offer 33% with prepay
```

**Expect:** `❌ D-1003 rejected ... Logged. No quote issued.`

## Scene 6: no made-up data (Rep, optional, about 10 s)

```
@pricing Wayne Industries wants 10% off.
```

**Expect:** pricing says the account isn't on the deal desk and asks for the deal ID.

## Scene 7: what's waiting? (Rep)

```
@pipeline what's pending approval?
```

**Expect:** a table with **D-1008 Orbital Freight** (28%, from the seed data), then
`@<finance> 1 deal(s) waiting on you`.

## Scene 8: the audit trail (terminal, about 20 s)

```bash
cat quotes/D-1001.md
column -s, -t data/approvals_log.csv
git diff --stat data/
```

> "Every decision is written down: the order form, the deal record and the audit log,
> with who approved it. All of it came from one Mattermost thread."

## Close (about 10 s)

(In HubSpot mode, skip `git diff`. The HubSpot deal from scene 4 is the audit trail.)


> "One template creates the agents, the room and the rules. Switch is the access
> control that makes the human approval real."

---

### If something goes wrong

| Symptom | Fix |
|---|---|
| No agent replies at all | Switch Console must stay open. Check the agents are running under Agents. |
| `quote` ignores Finance too | In Messaging apps, use **Link my account…** and choose **This is me** for your Mattermost user. |
| An agent asks for permission to run `python3` | Approve it in the chat once. Or set `auto_approve: true` on that agent in the template; it skips every permission check, so use it for the demo only. |
| The numbers differ from this script | Run `./scripts/reset_demo.sh`. An earlier take changed the data. |
