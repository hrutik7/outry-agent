# Demo script (2:45)

Three moments the video is built around:
1. **The rep tries to approve their own discount, and nothing happens.** (Switch)
2. **Finance types one line, and the HubSpot deal changes.** (real business system)
3. **Finance tries to approve a loss-making discount, and the code refuses.** (guardrails)

Everything else sets these up.

## Screen layout (1920×1080)

```
┌───────────────────────────────┬───────────────────────────────┐
│ LEFT: Finance (user)          │ RIGHT: Rep (rep.priya)        │
│ normal browser window         │ private window                │
│ tab 1: #deal-desk             │ #deal-desk                    │
│ tab 2: HubSpot Acme deal      │                               │
│ tab 3: HubSpot Brightline     │                               │
└───────────────────────────────┴───────────────────────────────┘
 also open but hidden: Switch Console, a terminal in the repo,
 switch/deal-desk.template.yaml in an editor (line: addressing: owner-agents)
```

- Browser zoom 90%, so pricing's table fits without scrolling.
- Mattermost: hide the left sidebar if you can, so the channel has room.
- Turn off notifications. Close every unrelated tab.

## Before every take

```bash
cd /home/hritik/Desktop/outry-agent/deal-desk-room && ./scripts/reset_demo.sh
```

Refresh both HubSpot tabs: Acme shows **$360,000**, stage **Decision maker bought in**.
Scroll the channel so it's empty or clean. Put the first message in the rep's message
box, ready to send.

**OBS rule:** press **Pause** after every send, and **Resume** when the agent's reply
lands. The video never shows waiting.

---

## 0:00 Hook (camera on the channel, nothing typed)

> "Every SaaS deal desk has this message: *'Acme will sign today if we do 25%. Can we?'*
> It lands in a DM, Finance doesn't have the numbers, and nobody records who said yes.
> We moved it into one channel with three AI teammates, and made sure a rep can't
> approve their own discount."

## 0:12 The team (show the member list, then 3 s of Switch Console's Agents page)

> "Two people: a rep and Finance. Three agents: pricing, quote and pipeline. All of
> them are Switch agents, created from one template and joined to Mattermost as
> teammates."

## 0:22 Easy path: agents hand off to each other (RIGHT, rep)

```
@pricing Brightline Health wants 15% off their 3-year, 120-seat deal.
```

Pause, then resume when quote answers.

> "Inside the policy, no human needed. pricing checks it and hands it to quote by name,
> and the quote is issued."

Optional, 2 s: flick to the Brightline HubSpot tab and refresh, to show contract sent.

## 0:45 Real path: an exception (RIGHT, rep)

```
@pricing Acme wants 25% off a 3-year, 200-seat deal.
```

Pause, then resume when the table lands. Hover the cursor over the table.

> "Here's the maths Finance never had: list, discount, net, margin. It's 5 points over
> what policy allows automatically, still above the margin floor, so pricing doesn't
> decide. It tags Finance, with a counter-offer ready."

## 1:10 ⭐ WOW 1: the rep tries to approve it themselves (RIGHT, rep)

```
@quote Approved D-1001 at 25%
```

**Don't pause.** Let 5 seconds of silence play on camera.

> "The rep tries to approve their own discount… and nothing. quote never hears it."

Cut to the template in the editor, with `addressing: owner-agents` highlighted (3 s).

> "That's not a prompt saying 'please only listen to Finance'. It's Switch addressing:
> quote only accepts messages from its owner, Finance, and Finance's own agents.
> The message is never delivered, so there's nothing to talk the model into."

## 1:30 ⭐ WOW 2: Finance decides in one line, and the CRM updates (LEFT, Finance)

```
@quote Counter D-1001 at 20% + prepay
```

Pause, then resume when "Quote issued" lands.

> "Finance counters with one line. The quote is issued at 20% with prepay, at a 62.5%
> margin…"

Switch to the HubSpot Acme tab and **refresh on camera**. Point at Amount $288,000,
stage Contract sent, Approved by, and the Deal desk note on the timeline.

> "…and the real deal record in HubSpot already has the approved price, the stage,
> who approved it, and the full calculation. The approval didn't stay in chat."

## 2:00 ⭐ WOW 3: even Finance can't break the floor (RIGHT, then LEFT)

Rep:
```
@pricing Kestrel Logistics needs 40% off the 1-year, 60-seat deal or they walk.
```

Pause, then resume. pricing says BLOCKED: margin 50%, below the 55% floor.

Finance:
```
@quote Approved D-1003 at 40%
```

Pause, then resume. quote posts **REFUSED: … below the 55% floor … the most Finance can approve is 33%.**

> "Even Finance can't approve a deal that loses money. The maths lives in tested code,
> not in the model, so it says no every time."

## 2:25 Anyone can see the state (RIGHT, rep)

```
@pipeline what's pending approval?
```

Pause, then resume.

> "And anyone can ask what's waiting, without pinging Finance."

## 2:35 Close (back on the full channel)

> "One Switch template. Three AI teammates. Every number shown, every approval
> enforced, and every decision written to the CRM. That's Deal Desk Room."

End card (3 s): repo URL, "Built on Switch".

---

## Tips

- **Do one full practice run before recording.** Agents can word things differently
  between runs, so know what to expect.
- **Record each "wow" as its own clip** if a take goes wrong. Reset between clips with
  `reset_demo.sh`. Brightline, Acme and Kestrel don't depend on each other.
- **Read the narration from a second screen or your phone.** Aim for natural, not
  memorised.
- **Mic close, room quiet.** Audio quality matters more to viewers than video quality.
- **Don't show:** setup, Switch Console forms, the terminal (unless asked), or waiting
  time.
- **If an agent says something unexpected,** keep going if it's still correct. Judges
  like to see that it's real.

## If something goes wrong

| Symptom | Fix |
|---|---|
| No agent replies at all | Switch Console must stay open. Check the agents are running under Agents. |
| `quote` ignores Finance | Finance must be the Mattermost account Switch linked to you (`user`). |
| `quote` replies to the rep in WOW 1 | Stop and tell the developer: the addressing isn't enforced in this setup. |
| An agent asks for permission to run `python3` | Approve it once, then reset and retake. |
| The numbers or HubSpot values look wrong | Run `./scripts/reset_demo.sh` and refresh HubSpot. An earlier take changed the data. |
