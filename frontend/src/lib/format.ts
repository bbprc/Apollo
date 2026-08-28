/** Number and label formatting shared across the cockpit. */

import type { LeagueSettings } from "../api/types";

export const signed = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;

export const decimal = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

export const percent = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;

/** Confidence bands. Deliberately coarse — the number is already 0–100. */
export function confidenceTone(confidence: number): string {
  if (confidence >= 70) return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  if (confidence >= 55) return "bg-sky-500/15 text-sky-300 border-sky-500/30";
  if (confidence >= 40) return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  return "bg-rose-500/15 text-rose-300 border-rose-500/30";
}

export function verdictTone(verdict: string): string {
  if (verdict === "TAKE") return "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
  if (verdict === "WAIT") return "bg-amber-500/20 text-amber-300 border-amber-500/40";
  return "bg-slate-500/20 text-slate-300 border-slate-500/40";
}

const SCORING_LABEL: Record<string, string> = {
  ppr: "PPR",
  half_ppr: "Half-PPR",
  standard: "Standard",
  custom: "Custom",
};

/** "12-team PPR" — used wherever a number is phrased against the league. */
export const leagueLabel = (league: LeagueSettings): string =>
  `${league.teams}-team ${SCORING_LABEL[league.scoring] ?? league.scoring}`;

/** Human labels for the confidence components (app/scoring/confidence.py). */
export const COMPONENT_LABELS: Record<string, string> = {
  adp_value: "Value vs. ADP",
  strength_of_schedule: "Strength of schedule",
  injury_risk: "Injury risk",
  opportunity_share: "Opportunity share",
  consensus_uncertainty: "Expert disagreement",
};

export const componentLabel = (name: string): string =>
  COMPONENT_LABELS[name] ?? name.replace(/_/g, " ");

/**
 * Which overall pick number belongs to a slot in a round.
 *
 * Mirrors LeagueSettings.pick_numbers_for_slot (app/models/league.py:108) so
 * the grid lays out exactly the way the backend numbers its picks.
 */
export function pickNumber(league: LeagueSettings, round: number, slot: number): number {
  const positionInRound =
    league.draft_type === "snake" && round % 2 === 0 ? league.teams - slot + 1 : slot;
  return (round - 1) * league.teams + positionInRound;
}

/** Roster slot naming for a need, e.g. RB with 2 open -> "RB2". */
export function needLabel(position: string, league: LeagueSettings, filled: number): string {
  const starters = league.roster[position] ?? 0;
  const index = Math.min(filled + 1, Math.max(starters, 1));
  return starters > 1 ? `${position}${index}` : position;
}
