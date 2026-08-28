/**
 * Every available player, in one list.
 *
 * There used to be two: a pool ranked by raw value and a suggestion panel
 * ranked by what you should actually take. They disagreed constantly and
 * nothing explained why. This is one list with one default order — the
 * engine's recommendation — and a sort control for when you want a different
 * question answered.
 */

import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import type { AdviceBoard, LeagueSettings, PlayerScore } from "../api/types";
import { rosterFit } from "../lib/fit";
import PlayerRow from "./PlayerRow";
import PositionFilter from "./PositionFilter";

const ROW_HEIGHT = 52;
const NUMBERS_KEY = "apollo.showNumbers";

type SortKey = "recommended" | "value" | "adp";

const SORT_LABELS: Record<SortKey, string> = {
  recommended: "best for you",
  value: "raw value",
  adp: "ADP",
};

interface Props {
  advice: AdviceBoard | undefined;
  loading: boolean;
  currentPick: number;
  league: LeagueSettings;
  rosterCounts: Record<string, number>;
  selectedId: string | null;
  onSelect: (score: PlayerScore) => void;
  onDraft?: (score: PlayerScore) => void;
}

export default function PlayerList({
  advice,
  loading,
  currentPick,
  league,
  rosterCounts,
  selectedId,
  onSelect,
  onDraft,
}: Props) {
  const [search, setSearch] = useState("");
  const [positions, setPositions] = useState<string[]>([]);
  const [sort, setSort] = useState<SortKey>("recommended");
  const [showNumbers, setShowNumbers] = useState(() => {
    try {
      return localStorage.getItem(NUMBERS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const scroller = useRef<HTMLDivElement>(null);

  function toggleNumbers() {
    setShowNumbers((on) => {
      try {
        localStorage.setItem(NUMBERS_KEY, on ? "0" : "1");
      } catch {
        /* private mode: the toggle still works for this session */
      }
      return !on;
    });
  }

  // `evidence.players` is the same 300 players as `ranked`, in the same order,
  // so the recommended ordering comes free and the two can never disagree.
  const players = advice?.evidence.players ?? [];
  const entries = useMemo(() => {
    const map = new Map<string, AdviceBoard["recommendation"]["ranked"][number]>();
    advice?.recommendation.ranked.forEach((entry) => map.set(entry.player_id, entry));
    return map;
  }, [advice?.recommendation.ranked]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    players.forEach((score) => {
      tally[score.player.position] = (tally[score.player.position] ?? 0) + 1;
    });
    return tally;
  }, [players]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = players.filter((score) => {
      if (positions.length && !positions.includes(score.player.position)) return false;
      if (!needle) return true;
      return (
        score.player.name.toLowerCase().includes(needle) ||
        (score.player.team ?? "").toLowerCase().includes(needle)
      );
    });

    if (sort === "value") {
      return [...filtered].sort((a, b) => (b.vorp ?? -1e9) - (a.vorp ?? -1e9));
    }
    if (sort === "adp") {
      return [...filtered].sort((a, b) => (a.adp ?? 1e9) - (b.adp ?? 1e9));
    }
    return filtered; // already in recommended order
  }, [players, positions, search, sort]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  return (
    <section className="flex min-h-0 flex-1 flex-col border-t border-line">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-3 py-2">
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted">Available</h2>

        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as SortKey)}
          className="rounded border border-line bg-raised px-1.5 py-1 text-[11px] text-slate-200 outline-none"
          title="What this list is sorted by"
        >
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <option key={key} value={key}>
              {SORT_LABELS[key]}
            </option>
          ))}
        </select>

        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search…"
          className="w-36 rounded-md border border-line bg-raised px-2.5 py-1 text-xs text-slate-100 outline-none placeholder:text-muted/60 focus:border-sky-500/60"
        />

        <PositionFilter active={positions} onChange={setPositions} counts={counts} />

        <button
          type="button"
          onClick={toggleNumbers}
          className={`ml-auto rounded border px-2 py-1 text-[10px] transition ${
            showNumbers
              ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
              : "border-line text-muted hover:text-slate-300"
          }`}
        >
          {showNumbers ? "✓ numbers" : "show numbers"}
        </button>
      </div>

      <div ref={scroller} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {loading && !advice ? (
          <div className="space-y-1 p-3">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="h-11 animate-pulse rounded bg-raised/60" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted">Nobody matches that filter.</p>
        ) : (
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const score = rows[item.index];
              return (
                <div
                  key={score.player.player_id}
                  className="absolute left-0 top-0 w-full"
                  style={{ height: item.size, transform: `translateY(${item.start}px)` }}
                >
                  <PlayerRow
                    score={score}
                    entry={entries.get(score.player.player_id)}
                    rank={item.index + 1}
                    currentPick={currentPick}
                    fit={rosterFit(score.player.position, league, rosterCounts)}
                    showNumbers={showNumbers}
                    selected={score.player.player_id === selectedId}
                    onSelect={() => onSelect(score)}
                    onDraft={onDraft ? () => onDraft(score) : undefined}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
