/** Where the draft is, whether it is your turn, and the state of the sync. */

import type { DraftState, SessionResponse } from "../api/types";
import type { SyncStatus } from "../store/useDraft";
import { leagueLabel } from "../lib/format";

interface Props {
  session: SessionResponse;
  state: DraftState | undefined;
  sync: SyncStatus;
  onTogglePause: () => void;
  onSyncNow: () => void;
  onUndo: () => void;
  undoing: boolean;
  onReset: () => void;
}

export default function TopBar({
  session,
  state,
  sync,
  onTogglePause,
  onSyncNow,
  onUndo,
  undoing,
  onReset,
}: Props) {
  const totalPicks = session.league.rounds * session.league.teams;
  // A finished draft has no pick on the clock; the old header happily showed
  // "Round 14 · Pick 157 · YOUR PICK" for a 156-pick draft.
  const complete = (state?.current_pick ?? 1) > totalPicks;
  const myTurn = !complete && (state?.is_my_pick ?? false);
  const away =
    state?.my_next_pick != null ? Math.max(0, state.my_next_pick - state.current_pick) : null;

  return (
    <header
      className={`flex shrink-0 items-center gap-4 border-b px-4 py-2.5 transition-colors ${
        myTurn ? "border-sky-500/50 bg-sky-500/10" : "border-line bg-panel"
      }`}
    >
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-bold tracking-tight text-slate-100">Apollo</span>
        <span className="text-xs text-muted">{session.league.name}</span>
      </div>

      <div className="h-5 w-px bg-line" />

      <div className="flex items-center gap-4 text-sm">
        {complete ? (
          <Stat label="Draft" value={`complete · ${totalPicks} picks`} />
        ) : (
          <>
            <Stat label="Round" value={state ? `${state.current_round}` : "—"} />
            <Stat label="Pick" value={state ? `${state.current_pick}` : "—"} />
            <Stat
              label="On the clock"
              value={
                state
                  ? state.on_the_clock_slot === state.my_draft_slot
                    ? "YOU"
                    : state.slot_names?.[String(state.on_the_clock_slot)] ??
                      `Team ${state.on_the_clock_slot}`
                  : "—"
              }
            />
          </>
        )}
      </div>

      <div className="h-5 w-px bg-line" />

      {complete ? (
        <span className="text-xs text-muted">Every pick is in.</span>
      ) : myTurn ? (
        <span className="animate-clock rounded-md bg-sky-500 px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-slate-950">
          Your pick
        </span>
      ) : (
        <span className="text-xs text-muted">
          {away === null
            ? "no picks left"
            : `Your next pick is ${state?.my_next_pick} — ${away} away`}
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        <span className="text-xs text-muted">{leagueLabel(session.league)}</span>

        {sync.enabled ? (
          <SyncBadge sync={sync} onToggle={onTogglePause} onSyncNow={onSyncNow} />
        ) : (
          <span className="chip bg-line text-muted">manual</span>
        )}

        <button
          type="button"
          onClick={onUndo}
          disabled={undoing || !state?.picks.length}
          className="rounded-md border border-line px-2.5 py-1 text-xs text-slate-300 transition hover:bg-raised disabled:opacity-30"
        >
          Undo pick
        </button>
        <button
          type="button"
          onClick={onReset}
          className="rounded-md border border-line px-2.5 py-1 text-xs text-muted transition hover:bg-raised hover:text-slate-300"
        >
          New draft
        </button>
      </div>
    </header>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className="font-semibold tabular-nums text-slate-100">{value}</span>
    </span>
  );
}

function SyncBadge({
  sync,
  onToggle,
  onSyncNow,
}: {
  sync: SyncStatus;
  onToggle: () => void;
  onSyncNow: () => void;
}) {
  const age = sync.lastEventAt ? Math.round((Date.now() - sync.lastEventAt) / 1000) : null;
  // Stale is reported honestly. The old badge showed the last *success* and sat
  // there green while the board was twenty picks behind.
  const stale = age !== null && age > 45;

  const tone =
    sync.error || sync.connection === "reconnecting"
      ? "border-amber-500/40 text-amber-300"
      : sync.paused
        ? "border-line text-muted"
        : stale
          ? "border-amber-500/40 text-amber-300"
          : sync.connection === "live"
            ? "border-emerald-500/40 text-emerald-300"
            : "border-line text-muted";

  const label = sync.paused
    ? "paused"
    : sync.connection === "reconnecting"
      ? "reconnecting…"
      : sync.connection === "connecting"
        ? "connecting…"
        : stale
          ? `stale ${age}s`
          : "live";

  return (
    <div className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${tone}`}>
      <button type="button" onClick={onToggle} title={sync.paused ? "Resume" : "Pause"}>
        {sync.paused ? "▶" : "⏸"}
      </button>
      <button
        type="button"
        onClick={onSyncNow}
        title={sync.error ?? "Streaming picks from Sleeper. Click to resync now."}
        className="tabular-nums"
      >
        {label}
      </button>
      {sync.unmatched > 0 && (
        <span
          className="text-amber-400"
          title={`${sync.unmatched} Sleeper picks did not match the registry`}
        >
          ⚠{sync.unmatched}
        </span>
      )}
    </div>
  );
}
