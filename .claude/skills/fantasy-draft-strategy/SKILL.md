---
name: fantasy-draft-strategy
description: How fantasy football drafts actually work — positional timing windows, replacement level, and the named strategies (Zero-RB, Hero-RB, Robust-RB, late-round QB). Read before changing anything that ranks, recommends, or explains a draft pick in Apollo, and before judging whether a recommendation is good.
---

# How fantasy drafts actually work

Apollo kept producing recommendations that were arithmetically defensible and
strategically wrong — a quarterback in round two, a kicker floated into the top
ten. Every one of those came from the same gap: the engine's measures are
**local**, and drafting is **global**.

Read this before touching anything that ranks or recommends a pick.

## The one idea everything rests on: replacement level

Raw projected points cannot compare positions. A quarterback scoring 20 a game
looks like the best player available, and he is — until you notice that the
*twelfth* quarterback also scores about 17. In a 12-team league somebody will
be starting QB12, so drafting QB1 buys you roughly **3 points a game** over
what you could have had for free.

Meanwhile RB30 — the back you would be left with — might score 8, so an elite
back buys you **10+**. That gap is the entire game.

> **Value is always measured against the player you would otherwise have had at
> that position, never in the absolute.**

This is what VORP does, and it is the correction that must be applied to *any*
new measure. When we added expected-points-per-game from real usage, we ranked
"upside" on the raw number and a quarterback won every time — the exact mistake
this section warns about, made in a fresh place.

## Why timing needs its own layer

VORP compares to replacement. VONA looks one turn ahead. **Neither can see the
cost of taking a quarterback in round two**, because that cost is not paid at
your next pick — it is paid across the whole draft, in the running back or
receiver you never got.

A one-turn simulation will happily tell you Josh Allen is scarce right now. He
is. It cannot tell you that a nearly-as-good quarterback will be sitting there
in round seven while the elite backs will not. That is why the round windows
below are stated explicitly rather than derived.

## The windows (12-team, 1-QB, PPR)

Encoded in `Apollo/backend/app/scoring/draft_strategy.py`, which is the single
source of truth — the LLM prompt is generated from it. Change them there.

| Position | Normal | Never before | Why |
|---|---|---|---|
| RB / WR | R1–12 | — | The scarce, league-winning positions. |
| TE | R7–14 | R1 for the **top 2** | Replacement TE is dreadful, so a genuinely elite one is worth an early pick. |
| QB | R6–12 | R6 | QB12 ≈ QB1. Large price, small edge. |
| DST | last few | R10 | Streamable all season. |
| K | last round | R13 | Entirely random. Never spend a real pick. |

### The exception is a property of the position, not the player

This is the subtle part and it is easy to get wrong. Elite tight end is a real
exception; elite quarterback is not — **even though both are the number one
player at their position**. The difference is what replacement looks like
behind them.

A rule like "let tier-1 players through" would pass Josh Allen and Trey McBride
alike. That is why `Window.elite_rank` is declared per position: `TE: 2` lets
Bowers and McBride go in round two, `QB: 0` keeps Allen out.

### Superflex inverts the QB rule

You start two quarterbacks, so the position becomes genuinely scarce and elites
go in round one. Any QB rule that does not check `league.superflex` is wrong for
that format, not merely imprecise.

## The named strategies

- **Balanced** — best available inside the windows. The default.
- **Hero RB** — one elite back, then receivers. Round 2–4 receivers become WR1s
  more often than round 5+ backs become RB1s. *Roster-dependent*: the first back
  is free, the next waits.
- **Zero RB** — no backs for four to six rounds; stack receivers and an elite
  tight end, then buy volume backs late. The bet is injury arbitrage — early
  backs bust and break at the draft's highest rate.
- **Robust RB** — two backs in the first two rounds to corner the scarcest
  volume. Doubles the injury exposure. *Roster-dependent*: receivers wait until
  the two backs are banked.
- **Late-round QB** — be the last team without a quarterback, then take two
  darts. Reigning QB1s regularly slip past round 10.

Hero-RB and Robust-RB cannot be expressed as static windows; they depend on what
you already have, which is why `Profile.dynamic` takes the roster.

## Judging a recommendation

Before calling a pick good, ask in this order:

1. **Is the position in its window?** A QB in round 2 or a K before the last
   round is wrong regardless of how good the number looks.
2. **Is the value measured against replacement?** If the comparison is raw
   points, it is meaningless across positions.
3. **Does it fill a slot you can actually start?** A second QB in a 1-QB league
   contributes nothing to your lineup no matter how scarce QBs look.
4. **What do you lose?** The pick you do not make is the real cost.

## Sources

- [QB List — round-by-round guide](https://football.pitcherlist.com/the-ultimate-fantasy-football-draft-guide-2026-who-to-draft-when/)
- [CBS / Jamey Eisenberg — draft plan](https://www.cbssports.com/fantasy/football/news/jamey-eisenbergs-2026-fantasy-draft-plan/)
- [RotoWire — strategy guide](https://www.rotowire.com/football/article/2026-fantasy-football-draft-strategy-the-ultimate-fantasy-football-draft-strategy-guide-130253)
- [Blitz Sports Media — Zero-RB vs Hero-RB](https://blitzsportsmedia.com/zero-rb-vs-hero-rb/)

These are 2026 consensus for 12-team 1-QB PPR. Formats move the windows;
superflex moves them a lot.
