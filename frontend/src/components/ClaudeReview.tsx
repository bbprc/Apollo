/**
 * Renders the `validation` block from any advice envelope.
 *
 * The backend's contract is that Claude never overrides the computed numbers,
 * so this always draws in its own bordered block, visibly apart from them.
 */

import type { Validation } from "../api/types";

interface Props {
  validation: Validation | undefined;
  /** Shown when status is "skipped" — the on-demand trigger. */
  onRequest?: () => void;
  requesting?: boolean;
  label?: string;
  /** False when the server has no ANTHROPIC_API_KEY. */
  available?: boolean;
  /** Supplied when the caller wants the read to be dismissable. */
  onDismiss?: () => void;
}

export default function ClaudeReview({
  validation,
  onRequest,
  requesting,
  label = "Get Claude's read",
  available = true,
  onDismiss,
}: Props) {
  if (!available) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-2 text-xs text-muted">
        Claude review is off — set <code className="text-slate-300">ANTHROPIC_API_KEY</code> in{" "}
        <code className="text-slate-300">backend/.env</code> and restart to switch it on.
      </div>
    );
  }

  const status = validation?.status ?? "skipped";

  if (requesting) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-xs text-violet-300">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
        Claude is reviewing the computed call…
      </div>
    );
  }

  if (status === "skipped") {
    return (
      <button
        type="button"
        onClick={onRequest}
        className="w-full rounded-md border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-xs font-semibold text-violet-300 transition hover:bg-violet-500/20"
      >
        {label}
      </button>
    );
  }

  if (status === "unavailable") {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-2 text-xs text-muted">
        {validation?.detail ?? "Claude review unavailable — no API key configured."}
      </div>
    );
  }

  if (status === "error" || status === "filtered") {
    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
        <span className="font-semibold uppercase tracking-wide">{status}</span>
        <p className="mt-1 text-amber-200/80">
          {validation?.detail ??
            (status === "filtered"
              ? "The review named players outside the current-season registry, so it was withheld."
              : "The review call failed. The computed numbers above are unaffected.")}
        </p>
        {validation?.filtered_names?.length ? (
          <p className="mt-1 text-amber-200/60">Filtered: {validation.filtered_names.join(", ")}</p>
        ) : null}
      </div>
    );
  }

  const agrees = validation?.agrees;
  return (
    <div className="rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-violet-400">
          Claude's read
        </span>
        {agrees !== undefined && (
          <span
            className={`chip ${
              agrees
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-amber-500/20 text-amber-300"
            }`}
          >
            {agrees ? "agrees" : "disagrees"}
          </span>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="ml-auto rounded px-1 text-muted transition hover:text-slate-200"
            aria-label="Dismiss this read"
            title="Dismiss"
          >
            ✕
          </button>
        )}
      </div>
      {validation?.reasoning && (
        <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{validation.reasoning}</p>
      )}
      {validation?.concerns?.length ? (
        <ul className="mt-2 space-y-1">
          {validation.concerns.map((concern, index) => (
            <li key={index} className="flex gap-1.5 text-xs text-amber-200/90">
              <span className="text-amber-500">▸</span>
              {concern}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 text-[10px] text-muted">
        Advisory only — it never changes the computed numbers above.
      </p>
    </div>
  );
}
