/**
 * Your whole team — starters and bench.
 *
 * The strip this replaces showed the starting lineup and reduced the bench to
 * a count, so half the roster was invisible. If the team matters enough to
 * drive every recommendation, it should be readable in full.
 */

import { useMemo } from "react";

import type { DraftState, LeagueSettings, RosterPlayer } from "../api/types";
import { positionStyle } from "../lib/positions";

interface Props {
  state: DraftState | undefined;
  league: LeagueSettings;
}

/** Lineup-card order, not alphabetical. */
const SLOT_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "K", "DST"];

export default function RosterTab({ state, league }: Props) {
  const { starters, bench, byes } = useMemo(() => {
    const players: RosterPlayer[] =
      state?.rosters[String(league.my_draft_slot)]?.players ?? [];
    const pool = [...players];

    /** Earliest-drafted player at a position is the likeliest starter. */
    const take = (positions: string[]): RosterPlayer | null => {
      const index = pool.findIndex((p) => positions.includes(p.position));
      return index === -1 ? null : pool.splice(index, 1)[0];
    };

    const built: { label: string; position: string; player: RosterPlayer | null }[] = [];
    for (const position of SLOT_ORDER) {
      const count = league.roster[position] ?? 0;
      for (let i = 0; i < count; i += 1) {
        built.push({
          label: count > 1 ? `${position}${i + 1}` : position,
          position,
          player: take(position === "FLEX" ? league.flex_eligible : [position]),
        });
      }
    }

    const tally = new Map<number, RosterPlayer[]>();
    players.forEach((p) => {
      if (!p.bye_week || p.position === "K" || p.position === "DST") return;
      tally.set(p.bye_week, [...(tally.get(p.bye_week) ?? []), p]);
    });

    return {
      starters: built,
      bench: pool,
      byes: [...tally.entries()]
        .filter(([, group]) => group.length >= 2)
        .sort((a, b) => b[1].length - a[1].length),
    };
  }, [state?.rosters, league]);

  const open = starters.filter((s) => !s.player).length;
  const benchSlots = league.roster.BENCH ?? 0;

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="text-[10px] font-bold uppercase tracking-widest text-muted">
          Starters
        </h3>
        <span className="text-[10px] text-muted">
          {open > 0 ? `${open} open` : "all set"}
        </span>
      </div>

      <div className="space-y-1">
        {starters.map((slot) => {
          const style = positionStyle(slot.player?.position ?? slot.position);
          return (
            <div
              key={slot.label}
              className={`flex items-center gap-2 rounded border px-2 py-1.5 ${
                slot.player
                  ? "border-line bg-raised"
                  : "border-dashed border-sky-500/50 bg-sky-500/5"
              }`}
            >
              <span
                className={`w-11 shrink-0 text-[10px] font-bold uppercase tracking-wide ${
                  slot.player ? "text-muted" : "text-sky-400"
                }`}
              >
                {slot.label}
              </span>
              {slot.player ? (
                <>
                  <span className="min-w-0 flex-1 truncate text-xs text-slate-100">
                    {slot.player.name}
                  </span>
                  <span className={`shrink-0 text-[10px] ${style.text}`}>
                    {slot.player.position} · {slot.player.team ?? "FA"}
                  </span>
                  <span className="w-10 shrink-0 text-right text-[10px] text-muted">
                    {slot.player.bye_week ? `bye ${slot.player.bye_week}` : ""}
                  </span>
                </>
              ) : (
                <span className="flex-1 text-xs text-sky-400/70">open</span>
              )}
            </div>
          );
        })}
      </div>

      <div className="mb-2 mt-4 flex items-baseline gap-2">
        <h3 className="text-[10px] font-bold uppercase tracking-widest text-muted">Bench</h3>
        <span className="text-[10px] text-muted">
          {bench.length}/{benchSlots}
        </span>
      </div>

      {bench.length === 0 ? (
        <p className="text-[11px] text-muted">Nothing on the bench yet.</p>
      ) : (
        <div className="space-y-1">
          {bench.map((player) => {
            const style = positionStyle(player.position);
            return (
              <div
                key={player.player_id}
                className="flex items-center gap-2 rounded border border-line/60 px-2 py-1.5"
              >
                <span className={`chip w-9 shrink-0 justify-center ${style.chip}`}>
                  {player.position}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
                  {player.name}
                </span>
                <span className="shrink-0 text-[10px] text-muted">
                  {player.team ?? "FA"}
                  {player.bye_week ? ` · bye ${player.bye_week}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {byes.length > 0 && (
        <>
          <h3 className="mb-2 mt-4 text-[10px] font-bold uppercase tracking-widest text-muted">
            Bye weeks
          </h3>
          {byes.map(([week, group]) => (
            <p
              key={week}
              className={`mb-1 text-[11px] leading-snug ${
                group.length >= 3 ? "text-amber-300" : "text-muted"
              }`}
            >
              <strong>Week {week}:</strong> {group.map((p) => p.name).join(", ")}
            </p>
          ))}
        </>
      )}
    </div>
  );
}
