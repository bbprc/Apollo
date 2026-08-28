/**
 * How a player fits the roster you actually have.
 *
 * The backend's `needs` map folds FLEX demand into whichever eligible position
 * is thinnest relative to its requirement, so a roster of RB4/WR6/TE1 reports
 * `{TE: 1}` even though the TE1 slot is filled — TE was simply the least
 * over-stocked. Reading that as "your TE slot is open" is wrong, and it is what
 * put a check mark next to a third-string tight end late in a draft.
 *
 * This separates the two questions the UI actually needs to answer: is a
 * dedicated starting slot open, and if not, is the flex still open?
 */

import type { LeagueSettings } from "../api/types";

export type FitKind = "starter" | "flex" | "depth";

export interface RosterFit {
  kind: FitKind;
  /** "RB2", "TE" — the specific slot he would start in, when there is one. */
  slotLabel: string;
  /** Unfilled dedicated starting slots at this position. */
  dedicatedGap: number;
  /** Flex slots still open across all eligible positions. */
  flexOpen: number;
}

const startersAt = (league: LeagueSettings, position: string): number =>
  league.roster[position] ?? 0;

/** Flex slots this league starts, superflex included. */
function flexSlots(league: LeagueSettings): number {
  const flex = league.roster.FLEX ?? 0;
  if (!league.superflex) return flex;
  return flex + (league.roster.SUPERFLEX ?? 1);
}

/**
 * Flex seats already taken — every flex-eligible player beyond his position's
 * own starting requirement is assumed to be filling one.
 */
function flexFilled(league: LeagueSettings, counts: Record<string, number>): number {
  const eligible = [...league.flex_eligible];
  if (league.superflex && !eligible.includes("QB")) eligible.push("QB");
  return eligible.reduce(
    (total, position) =>
      total + Math.max(0, (counts[position] ?? 0) - startersAt(league, position)),
    0,
  );
}

export function rosterFit(
  position: string,
  league: LeagueSettings,
  counts: Record<string, number>,
): RosterFit {
  const required = startersAt(league, position);
  const have = counts[position] ?? 0;
  const dedicatedGap = Math.max(0, required - have);
  const flexOpen = Math.max(0, flexSlots(league) - flexFilled(league, counts));

  // Name the slot he would actually start in: the next unfilled one.
  const slotLabel = required > 1 ? `${position}${Math.min(have + 1, required)}` : position;

  const eligible = [...league.flex_eligible];
  if (league.superflex && !eligible.includes("QB")) eligible.push("QB");

  let kind: FitKind = "depth";
  if (dedicatedGap > 0) kind = "starter";
  else if (flexOpen > 0 && eligible.includes(position)) kind = "flex";

  return { kind, slotLabel, dedicatedGap, flexOpen };
}

/** One sentence describing the fit, for the drawer. */
export function fitSentence(fit: RosterFit, position: string): string {
  if (fit.kind === "starter") {
    return fit.dedicatedGap > 1
      ? `Fills your open ${fit.slotLabel} slot (${fit.dedicatedGap} ${position} slots still unfilled).`
      : `Fills your open ${fit.slotLabel} slot.`;
  }
  if (fit.kind === "flex") {
    return `Would fill your FLEX — your ${position} starting slot is already set.`;
  }
  return `Depth only: your ${position} slot and your flex are both covered.`;
}
