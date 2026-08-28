/**
 * Everything the engine knows about one player.
 *
 * Opens instantly from the PlayerScore the list already holds. The two calls
 * that run a Monte Carlo simulation — GET /players/{id} and wait-vs-take —
 * fire in parallel behind skeletons and must never block the first paint.
 */

import { useEffect, useState } from "react";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  LeagueSettings,
  PlayerDetail,
  PlayerScore,
  Validation,
  WaitVsTake,
} from "../api/types";
import { confidenceTone, decimal, percent, signed } from "../lib/format";
import { positionStyle } from "../lib/positions";
import ClaudeReview from "./ClaudeReview";
import ConfidenceBreakdown from "./ConfidenceBreakdown";
import FitCard from "./FitCard";
import WaitVsTakeCard from "./WaitVsTakeCard";

interface Props {
  sessionId: string;
  score: PlayerScore;
  league: LeagueSettings;
  roster: Record<string, number>;
  claudeAvailable: boolean;
  playersById: Map<string, PlayerScore>;
  onClose: () => void;
  onSelectPlayer: (score: PlayerScore) => void;
  onDraft?: () => void;
}

export default function PlayerDrawer({
  sessionId,
  score,
  league,
  roster,
  claudeAvailable,
  playersById,
  onClose,
  onSelectPlayer,
  onDraft,
}: Props) {
  const playerId = score.player.player_id;
  const style = positionStyle(score.player.position);

  const [detail, setDetail] = useState<PlayerDetail | undefined>();
  const [detailError, setDetailError] = useState<string | null>(null);
  const [advice, setAdvice] = useState<WaitVsTake | undefined>();
  const [adviceError, setAdviceError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [review, setReview] = useState<Validation | undefined>();
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDetail(undefined);
    setAdvice(undefined);
    setDetailError(null);
    setAdviceError(null);
    setReview(undefined);
    setLoading(true);

    // Both calls run a simulation, so they go out together rather than in
    // sequence — the drawer is already on screen either way.
    const detailCall = api
      .getPlayerDetail(sessionId, playerId)
      .then((result) => !cancelled && setDetail(result))
      .catch((error) => {
        if (cancelled) return;
        setDetailError(
          error instanceof ApiError && error.status === 404
            ? error.message
            : "Could not load the full breakdown.",
        );
      });

    const adviceCall = api
      .getWaitVsTake(sessionId, playerId, false)
      .then((result) => !cancelled && setAdvice(result))
      .catch((error) => {
        if (cancelled) return;
        setAdviceError((error as Error).message);
      });

    void Promise.allSettled([detailCall, adviceCall]).then(
      () => !cancelled && setLoading(false),
    );

    return () => {
      cancelled = true;
    };
  }, [sessionId, playerId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function requestReview() {
    setReviewing(true);
    try {
      const result = await api.getWaitVsTake(sessionId, playerId, true);
      setAdvice(result);
      setReview(result.validation);
    } catch (error) {
      setReview({ status: "error", detail: (error as Error).message });
    } finally {
      setReviewing(false);
    }
  }

  return (
    <aside className="absolute inset-y-0 right-0 z-20 flex w-[26rem] flex-col border-l border-line bg-panel shadow-2xl shadow-black/50">
      {/* Header — everything here comes from the list, so it paints at once. */}
      <div className={`shrink-0 border-b border-l-4 border-line px-4 py-3 ${style.border}`}>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-bold text-slate-100">{score.player.name}</h2>
            <p className="text-xs text-muted">
              <span className={style.text}>{score.player.position}</span>
              {score.positional_rank ? ` ${score.positional_rank}` : ""} ·{" "}
              {score.player.team ?? "Free agent"}
              {score.player.age ? ` · age ${decimal(score.player.age, 1)}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted transition hover:bg-raised hover:text-slate-200"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="mt-3 grid grid-cols-4 gap-2 text-center">
          <Stat
            label="Confidence"
            value={score.confidence.toFixed(0)}
            className={`rounded border ${confidenceTone(score.confidence)}`}
          />
          <Stat label="VORP" value={signed(score.vorp, 0)} />
          <Stat label="Proj" value={decimal(score.projected_points, 0)} />
          <Stat label="ADP" value={decimal(score.adp, 1)} />
        </div>

        {onDraft && (
          <button
            type="button"
            onClick={onDraft}
            className="mt-3 w-full rounded-md bg-sky-500 px-3 py-1.5 text-xs font-bold uppercase tracking-wide text-slate-950 transition hover:bg-sky-400"
          >
            Draft {score.player.name}
          </button>
        )}
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <Section title="Fits your team">
          <FitCard score={score} league={league} roster={roster} detail={detail} />
        </Section>

        <Section title="Take him or wait">
          <WaitVsTakeCard
            result={advice}
            loading={loading && !advice && !adviceError}
            error={adviceError}
            playersById={playersById}
            onSelectAlternative={(id) => {
              const next = playersById.get(id);
              if (next) onSelectPlayer(next);
            }}
          />
          <div className="mt-3">
            <ClaudeReview
              validation={review}
              onRequest={requestReview}
              requesting={reviewing}
              available={claudeAvailable}
              label="Ask Claude about this pick"
            />
          </div>
        </Section>

        <Section title={`Why confidence ${score.confidence.toFixed(0)}`}>
          <ConfidenceBreakdown components={score.components} />
        </Section>

        <Section title="Signals">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <Row label="Schedule (season)" value={decimal(score.sos_season, 3)} />
            <Row label="Schedule (playoffs)" value={decimal(score.sos_playoffs, 3)} />
            <Row label="Opportunity share" value={percent(score.opportunity_share, 1)} />
            <Row label="Injury risk" value={decimal(score.injury_risk, 3)} />
            <Row label="Expert rank (ECR)" value={decimal(score.ecr, 1)} />
            <Row label="Usage trend" value={detail?.usage_trend ?? "—"} />
            <Row
              label="Expected pts/game"
              value={decimal(score.expected_ppg, 1)}
            />
            <Row
              label="Rank on usage"
              value={
                score.usage_rank
                  ? `${score.player.position}${score.usage_rank}`
                  : "—"
              }
            />
          </dl>
          {detail?.availability && (
            <p className="mt-2 text-[11px] text-muted">
              Survives to pick {detail.availability.target_pick}{" "}
              {percent(detail.availability.probability)} of the time (
              {detail.availability.method.replace(/_/g, " ")}).
            </p>
          )}
        </Section>

        {score.edge_ppg !== null && score.usage_rank !== null && (
          <Section title="Market vs. his own usage">
            <p className="text-xs leading-relaxed text-slate-300">
              The consensus has him{" "}
              <strong className="text-slate-100">
                {score.player.position}
                {score.positional_rank}
              </strong>
              . Last season&rsquo;s opportunity produced{" "}
              <strong className="text-slate-100">
                {score.player.position}
                {score.usage_rank}
              </strong>{" "}
              value —{" "}
              <span
                className={
                  score.edge_ppg > 0 ? "text-emerald-400" : "text-amber-400"
                }
              >
                {signed(score.edge_ppg, 1)} points a game
              </span>{" "}
              against what his draft price implies.
            </p>
            <p className="mt-1.5 text-[10px] leading-snug text-muted">
              Backward-looking. A player who missed time reads low here even if
              nothing is wrong with his role.
            </p>
          </Section>
        )}

        {score.notes.length > 0 && (
          <Section title="Notes">
            <ul className="space-y-1">
              {score.notes.map((note, index) => (
                <li key={index} className="text-xs leading-relaxed text-slate-300">
                  {note}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {detail?.injury_history?.length ? (
          <Section title="Injury history">
            <ul className="space-y-1 text-xs text-slate-300">
              {detail.injury_history.slice(0, 8).map((entry, index) => (
                <li key={index} className="flex justify-between gap-2">
                  <span className="truncate">
                    {String(entry.season ?? "")} {String(entry.report_primary_injury ?? entry.injury ?? "")}
                  </span>
                  <span className="shrink-0 text-muted">
                    {String(entry.games_missed ?? entry.status ?? "")}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {detailError && <p className="text-xs text-muted">{detailError}</p>}
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`px-1 py-1 ${className}`}>
      <div className="text-sm font-bold tabular-nums text-slate-100">{value}</div>
      <div className="text-[9px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="text-right tabular-nums text-slate-200">{value}</dd>
    </>
  );
}
