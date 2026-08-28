# Apollo — draft cockpit (frontend)

A single-screen draft board for the Apollo engine. The Sleeper-style grid, the
available-player pool, the engine's suggestions for your slot, why each player
rates where he does and how he fits your roster, and a chat rail.

## Run it

The backend has to be up first:

```bash
cd ../backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload     # first boot builds the registry
```

Then:

```bash
npm install
npm run dev            # http://localhost:5173
```

`/api` is proxied to `http://localhost:8000` by `vite.config.ts`. Set
`VITE_API_BASE=http://localhost:8000` to bypass the proxy and talk to uvicorn
directly — worth trying if the chat answer ever arrives in one block instead of
streaming (backend CORS is already open).

## Layout

```
TopBar          round, pick, who is on the clock, live/stale state, undo
DraftBoard      rounds x teams, snake-aware, real manager names, your column outlined
PlayerList      the pool, ranked by VORP, virtualized, search + position filter
DraftPulse      positional runs and bye-week stacks on your roster
SuggestionPanel /advice/board — ranked by VONA, with tiers and reach/value flags
PlayerDrawer    click any player: fit, verdict, confidence breakdown, signals
ChatPanel       streaming /chat, grounded in the current board
```

## VONA, not VORP, in the suggestions

The pool list ranks by VORP — value against a fixed replacement. The
suggestions rank by **VONA**: value over the *next available* player at that
position, measured by simulating the room to your next real turn.

The difference matters most at quarterback. VORP happily floats a QB to the top
because QB12 is weak, but if three comparable quarterbacks survive to your next
pick, taking one now gains you almost nothing. VONA prices that in, and on the
wheel it measures against the pick *after* your back-to-back pair — comparing
pick 12 to pick 13 makes everything look equally urgent and collapses the
ranking.

## Live updates

Picks arrive over SSE from `GET /draft/events`, not a browser timer. Chrome
throttles `setInterval` in hidden tabs to roughly once a minute, and this app
lives in a hidden tab while you draft in Sleeper. A 30s fallback poll and a
resync on tab focus cover the case where the stream cannot connect; the badge
reports `live` / `reconnecting` / `stale` honestly rather than always green.

## What costs what

`GET /players/{id}` and `GET /advice/wait-vs-take` each run a 1000-run Monte
Carlo simulation, so the drawer opens from the `PlayerScore` the list already
holds and fills those two in behind skeletons. Nothing blocks on them.

The Claude layer is **on demand**: every request passes
`validate_with_claude=false`, and the review buttons in the suggestion panel and
the drawer are what trigger it. Without `ANTHROPIC_API_KEY` on the backend those
buttons and the chat composer are replaced by a note; everything else works.

## Sleeper

Start a session from a draft ID and picks stream in as they land. One server
poller serves every tab on a session, and the board only re-scores when
`current_pick` actually moves. Column headers show real manager names where
Sleeper knows one, falling back to `Team N` for CPU slots in a mock.

## Claude review

Two buttons rather than one. `quick check` runs at medium effort (~25s),
`deep review` at full effort (~35s) — pick based on how much clock is left.
Both are non-blocking and show elapsed seconds, because a silent 30s wait reads
as a hang.

Fast Mode (2.5x on the same model, no quality traded) is attempted first and
switches itself off for the process the moment the API says the account has no
quota — retrying a request we know will 429 costs a whole round trip.

## Connecting Sleeper

Enter your **username**; the app resolves your account and lists your leagues.
Mock drafts are not in that listing, so paste the draft id for those. Your draft
slot is pre-selected when Sleeper has assigned the order and **must be chosen**
when it has not — it is never defaulted, because a wrong slot silently poisons
replacement level and every recommendation after it.

## Checks

```bash
npm run typecheck
```
