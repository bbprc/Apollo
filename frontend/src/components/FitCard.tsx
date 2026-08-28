/**
 * How this player fits *your* team — the roster holes he closes and what his
 * value is worth under your scoring, phrased against your league.
 */

import type { LeagueSettings, PlayerDetail, PlayerScore } from "../api/types";
import { decimal, leagueLabel, signed } from "../lib/format";
import { fitSentence, rosterFit } from "../lib/fit";

interface Props {
  score: PlayerScore;
  league: LeagueSettings;
  /** Your current roster counts by position. */
  roster: Record<string, number>;
  detail: PlayerDetail | undefined;
}

export default function FitCard({ score, league, roster, detail }: Props) {
  const position = score.player.position;
  const fit = rosterFit(position, league, roster);

  const lines: { good: boolean; text: string }[] = [];

  lines.push({
    // Flex counts as a real opening; depth does not.
    good: fit.kind !== "depth",
    text: fitSentence(fit, position),
  });

  if (score.vorp !== null) {
    lines.push({
      good: score.vorp > 0,
      text: `Worth ${signed(score.vorp, 1)} points over replacement in your ${leagueLabel(league)} league.`,
    });
  }

  if (detail?.replacement_rank != null && detail.replacement_points != null) {
    lines.push({
      good: true,
      text: `Replacement level at ${position} in this league is ${position}${detail.replacement_rank} — about ${decimal(detail.replacement_points, 0)} points.`,
    });
  }

  if (detail?.bye_week) {
    lines.push({ good: true, text: `Bye week ${detail.bye_week}.` });
  }

  return (
    <ul className="space-y-1.5">
      {lines.map((line, index) => (
        <li key={index} className="flex gap-2 text-xs leading-relaxed">
          <span className={line.good ? "text-emerald-400" : "text-amber-400"}>
            {line.good ? "✓" : "!"}
          </span>
          <span className="text-slate-300">{line.text}</span>
        </li>
      ))}
    </ul>
  );
}
