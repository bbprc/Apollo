/**
 * The two things about a draft in progress that raw rankings never tell you:
 * which position the room is emptying right now, and whether your own starters
 * are all on bye together.
 */

import { useMemo } from "react";

import type { DraftState } from "../api/types";
import { positionStyle } from "../lib/positions";

/** How many recent picks constitute "right now". */
const WINDOW = 10;
/** Share of that window one position must take before it counts as a run. */
const RUN_SHARE = 0.5;
interface Props {
  state: DraftState | undefined;
}

export default function DraftPulse({ state }: Props) {
  const run = useMemo(() => {
    const recent = (state?.picks ?? []).slice(-WINDOW);
    if (recent.length < 5) return null;
    const tally = new Map<string, number>();
    recent.forEach((pick) => {
      if (!pick.position) return;
      tally.set(pick.position, (tally.get(pick.position) ?? 0) + 1);
    });
    const [position, count] =
      [...tally.entries()].sort((a, b) => b[1] - a[1])[0] ?? [];
    if (!position || count / recent.length < RUN_SHARE) return null;
    return { position, count, of: recent.length };
  }, [state?.picks]);

  const away =
    state?.my_next_pick != null ? Math.max(0, state.my_next_pick - state.current_pick) : null;

  if (!run) return null;

  return (
    <div className="shrink-0 space-y-1 px-3 pb-2">
      {run && (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-2.5 py-1.5">
          <span className={`chip ${positionStyle(run.position).chip}`}>{run.position}</span>
          <span className="text-[11px] leading-tight text-amber-200">
            <strong>Run on {run.position}</strong> — {run.count} of the last {run.of} picks
            {away !== null && away > 0 ? `, and you are ${away} picks away` : ""}.
          </span>
        </div>
      )}

    </div>
  );
}
