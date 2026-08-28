/**
 * Hand-written mirrors of the backend's pydantic models.
 *
 * Sources, so these stay checkable against the server:
 *   app/models/player.py, app/models/league.py, app/models/draft.py,
 *   app/models/responses.py
 */

export type Position = "QB" | "RB" | "WR" | "TE" | "K" | "DST";
export type ScoringPreset = "standard" | "half_ppr" | "ppr" | "custom";

export interface Player {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  age: number | null;
  years_exp: number | null;
  status: string | null;
  gsis_id: string | null;
  sleeper_id: string | null;
  fantasypros_id: string | null;
  espn_id: string | null;
}

/** One input to the confidence score, in both raw and standardized form. */
export interface ScoreComponent {
  name: string;
  raw: number | null;
  z_score: number;
  weight: number;
  contribution: number;
  detail: string | null;
}

/** The full analytic picture for one player at one point in a draft. */
export interface PlayerScore {
  player: Player;
  confidence: number;
  components: ScoreComponent[];
  projected_points: number | null;
  vorp: number | null;
  adp: number | null;
  ecr: number | null;
  positional_rank: number | null;
  sos_season: number | null;
  sos_playoffs: number | null;
  injury_risk: number | null;
  opportunity_share: number | null;
  /** Positional tier, 1 = best. Tier breaks mark drop-offs in the value curve. */
  tier: number | null;
  /** Expected fantasy points per game from real play-by-play opportunity. */
  expected_ppg: number | null;
  /** His rank at his position on that measure, 1 = best. */
  usage_rank: number | null;
  /** Expected pts/game above the replacement player at his position. */
  expected_above_replacement: number | null;
  /** Expected pts/game minus what his draft price implies. Positive = cheap. */
  edge_ppg: number | null;
  /** That edge standardised within his position. Rank on this, show edge_ppg. */
  edge_z: number | null;
  notes: string[];
}

export interface LeagueSettings {
  name: string;
  scoring: ScoringPreset;
  custom_scoring: Record<string, number> | null;
  teams: number;
  roster: Record<string, number>;
  flex_eligible: string[];
  superflex: boolean;
  draft_type: "snake" | "linear";
  my_draft_slot: number;
  rounds: number;
}

export interface Pick {
  overall: number;
  round: number;
  slot: number;
  player_id: string;
  player_name: string | null;
  position: string | null;
  source: "manual" | "sleeper" | string;
}

/** A drafted player, as returned inside a roster. */
export interface RosterPlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  bye_week: number | null;
}

export interface RosterView {
  players: RosterPlayer[];
  positions: Record<string, number>;
  /**
   * Unfilled starting slots, with FLEX demand folded into whichever eligible
   * position is thinnest. Do NOT read this as "the POS slot is open" — see
   * `rosterFit` in lib/fit.ts, which separates dedicated slots from flex.
   */
  needs: Record<string, number>;
}

/** GET /draft/state */
export interface DraftState {
  session_id: string;
  current_pick: number;
  current_round: number;
  on_the_clock_slot: number;
  is_my_pick: boolean;
  my_draft_slot: number;
  my_next_pick: number | null;
  my_following_pick: number | null;
  my_remaining_picks: number[];
  /** Draft slot -> manager name. Absent for CPU/unclaimed slots. */
  slot_names: Record<string, string>;
  picks: Pick[];
  rosters: Record<string, RosterView>;
}

/** POST /draft/sessions, POST /draft/picks, DELETE /draft/picks/last */
export interface SessionResponse {
  session_id: string;
  league: LeagueSettings;
  sleeper_draft_id: string | null;
  current_pick: number;
  current_round: number;
  is_my_pick: boolean;
  picks_made: number;
}

/** POST /draft/sync */
export interface SyncResponse {
  synced_picks: number;
  total_remote_picks: number;
  unmatched: { pick_no: number | null; sleeper_player_id: string | null; name: string | null }[];
  current_pick: number;
  on_the_clock_slot: number;
  is_my_pick: boolean;
}

/** GET /players */
export interface PlayerListResponse {
  count: number;
  current_pick: number;
  consensus_source: string;
  players: PlayerScore[];
}

/** GET /players/{player_id} */
export interface PlayerDetail {
  score: PlayerScore;
  replacement_rank: number | null;
  replacement_points: number | null;
  injury_history: Record<string, unknown>[];
  usage_trend: string | null;
  bye_week: number | null;
  availability: {
    target_pick: number;
    probability: number;
    method: string;
    detail?: string | null;
  } | null;
}

/**
 * Claude's second-layer audit. It never overrides the computed result, so the
 * UI always renders it in its own visually separate block.
 */
export interface Validation {
  status: "ok" | "unavailable" | "skipped" | "error" | "filtered";
  agrees?: boolean;
  concerns?: string[];
  reasoning?: string;
  detail?: string;
  filtered_names?: string[];
  usage?: Record<string, unknown>;
}

/** The uniform advice envelope shared by all four advice endpoints. */
export interface Envelope<R = Record<string, unknown>, E = Record<string, unknown>> {
  recommendation: R;
  evidence: E;
  validation: Validation;
}

export interface BoardRankedEntry {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  vorp: number | null;
  /** Value over next available: what this pick gains vs. waiting a turn. */
  vona: number;
  confidence: number;
  adp: number | null;
  /** adp - current_pick. Negative = he has fallen (value); positive = a reach. */
  adp_delta: number | null;
  tier: number | null;
  projected_points: number | null;
  fills_a_need: boolean;
  /** 1 = can start him now; < 1 = bench only, given your roster. */
  startability: number;
  /** 1 = the position is in its normal draft window; < 1 = early for it. */
  timing: number;
  off_window: boolean;
}

export type AdviceBoard = Envelope<
  {
    current_pick: number;
    current_round: number;
    is_my_pick: boolean;
    ranked_by: string;
    /**
     * "gain" ranks by what you gain picking now vs. waiting. "best_available"
     * takes over once you have only enough picks left to fill your starters,
     * when every remaining pick has to fill a hole.
     */
    mode: "gain" | "best_available";
    open_starting_slots: number;
    your_picks_left: number;
    /** Two or three genuinely different ways to use this pick. */
    options: PickOption[];
    strategy: StrategyKey;
    /** Why a position is being held back right now, in plain English. */
    strategy_notes: string[];
    /** On the wheel: which of two to take first, and why. */
    pair: PickPair | null;
    /** The pick this board measures "waiting" against. */
    horizon_pick: number | null;
    top_pick: {
      player_id: string;
      name: string;
      position: string;
      vorp: number | null;
      vona: number;
      confidence: number;
      why: string;
    } | null;
    ranked: BoardRankedEntry[];
  },
  {
    your_roster: Record<string, number>;
    your_remaining_needs: Record<string, number>;
    consensus_source: string;
    replacement_ranks: Record<string, number>;
    expected_vorp_at_next_pick: Record<string, number>;
    players: PlayerScore[];
  }
>;

/** One labelled way to use the pick, with the trade-off stated. */
export type StrategyKey =
  | "balanced"
  | "hero_rb"
  | "zero_rb"
  | "robust_rb"
  | "late_qb";

export interface PickOption extends BoardRankedEntry {
  axes: ("value" | "safe" | "upside")[];
  reason: string;
}

export interface PickPair {
  now: { player_id: string; name: string; position: string };
  then: {
    player_id: string;
    name: string;
    position: string;
    probability_available: number;
  };
  note: string;
}

/** GET /sleeper/lookup */
export interface SleeperLookup {
  user: { user_id: string; username: string; display_name: string };
  season: number;
  drafts: SleeperDraftRow[];
  note: string;
}

export interface SleeperDraftRow {
  draft_id: string;
  name: string;
  status: string;
  type: string;
  scoring: string | null;
  teams: number | null;
  rounds: number | null;
  /** Null when Sleeper has not assigned draft order yet — then you must pick. */
  your_slot: number | null;
}

export type Verdict = "TAKE" | "WAIT" | "EITHER";

export interface WaitVsTakeAlternative {
  player_id: string;
  name: string;
  team: string | null;
  vorp: number | null;
  adp: number | null;
  probability_available: number;
}

export type WaitVsTake = Envelope<
  {
    player_id: string;
    player_name: string;
    position: string;
    verdict: Verdict;
    /** Expected projected points surrendered by waiting. The headline number. */
    rating_value: number;
    confidence: number;
    current_pick: number;
    next_pick: number | null;
    probability_available_next_pick: number | null;
    availability_method: string | null;
    take_value: number;
    wait_value: number;
    alternatives: WaitVsTakeAlternative[];
    reasons: string[];
  },
  { player: PlayerScore | null; alternatives: PlayerScore[]; consensus_source: string }
>;

/** POST /chat, non-streaming */
export interface ChatResponse {
  status: "ok" | "unavailable" | "filtered" | "error";
  answer: string | null;
  players_in_context: string[];
  filtered_names: string[];
  detail: string | null;
  usage: Record<string, unknown>;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** GET /health */
export interface Health {
  status: string;
  season: number;
  registry: { ready: boolean; players?: number; season?: number; error?: string };
  sources: Record<string, { configured: boolean; role: string }>;
  validation: { configured: boolean; model: string | null; note: string };
}

export interface LeagueResponse {
  league_id: string;
  league: LeagueSettings;
}

export interface SessionSummary {
  session_id: string;
  league_id?: string | null;
  sleeper_draft_id?: string | null;
  [key: string]: unknown;
}
