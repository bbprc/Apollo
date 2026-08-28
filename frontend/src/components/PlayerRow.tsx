import type { BoardRankedEntry, PlayerScore } from "../api/types";
import { describe } from "../lib/describe";
import { confidenceTone, decimal, percent, signed } from "../lib/format";
import type { RosterFit } from "../lib/fit";
import { positionStyle } from "../lib/positions";

interface Props {
  score: PlayerScore;
  entry: BoardRankedEntry | undefined;
  rank: number;
  currentPick: number;
  fit: RosterFit;
  /** When false the row speaks English; when true it shows the raw numbers. */
  showNumbers: boolean;
  selected: boolean;
  onSelect: () => void;
  onDraft?: () => void;
}

export default function PlayerRow({
  score,
  entry,
  rank,
  currentPick,
  fit,
  showNumbers,
  selected,
  onSelect,
  onDraft,
}: Props) {
  const { player } = score;
  const style = positionStyle(player.position);
  const adpDelta = score.adp === null ? null : score.adp - currentPick;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect()}
      className={`group flex h-full cursor-pointer items-center gap-3 border-l-2 px-3 text-sm transition ${
        style.border
      } ${selected ? "bg-raised" : "hover:bg-raised/60"}`}
    >
      <span className="w-6 shrink-0 text-right text-xs tabular-nums text-muted">{rank}</span>
      <span className={`chip w-9 shrink-0 justify-center ${style.chip}`}>{player.position}</span>

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate font-medium text-slate-100">{player.name}</span>
          {fit.kind === "starter" && (
            <span className="chip shrink-0 bg-sky-500/20 text-sky-300">need</span>
          )}
          {fit.kind === "flex" && (
            <span className="chip shrink-0 bg-indigo-500/20 text-indigo-300">flex</span>
          )}
          {fit.kind === "depth" && entry && entry.startability < 0.5 && (
            <span className="chip shrink-0 bg-line text-muted">bench</span>
          )}
        </span>

        {showNumbers ? (
          <span className="block truncate text-[11px] text-muted">
            {player.team ?? "FA"} · value {signed(score.vorp, 0)} · usage{" "}
            {percent(score.opportunity_share, 0)} · schedule {decimal(score.sos_season, 2)} · ADP{" "}
            {decimal(score.adp, 1)}
          </span>
        ) : (
          <span className="block truncate text-[11px] text-muted">
            {player.team ?? "FA"} · {describe(score, fit, currentPick).join(" · ")}
          </span>
        )}
      </span>

      {showNumbers && (
        <span className="hidden w-16 shrink-0 text-right lg:block">
          <span className="block text-xs tabular-nums text-slate-300">
            {adpDelta === null ? "—" : signed(adpDelta, 0)}
          </span>
          <span className="block text-[10px] text-muted">vs ADP</span>
        </span>
      )}

      <span
        className={`w-12 shrink-0 rounded border py-0.5 text-center ${confidenceTone(
          score.confidence,
        )}`}
        title="Confidence 0–100: how sure we are this pick works out at this slot, from usage, schedule, injury history and how much the experts disagree"
      >
        <span className="block text-xs font-bold leading-tight tabular-nums">
          {score.confidence.toFixed(0)}
        </span>
        <span className="block text-[8px] uppercase leading-tight opacity-70">conf</span>
      </span>

      {onDraft && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onDraft();
          }}
          className="shrink-0 rounded border border-line px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted opacity-0 transition hover:border-sky-500/50 hover:text-sky-300 group-hover:opacity-100"
        >
          Draft
        </button>
      )}
    </div>
  );
}
