/**
 * The Sleeper-style grid: rounds down, teams across.
 *
 * Cell → pick number uses the same snake formula the backend numbers picks
 * with (`pickNumber`, mirroring LeagueSettings.pick_numbers_for_slot), so the
 * grid and `picks[].overall` cannot drift apart.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { DraftState, LeagueSettings } from "../api/types";
import { pickNumber } from "../lib/format";
import { positionStyle } from "../lib/positions";

interface Props {
  league: LeagueSettings;
  state: DraftState | undefined;
}

const OPEN_KEY = "apollo.boardOpen";

export default function DraftBoard({ league, state }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const currentCell = useRef<HTMLDivElement>(null);
  // Collapsed by default: the grid is reference material, not the thing you
  // make a decision from, and it was eating 40% of the screen.
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(OPEN_KEY) === "1";
    } catch {
      return false;
    }
  });

  function toggle() {
    setOpen((was) => {
      try {
        localStorage.setItem(OPEN_KEY, was ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !was;
    });
  }

  const byOverall = useMemo(() => {
    const map = new Map<number, DraftState["picks"][number]>();
    state?.picks.forEach((pick) => map.set(pick.overall, pick));
    return map;
  }, [state?.picks]);

  const upcomingMine = useMemo(
    () => new Set(state?.my_remaining_picks ?? []),
    [state?.my_remaining_picks],
  );

  // Keep the pick on the clock in view as the draft moves down the board.
  useEffect(() => {
    currentCell.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [state?.current_pick]);

  const rounds = Array.from({ length: league.rounds }, (_, index) => index + 1);
  const slots = Array.from({ length: league.teams }, (_, index) => index + 1);

  return (
    <section className={`flex flex-col ${open ? "min-h-0 flex-1" : "shrink-0"}`}>
      <button
        type="button"
        onClick={toggle}
        className="flex shrink-0 items-center gap-2 px-3 py-1.5 text-left transition hover:bg-raised/40"
      >
        <span className="text-[10px] text-muted">{open ? "▾" : "▸"}</span>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted">Draft board</h2>
        <span className="ml-auto text-[10px] text-muted">
          {state?.picks.length ?? 0} of {league.rounds * league.teams} picks
        </span>
      </button>

      {!open ? null : (
      <div ref={scroller} className="scroll-thin min-h-0 flex-1 overflow-auto px-3 pb-3">
        <div
          className="grid gap-1"
          style={{ gridTemplateColumns: `2rem repeat(${league.teams}, minmax(6.5rem, 1fr))` }}
        >
          {/* Header row: one column per draft slot. */}
          <div className="sticky top-0 z-10 bg-ink" />
          {slots.map((slot) => {
            const mine = slot === league.my_draft_slot;
            // Real manager names where Sleeper knows one; CPU teams in a mock
            // have no user behind them and keep the generic label.
            const name = state?.slot_names?.[String(slot)];
            return (
              <div
                key={`head-${slot}`}
                title={name ?? `Team ${slot}`}
                className={`sticky top-0 z-10 truncate bg-ink pb-1 text-center text-[10px] font-bold uppercase tracking-wide ${
                  mine ? "text-sky-400" : "text-muted"
                }`}
              >
                {mine ? "You" : name ?? `Team ${slot}`}
              </div>
            );
          })}

          {rounds.map((round) => (
            <RoundRow
              key={round}
              round={round}
              slots={slots}
              league={league}
              byOverall={byOverall}
              upcomingMine={upcomingMine}
              currentPick={state?.current_pick ?? 0}
              currentCellRef={currentCell}
            />
          ))}
        </div>
      </div>
      )}
    </section>
  );
}

function RoundRow({
  round,
  slots,
  league,
  byOverall,
  upcomingMine,
  currentPick,
  currentCellRef,
}: {
  round: number;
  slots: number[];
  league: LeagueSettings;
  byOverall: Map<number, DraftState["picks"][number]>;
  upcomingMine: Set<number>;
  currentPick: number;
  currentCellRef: React.RefObject<HTMLDivElement>;
}) {
  return (
    <>
      <div className="flex items-center justify-center text-[10px] font-semibold tabular-nums text-muted">
        {round}
      </div>
      {slots.map((slot) => {
        const overall = pickNumber(league, round, slot);
        const pick = byOverall.get(overall);
        const isCurrent = overall === currentPick;
        const isMine = slot === league.my_draft_slot;

        if (pick) {
          const style = positionStyle(pick.position);
          return (
            <div
              key={overall}
              className={`min-w-0 rounded border-l-2 bg-raised px-1.5 py-1 ${style.border} ${
                isMine ? "ring-1 ring-inset ring-sky-500/40" : ""
              }`}
            >
              <div className="truncate text-[11px] font-medium leading-tight text-slate-200">
                {pick.player_name ?? pick.player_id}
              </div>
              <div className={`truncate text-[9px] leading-tight ${style.text}`}>
                {pick.position ?? "—"} · {overall}
              </div>
            </div>
          );
        }

        return (
          <div
            key={overall}
            ref={isCurrent ? currentCellRef : undefined}
            className={`flex min-w-0 items-center justify-center rounded border border-dashed px-1 py-1 text-[10px] tabular-nums ${
              isCurrent
                ? "animate-clock border-sky-500 bg-sky-500/10 font-bold text-sky-300"
                : isMine
                  ? upcomingMine.has(overall)
                    ? "border-sky-500/40 bg-sky-500/5 text-sky-400/70"
                    : "border-sky-500/20 text-muted/50"
                  : "border-line text-muted/40"
            }`}
          >
            {overall}
          </div>
        );
      })}
    </>
  );
}
