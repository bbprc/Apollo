/**
 * Plain-English descriptions of a player.
 *
 * Every phrase here is a restatement of a number the engine already computed —
 * nothing new is inferred. The point is that "57% opp share · 0.96 SOS · +138
 * VORP" tells you nothing under a draft clock, while "Top-5 back · Huge
 * workload · Fills your RB1" tells you what to do.
 */

import type { PlayerScore } from "../api/types";
import type { RosterFit } from "./fit";

/**
 * Usage thresholds differ by position: a 30% target share makes a receiver a
 * true alpha, while a back needs a far larger slice of his own backfield.
 */
function usagePhrase(
  share: number | null,
  position: string,
  yearsExp: number | null,
): string | null {
  // Opportunity share is only modelled for skill positions; saying a kicker
  // has "no usage history" reads as a finding when it is just a blank column.
  if (position === "K" || position === "DST") return null;
  if (share === null) {
    return yearsExp !== null && yearsExp <= 0 ? "Rookie" : "No recent usage data";
  }
  const pct = share * 100;
  if (position === "RB") {
    if (pct >= 55) return "Huge workload";
    if (pct >= 40) return "Clear lead back";
    if (pct >= 25) return "Split backfield";
    return "Committee back";
  }
  if (position === "WR" || position === "TE") {
    if (pct >= 27) return "Alpha target";
    if (pct >= 20) return "Heavy target share";
    if (pct >= 14) return "Steady role";
    return "Low target share";
  }
  if (position === "QB") return pct >= 40 ? "Runs a lot" : null;
  return null;
}

function valuePhrase(score: PlayerScore): string | null {
  const rank = score.positional_rank;
  if (!rank) return null;
  const position = score.player.position;
  // Tiering language is meaningless at kicker and defense, where the spread
  // between the best and the tenth-best is a rounding error.
  if (position === "K" || position === "DST") return `${position}${rank}`;
  if (rank <= 5) return `Top-5 ${position}`;
  if (rank <= 12) return `Top-12 ${position}`;
  return `${position}${rank}`;
}

function fitPhrase(fit: RosterFit, position: string): string {
  if (fit.kind === "starter") return `Fills your ${fit.slotLabel}`;
  if (fit.kind === "flex") return "Would fill your FLEX";
  return position === "QB" || position === "K" || position === "DST"
    ? "Backup only"
    : "Bench depth";
}

function adpPhrase(adp: number | null, currentPick: number): string | null {
  if (adp === null) return null;
  const delta = adp - currentPick;
  if (delta <= -8) return `Fallen ${Math.abs(delta).toFixed(0)} picks past ADP`;
  if (delta <= -4) return "Going later than usual";
  if (delta >= 15) return "Big reach here";
  if (delta >= 8) return "Reach here";
  return null;
}

/**
 * What his own usage produced, versus what the market charges for him.
 *
 * Deliberately phrased as history, not prophecy: it is last season's
 * opportunity, so a player who missed time reads as "down" when he was really
 * just absent.
 */
function edgePhrase(score: PlayerScore): string | null {
  if (score.edge_z === null || score.usage_rank === null) return null;
  const position = score.player.position;
  if (score.edge_z >= 1.0) return `Usage says ${position}${score.usage_rank}`;
  if (score.edge_z <= -1.0) return `Usage says only ${position}${score.usage_rank}`;
  return null;
}

function riskPhrase(score: PlayerScore): string | null {
  if (score.injury_risk === null) return null;
  if (score.injury_risk <= 0.02) return "Never missed a game";
  if (score.injury_risk >= 0.30) return "Injury risk";
  return null;
}

function schedulePhrase(sos: number | null): string | null {
  if (sos === null) return null;
  if (sos >= 1.04) return "Easy schedule";
  if (sos <= 0.96) return "Tough schedule";
  return null;
}

/**
 * Two or three phrases, ordered by how much they should move a decision:
 * what he does for your lineup, then how big his role is, then price.
 */
export function describe(
  score: PlayerScore,
  fit: RosterFit,
  currentPick: number,
  limit = 3,
): string[] {
  const candidates = [
    fitPhrase(fit, score.player.position),
    edgePhrase(score),
    usagePhrase(score.opportunity_share, score.player.position, score.player.years_exp),
    valuePhrase(score),
    adpPhrase(score.adp, currentPick),
    riskPhrase(score),
    schedulePhrase(score.sos_season),
  ];
  return candidates.filter((phrase): phrase is string => Boolean(phrase)).slice(0, limit);
}

/** One sentence for the hero card, assembled from the same material. */
export function headline(
  score: PlayerScore,
  fit: RosterFit,
  currentPick: number,
): string {
  const value = valuePhrase(score);
  const usage = usagePhrase(
    score.opportunity_share,
    score.player.position,
    score.player.years_exp,
  );
  const adp = adpPhrase(score.adp, currentPick);

  // Only the prose is lowercased; the position acronym has to stay uppercase,
  // or it reads "the top-5 te".
  const parts: string[] = [];
  if (value) parts.push(value.replace(/^Top-(\d+) /, "top-$1 "));
  if (usage) parts.push(usage.charAt(0).toLowerCase() + usage.slice(1));
  const lead = parts.length
    ? `He is the ${parts.join(", ")}.`
    : "Best player left on the board.";

  const fitLine =
    fit.kind === "starter"
      ? ` Fills your open ${fit.slotLabel}.`
      : fit.kind === "flex"
        ? " Slots into your FLEX."
        : " He would be bench depth.";

  return lead + fitLine + (adp ? ` ${adp}.` : "");
}
