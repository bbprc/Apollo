/**
 * Two or three players, side by side.
 *
 * `/advice/compare` has existed in the backend since the start and nothing has
 * ever called it. It runs the same simulation per candidate, so the survival
 * odds and verdicts are directly comparable rather than separately computed.
 */

import { useEffect, useState } from "react";

import * as api from "../api/client";
import type { Envelope, PlayerScore } from "../api/types";
import { decimal, percent, signed, verdictTone } from "../lib/format";
import { positionStyle } from "../lib/positions";

interface Props {
  sessionId: string;
  playerIds: string[];
  playersById: Map<string, PlayerScore>;
  onClose: () => void;
  onSelect: (score: PlayerScore) => void;
}

interface Candidate {
  wait_vs_take: {
    player_id: string;
    player_name: string;
    position: string;
    verdict: string;
    rating_value: number;
    next_pick: number | null;
    probability_available_next_pick: number | null;
  };
}

export default function ComparePanel({
  sessionId,
  playerIds,
  playersById,
  onClose,
  onSelect,
}: Props) {
  const [data, setData] = useState<Envelope | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .comparePlayers(sessionId, playerIds)
      .then((result) => !cancelled && setData(result))
      .catch((caught) => !cancelled && setError((caught as Error).message));
    return () => {
      cancelled = true;
    };
  }, [sessionId, playerIds]);

  const candidates = (data?.evidence.candidates as Candidate[] | undefined) ?? [];

  return (
    <div className="absolute inset-x-0 bottom-0 top-0 z-30 flex flex-col bg-ink/95 backdrop-blur">
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2.5">
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted">
          Side by side
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded p-1 text-muted transition hover:bg-raised hover:text-slate-200"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-auto p-4">
        {error ? (
          <p className="text-xs text-rose-300">{error}</p>
        ) : !data ? (
          <div className="space-y-2">
            <p className="text-xs text-muted">Simulating each option…</p>
            <div className="h-40 animate-pulse rounded bg-raised/60" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-sm">
              <tbody>
                <Row label="">
                  {candidates.map((c) => {
                    const score = playersById.get(c.wait_vs_take.player_id);
                    const style = positionStyle(c.wait_vs_take.position);
                    return (
                      <td key={c.wait_vs_take.player_id} className="px-3 pb-2 align-bottom">
                        <button
                          type="button"
                          disabled={!score}
                          onClick={() => score && onSelect(score)}
                          className="text-left"
                        >
                          <span className="block text-sm font-bold text-slate-100">
                            {c.wait_vs_take.player_name}
                          </span>
                          <span className={`text-[11px] ${style.text}`}>
                            {c.wait_vs_take.position}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </Row>

                <Row label="Verdict">
                  {candidates.map((c) => (
                    <Cell key={c.wait_vs_take.player_id}>
                      <span
                        className={`rounded border px-2 py-0.5 text-[11px] font-bold ${verdictTone(
                          c.wait_vs_take.verdict,
                        )}`}
                      >
                        {c.wait_vs_take.verdict}
                      </span>
                    </Cell>
                  ))}
                </Row>

                <Row label="Cost of waiting">
                  {candidates.map((c) => (
                    <Cell key={c.wait_vs_take.player_id}>
                      {signed(c.wait_vs_take.rating_value, 1)} pts
                    </Cell>
                  ))}
                </Row>

                <Row label={`Lasts to your next pick`}>
                  {candidates.map((c) => (
                    <Cell key={c.wait_vs_take.player_id}>
                      {percent(c.wait_vs_take.probability_available_next_pick)}
                    </Cell>
                  ))}
                </Row>

                <Row label="Expected pts/game">
                  {candidates.map((c) => {
                    const score = playersById.get(c.wait_vs_take.player_id);
                    return (
                      <Cell key={c.wait_vs_take.player_id}>
                        {decimal(score?.expected_ppg ?? null, 1)}
                      </Cell>
                    );
                  })}
                </Row>

                <Row label="Market vs usage">
                  {candidates.map((c) => {
                    const score = playersById.get(c.wait_vs_take.player_id);
                    if (!score || score.usage_rank === null) {
                      return <Cell key={c.wait_vs_take.player_id}>—</Cell>;
                    }
                    return (
                      <Cell key={c.wait_vs_take.player_id}>
                        <span
                          className={
                            (score.edge_ppg ?? 0) > 0 ? "text-emerald-400" : "text-muted"
                          }
                        >
                          {score.player.position}
                          {score.positional_rank} → {score.player.position}
                          {score.usage_rank}
                        </span>
                      </Cell>
                    );
                  })}
                </Row>

                <Row label="Confidence">
                  {candidates.map((c) => {
                    const score = playersById.get(c.wait_vs_take.player_id);
                    return (
                      <Cell key={c.wait_vs_take.player_id}>
                        {score ? score.confidence.toFixed(0) : "—"}
                      </Cell>
                    );
                  })}
                </Row>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr className="border-b border-line/50">
      <th className="w-40 py-2 pr-3 text-left align-middle text-[11px] font-medium text-muted">
        {label}
      </th>
      {children}
    </tr>
  );
}

function Cell({ children }: { children: React.ReactNode }) {
  return (
    <td className="px-3 py-2 align-middle text-xs tabular-nums text-slate-200">
      {children}
    </td>
  );
}
