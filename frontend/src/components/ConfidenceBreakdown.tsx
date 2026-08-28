/**
 * Why the confidence number is what it is.
 *
 * One diverging bar per component, signed by `contribution` (z-score × weight),
 * with the backend's own `detail` string as the caption — this is the ranking
 * explanation straight from the engine, not a restatement of it.
 */

import type { ScoreComponent } from "../api/types";
import { componentLabel } from "../lib/format";

export default function ConfidenceBreakdown({ components }: { components: ScoreComponent[] }) {
  const ordered = [...components].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
  );
  // Scale bars against the largest contribution present, so the shape of the
  // breakdown is readable even when every component is small.
  const peak = Math.max(...ordered.map((c) => Math.abs(c.contribution)), 0.1);

  return (
    <div className="space-y-2.5">
      {ordered.map((component) => {
        const positive = component.contribution >= 0;
        const width = (Math.abs(component.contribution) / peak) * 50;
        return (
          <div key={component.name}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-slate-200">
                {componentLabel(component.name)}
              </span>
              <span
                className={`text-xs font-semibold tabular-nums ${
                  positive ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {positive ? "+" : ""}
                {component.contribution.toFixed(2)}
              </span>
            </div>

            <div className="relative mt-1 h-1.5 rounded-full bg-raised">
              <div className="absolute left-1/2 top-0 h-full w-px bg-line" />
              <div
                className={`absolute top-0 h-full rounded-full ${
                  positive ? "bg-emerald-500/70" : "bg-rose-500/70"
                }`}
                style={
                  positive
                    ? { left: "50%", width: `${width}%` }
                    : { right: "50%", width: `${width}%` }
                }
              />
            </div>

            {component.detail && (
              <p className="mt-1 text-[11px] leading-snug text-muted">{component.detail}</p>
            )}
            <p className="mt-0.5 text-[10px] text-muted/60">
              weight {(component.weight * 100).toFixed(0)}% · z {component.z_score.toFixed(2)}
            </p>
          </div>
        );
      })}
    </div>
  );
}
