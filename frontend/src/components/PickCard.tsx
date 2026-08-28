/**
 * Two or three ways to use this pick, not one instruction.
 *
 * A single name reads as a command and invites the question "why not the other
 * guy". These are the three axes a drafter actually weighs — is he cheap, is he
 * safe, is he going to win me weeks — each with the trade-off stated, so the
 * decision stays yours.
 */

import { useEffect, useRef, useState } from "react";

import * as api from "../api/client";
import type {
  AdviceBoard,
  LeagueSettings,
  PlayerScore,
  StrategyKey,
  Validation,
} from "../api/types";
import { rosterFit } from "../lib/fit";
import { positionStyle } from "../lib/positions";
import ClaudeReview from "./ClaudeReview";

const AXIS_LABEL: Record<string, string> = {
  value: "BEST VALUE",
  safe: "SAFEST",
  upside: "MOST UPSIDE",
};

export const STRATEGY_LABELS: Record<StrategyKey, string> = {
  balanced: "Balanced",
  hero_rb: "Hero RB",
  zero_rb: "Zero RB",
  robust_rb: "Robust RB",
  late_qb: "Late-round QB",
};

const AXIS_TONE: Record<string, string> = {
  value: "bg-emerald-500/20 text-emerald-300",
  safe: "bg-sky-500/20 text-sky-300",
  upside: "bg-violet-500/20 text-violet-300",
};

interface Props {
  sessionId: string;
  advice: AdviceBoard | undefined;
  loading: boolean;
  isMyPick: boolean;
  currentPick: number;
  picksAway: number | null;
  league: LeagueSettings;
  rosterCounts: Record<string, number>;
  claudeAvailable: boolean;
  playersById: Map<string, PlayerScore>;
  strategy: StrategyKey;
  onStrategyChange: (next: StrategyKey) => void;
  onSelect: (score: PlayerScore) => void;
  onCompare: (playerIds: string[]) => void;
}

export default function PickCard({
  sessionId,
  advice,
  loading,
  isMyPick,
  currentPick,
  picksAway,
  league,
  rosterCounts,
  claudeAvailable,
  playersById,
  strategy,
  onStrategyChange,
  onSelect,
  onCompare,
}: Props) {
  const [review, setReview] = useState<Validation | undefined>();
  const [reviewing, setReviewing] = useState<null | "quick" | "deep">(null);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  const boardPick = advice?.recommendation.current_pick;
  useEffect(() => setReview(undefined), [boardPick]);

  // A 30s review with no feedback looks like a hang; count the seconds.
  useEffect(() => {
    if (!reviewing) {
      if (timer.current) window.clearInterval(timer.current);
      return;
    }
    setElapsed(0);
    timer.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [reviewing]);

  async function requestReview(depth: "quick" | "deep") {
    setReviewing(depth);
    try {
      setReview(
        (await api.getAdviceBoard(sessionId, 12, true, depth, strategy)).validation,
      );
    } catch (error) {
      setReview({ status: "error", detail: (error as Error).message });
    } finally {
      setReviewing(null);
    }
  }

  if (loading && !advice) {
    return (
      <div className="p-3">
        <div className="h-56 animate-pulse rounded-lg bg-raised/60" />
      </div>
    );
  }

  const options = advice?.recommendation.options ?? [];
  const pair = advice?.recommendation.pair ?? null;
  const mode = advice?.recommendation.mode ?? "gain";
  const notes = advice?.recommendation.strategy_notes ?? [];
  if (options.length === 0) {
    // Happens once the roster is full: nothing left can crack the lineup, so
    // there is no recommendation to make. Say so rather than showing nothing.
    return (
      <div className="p-4">
        <p className="text-xs leading-relaxed text-muted">
          Every starting slot is filled and your bench is set — there is nothing
          left worth recommending. The list on the left is still searchable if
          you want to look someone up.
        </p>
      </div>
    );
  }

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3">
      <div className="mb-2 flex items-baseline gap-2">
        <span
          className={`text-[10px] font-bold uppercase tracking-widest ${
            isMyPick ? "text-sky-300" : "text-muted"
          }`}
        >
          {isMyPick ? `Your pick · ${currentPick}` : "Next up"}
        </span>
        {!isMyPick && picksAway !== null && (
          <span className="text-[10px] text-muted">
            {picksAway} {picksAway === 1 ? "pick" : "picks"} away
          </span>
        )}
        {mode === "best_available" && (
          <span className="chip bg-slate-500/25 text-slate-300">best left</span>
        )}
        <select
          value={strategy}
          onChange={(event) => onStrategyChange(event.target.value as StrategyKey)}
          className="ml-auto rounded border border-line bg-raised px-1.5 py-0.5 text-[10px] text-slate-200 outline-none"
          title="Which draft strategy the board should follow"
        >
          {(Object.keys(STRATEGY_LABELS) as StrategyKey[]).map((key) => (
            <option key={key} value={key}>
              {STRATEGY_LABELS[key]}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        {options.map((option) => {
          const style = positionStyle(option.position);
          const score = playersById.get(option.player_id);
          const fit = rosterFit(option.position, league, rosterCounts);
          return (
            <button
              key={option.player_id}
              type="button"
              onClick={() => score && onSelect(score)}
              className={`block w-full rounded-lg border p-3 text-left transition hover:bg-raised/60 ${
                isMyPick ? "border-line bg-panel" : "border-line/60"
              }`}
            >
              <div className="flex flex-wrap items-center gap-1">
                {option.axes.map((axis) => (
                  <span
                    key={axis}
                    className={`chip ${AXIS_TONE[axis] ?? "bg-line text-muted"}`}
                  >
                    {AXIS_LABEL[axis] ?? axis}
                  </span>
                ))}
                {fit.kind === "starter" && (
                  <span className="chip bg-sky-500/15 text-sky-300">
                    fills {fit.slotLabel}
                  </span>
                )}
                {fit.kind === "depth" && (
                  <span className="chip bg-line text-muted">bench</span>
                )}
              </div>

              <div className="mt-1.5 text-sm font-bold leading-tight text-slate-100">
                {option.name}
              </div>
              <div className={`text-[11px] ${style.text}`}>
                {option.position} · {option.team ?? "FA"}
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-300">
                {option.reason}
              </p>
            </button>
          );
        })}
      </div>

      {options.length > 1 && (
        <button
          type="button"
          onClick={() => onCompare(options.map((o) => o.player_id))}
          className="mt-2 w-full rounded-md border border-line px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-raised"
        >
          Compare these side by side
        </button>
      )}

      {notes.length > 0 && (
        <div className="mt-3 rounded-md border border-line bg-raised/40 px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted">
            Not yet
          </p>
          {notes.map((note) => (
            <p key={note} className="mt-1 text-[11px] leading-snug text-muted">
              {note}
            </p>
          ))}
        </div>
      )}

      {pair && (
        <div className="mt-3 rounded-md border border-indigo-500/30 bg-indigo-500/5 px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
            You pick twice in a row
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            {pair.note}
          </p>
        </div>
      )}

      <div className="mt-3 space-y-2">
        {reviewing ? (
          <div className="flex items-center gap-2 rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-xs text-violet-300">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
            Claude is {reviewing === "deep" ? "reviewing in depth" : "checking"}… {elapsed}s
          </div>
        ) : review ? (
          <ClaudeReview
            validation={review}
            available={claudeAvailable}
            onDismiss={() => setReview(undefined)}
          />
        ) : claudeAvailable ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => requestReview("quick")}
              className="flex-1 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-2 text-[11px] font-semibold text-violet-300 transition hover:bg-violet-500/20"
              title="Lower effort — for when the clock is short"
            >
              quick check <span className="opacity-60">~25s</span>
            </button>
            <button
              type="button"
              onClick={() => requestReview("deep")}
              className="flex-1 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-2 text-[11px] font-semibold text-violet-300 transition hover:bg-violet-500/20"
              title="Full effort — the deeper critique"
            >
              deep review <span className="opacity-60">~35s</span>
            </button>
          </div>
        ) : (
          <ClaudeReview validation={undefined} available={false} />
        )}
      </div>
    </div>
  );
}
