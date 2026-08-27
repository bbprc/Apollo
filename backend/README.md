# Apollo — Fantasy Football Draft Assistant (backend)

A draft-day decision engine. Recommendations are **computed deterministically**;
Claude reviews them as a **second layer**. Every number is reproducible and
carries its own breakdown, and every player named anywhere comes from a registry
of current-season NFL rosters.

FastAPI service with OpenAPI docs at `/docs`. A UI can sit on top of it later —
every advice endpoint returns the same envelope so there is one shape to bind to.

---

## Quick start

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # optional; it runs without any keys
.venv/bin/uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs>. Then, in order:

1. `POST /league` — set scoring, teams, roster slots, flex, your draft slot.
2. `POST /draft/sessions` — start a session from that `league_id`.
3. `GET /players?session_id=…` — the ranked board.
4. `POST /draft/picks` — record picks (or `POST /draft/sync` for Sleeper).
5. `GET /advice/wait-vs-take?session_id=…&player_name=…` — the call, and what it costs.

Everything works with **no API keys at all**. Keys upgrade the data and switch on
the review layer; nothing breaks without them.

---

## What it does

### Draft Confidence Score (0–100)

Deliberately *not* projected points — that is what VORP measures. Confidence
answers **"how sure are we that this pick works out at this slot"**, so expert
disagreement pushes it down while durability, volume and an easy schedule push
it up. Components, each z-scored then weighted:

| Component | Source | Note |
|---|---|---|
| Value vs. ADP | FantasyPros consensus | Positive = he fell past his ADP |
| Strength of schedule | computed from nflverse | Season **and** fantasy playoffs, reported apart |
| Injury risk | nflverse injury reports, 2009+ | Games missed and practice participation, recency-weighted |
| Opportunity share | nflverse weekly stats | Target share, rush share, snap share |
| Consensus uncertainty | FantasyPros `sd`/`best`/`worst` | Wide expert spread **lowers** confidence |

Weights live in `app/config.py` (`ConfidenceWeights`) and are overridable per
environment via `APOLLO_WEIGHT_*`. Shares and schedules are standardised *within*
position; ADP value is standardised across the whole pool.

### VORP and wait-vs-take

Raw points cannot compare a back to a receiver, so everything ranks by **value
over replacement**, where replacement level is set by *your* league — teams,
starting slots, flex, superflex. Change `teams` from 10 to 14 and the whole board
re-ranks.

`GET /advice/wait-vs-take` compares his value now against the expected value of
whoever survives to your next pick, weighted by how likely he is to last:

```
rating_value = VORP(now) − E[best VORP at your position of need at next pick]
```

That gap — **the projected points you give up by waiting** — is the headline
number, alongside `probability_available_next_pick` and the reasoning behind both.

### What-if

`POST /advice/what-if` takes the pick hypothetically, simulates the room's
response through your next one or two turns, and reports what the board looks
like when it comes back: who is likely there, what each roster hole is worth by
then, and the shape of your team. It never mutates the live draft.

### The simulator

One Monte Carlo simulator answers all three questions — will he last, should I
wait, what happens if I take him — so they cannot drift apart. Other teams draft
from an ADP-weighted softmax over what is left, tilted toward their roster holes;
sampling uses Gumbel-max with a fixed seed, so results are reproducible.

---

## Current players only

This is enforced structurally, not by asking the model nicely:

1. **Build** — the registry is the union of nflverse current-season rosters and
   Sleeper's active player list, filtered to draftable statuses, joined across
   FantasyPros / Sleeper / nflverse ids.
2. **Inject** — prompts are built *only* from registry rows. No free-form player
   text ever reaches Claude.
3. **Verify** — every response is scanned for player names and checked back
   against the registry. An unknown name triggers one corrective retry; if it
   persists, the commentary is withheld and reported in `filtered_names`.

Step 3 is what actually enforces the rule. Retired players are rejected at every
entry point, including `POST /draft/picks`.

---

## The Claude layer

`claude-opus-5`, adaptive thinking, structured outputs, and a cached system
prefix (the methodology and your league rules) so a draft's worth of validation
calls reuse it.

The audit **never overrides** the computed result. It arrives in a separate
`validation` block so you see where the two disagree:

```jsonc
{
  "recommendation": { "verdict": "TAKE", "rating_value": 74.6, "...": "..." },
  "evidence":       { "player": { "...": "..." }, "alternatives": [] },
  "validation":     { "status": "ok", "agrees": true, "concerns": [], "reasoning": "..." }
}
```

`validation.status` is one of `ok`, `unavailable` (no key), `skipped`
(`validate_with_claude=false`), `error`, or `filtered` (strayed outside the
registry). **A failed model call never takes the draft board down.**

Pass `validate_with_claude=false` to skip the round trip when drafting fast.

---

## Data sources

| Source | Provides | Key |
|---|---|---|
| **FantasyPros v2** | Consensus rankings, ADP, projections | Needed for production; free tier is sample data only |
| **nflverse** (`nflreadpy`) | Weekly stats, injuries 2009+, schedules, snap counts, rosters, id crosswalk, **and a mirror of FantasyPros draft rankings** | None |
| **Sleeper** | Live draft sync, active players | None |

FantasyPros exposes rankings and projections but **not** strength of schedule,
target share, or injury history — those three are computed from nflverse.

Without `FANTASYPROS_API_KEY` the app reads the same FantasyPros draft rankings
through nflverse (`ecr`, `sd`, `best`, `worst`) and derives projections from a
historical rank-to-points curve: what the Nth-best player at a position has
actually scored recently, under your scoring rules. Adding the key later switches
the source with no code change.

Upstream payloads are cached to `.cache/` (`APOLLO_CACHE_DIR`), so startup is
usually offline and Sleeper polling stays far under its rate limit.

---

## Configuration

`.env` or environment, all prefixed `APOLLO_` except the two API keys:

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Switches on validation and chat |
| `FANTASYPROS_API_KEY` | – | Switches the consensus source to FantasyPros |
| `APOLLO_SEASON` | current | Season to analyze |
| `APOLLO_CACHE_DIR` | `.cache` | Upstream payload cache |
| `APOLLO_MONTE_CARLO_RUNS` | `1000` | Simulations per question |
| `APOLLO_SIMULATION_SEED` | `20260827` | Set for reproducibility |
| `APOLLO_ADP_SOFTMAX_TEMPERATURE` | `6.0` | Lower = the room follows ADP more tightly |
| `APOLLO_WAIT_VS_TAKE_THRESHOLD` | `8.0` | Points of VORP gap before it says TAKE |
| `APOLLO_WEIGHT_*` | see `config.py` | Individual confidence weights |

---

## Endpoints

```
GET    /health                    status, registry size, which sources are configured

POST   /league                    create or update a league
GET    /league/presets            scoring presets and their per-stat values
POST   /league/from-sleeper       build a league from a Sleeper draft id

POST   /draft/sessions            start a session
GET    /draft/state               picks, rosters, who is on the clock
POST   /draft/picks               record a pick (by player_id or player_name)
DELETE /draft/picks/last          undo
POST   /draft/sync                pull picks from Sleeper

GET    /players                   ranked board with confidence scores
GET    /players/search            find current players by name
GET    /players/{player_id}       full breakdown: SOS, injury history, share, VORP, availability

GET    /advice/board              top recommendations at the current pick
GET    /advice/wait-vs-take       verdict, rating value, P(reaches your next pick), why
POST   /advice/what-if            take this player — how does the next round look
GET    /advice/compare            several candidates side by side

POST   /chat                      grounded Q&A (set `stream: true` to stream)
```

---

## Tests

```bash
.venv/bin/python -m pytest tests -q                        # everything
.venv/bin/python -m pytest tests -q -m "not integration"   # no network
```

Unit tests cover the maths and the guardrail with synthetic fixtures. The Claude
layer is tested against a stubbed SDK — degradation, the cache breakpoint, the
request shape, and the retry-then-filter path. Integration tests exercise the
live board, the simulator's invariants, and the full HTTP flow.

### Not yet verified

The Claude layer has **never been run against the live API** — no
`ANTHROPIC_API_KEY` was available in this environment. Its contract is covered by
mocks. Before relying on it, set a key and check:

```bash
curl "localhost:8000/advice/wait-vs-take?session_id=…&player_name=Bijan%20Robinson" | jq .validation
```

`status` should be `ok`, and on a second call `validation.usage.cache_read_input_tokens`
should be greater than zero — if it is `0`, something is invalidating the cached
prefix.
