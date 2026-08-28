/**
 * The verdict: take him now, or let him ride to your next pick.
 *
 * `rating_value` is the headline — the projected points you give up by waiting.
 * It comes from a Monte Carlo simulation, so this whole card arrives late and
 * renders behind a skeleton.
 */

import type { PlayerScore, WaitVsTake } from "../api/types";
import { decimal, percent, signed, verdictTone } from "../lib/format";

interface Props {
  result: WaitVsTake | undefined;
  loading: boolean;
  error: string | null;
  onSelectAlternative?: (playerId: string) => void;
  playersById: Map<string, PlayerScore>;
}

export default function WaitVsTakeCard({
  result,
  loading,
  error,
  onSelectAlternative,
  playersById,
}: Props) {
  if (loading) {
    return (
      <div className="space-y-2">
        <div className="h-14 animate-pulse rounded bg-raised/60" />
        <div className="h-20 animate-pulse rounded bg-raised/60" />
        <p className="text-[10px] text-muted">Simulating the room to your next pick…</p>
      </div>
    );
  }

  if (error) {
    return (
      <p className="rounded-md border border-line px-3 py-2 text-xs text-muted">{error}</p>
    );
  }

  if (!result) return null;

  const call = result.recommendation;
  const survival = call.probability_available_next_pick;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span
          className={`rounded-md border px-3 py-1.5 text-sm font-bold tracking-wide ${verdictTone(
            call.verdict,
          )}`}
        >
          {call.verdict}
        </span>
        <div>
          <div className="text-lg font-bold tabular-nums leading-none text-slate-100">
            {signed(call.rating_value, 1)}
          </div>
          <div className="text-[10px] text-muted">
            projected points {call.rating_value >= 0 ? "given up by waiting" : "gained by waiting"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 rounded-md bg-raised/50 px-3 py-2 text-center">
        <Metric label="Take now" value={decimal(call.take_value, 0)} hint="VORP if you take him" />
        <Metric
          label="If you wait"
          value={decimal(call.wait_value, 0)}
          hint="expected VORP at the position next turn"
        />
        <Metric
          label={call.next_pick ? `Lasts to ${call.next_pick}` : "Last pick"}
          value={survival === null ? "—" : percent(survival)}
          hint={call.availability_method?.replace(/_/g, " ") ?? undefined}
        />
      </div>

      {call.reasons.length > 0 && (
        <ul className="space-y-1">
          {call.reasons.map((reason, index) => (
            <li key={index} className="flex gap-2 text-xs leading-relaxed text-slate-300">
              <span className="text-muted">·</span>
              {reason}
            </li>
          ))}
        </ul>
      )}

      {call.alternatives.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-muted">
            Likely still there at {call.next_pick}
          </p>
          <ul className="space-y-0.5">
            {call.alternatives.map((alternative) => {
              const known = playersById.get(alternative.player_id);
              return (
                <li key={alternative.player_id}>
                  <button
                    type="button"
                    disabled={!known || !onSelectAlternative}
                    onClick={() => onSelectAlternative?.(alternative.player_id)}
                    className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition hover:bg-raised disabled:cursor-default"
                  >
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-200">
                      {alternative.name}
                      <span className="ml-1 text-muted">{alternative.team ?? ""}</span>
                    </span>
                    <span className="text-xs tabular-nums text-slate-300">
                      {signed(alternative.vorp, 0)}
                    </span>
                    <span className="w-10 text-right text-[10px] tabular-nums text-muted">
                      {percent(alternative.probability_available)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <div className="text-sm font-semibold tabular-nums text-slate-100">{value}</div>
      <div className="text-[10px] leading-tight text-muted">{label}</div>
    </div>
  );
}
