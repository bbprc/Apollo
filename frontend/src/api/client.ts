/**
 * One typed function per backend endpoint.
 *
 * The backend takes `session_id` as a *query* parameter on every
 * session-scoped route, including the POST ones where a body also travels
 * (app/routers/deps.py:17). `withSession` is the single place that knows that.
 */

import type {
  AdviceBoard,
  SleeperDraftRow,
  SleeperLookup,
  StrategyKey,
  ChatResponse,
  DraftState,
  Health,
  LeagueResponse,
  LeagueSettings,
  PlayerDetail,
  PlayerListResponse,
  Envelope,
  SessionResponse,
  SessionSummary,
  SyncResponse,
  WaitVsTake,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function query(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    // FastAPI reads repeated keys as a list (e.g. ?position=RB&position=WR).
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function request<T>(
  path: string,
  init: RequestInit & { params?: Record<string, unknown> } = {},
): Promise<T> {
  const { params, ...rest } = init;
  const response = await fetch(`${API_BASE}${path}${query(params ?? {})}`, {
    ...rest,
    headers: rest.body ? { "Content-Type": "application/json", ...rest.headers } : rest.headers,
  });

  if (!response.ok) {
    // FastAPI errors are {"detail": ...}, where detail is a string or an object
    // (resolve_player_id returns {message, did_you_mean}).
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = await response.text().catch(() => "");
    }
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { message?: string })?.message ?? `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, message, detail);
  }
  return (await response.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

// --- meta -----------------------------------------------------------------

export const getHealth = () => request<Health>("/health");

export const getPresets = () =>
  request<{ scoring: Record<string, Record<string, number>>; default_roster: Record<string, number> }>(
    "/league/presets",
  );

// --- league ---------------------------------------------------------------

export const createLeague = (league: LeagueSettings) =>
  request<LeagueResponse>("/league", { method: "POST", body: json({ league }) });

// --- sessions -------------------------------------------------------------

export const createSession = (payload: {
  league_id?: string;
  sleeper_draft_id?: string;
  sleeper_user_id?: string;
  /** Required when Sleeper cannot say which slot is yours. Never defaulted. */
  my_draft_slot?: number;
}) => request<SessionResponse>("/draft/sessions", { method: "POST", body: json(payload) });

// --- sleeper account ------------------------------------------------------

export const sleeperLookup = (username: string) =>
  request<SleeperLookup>("/sleeper/lookup", { params: { username } });

export const sleeperDraftPreview = (draftId: string, userId?: string) =>
  request<SleeperDraftRow>(`/sleeper/draft/${encodeURIComponent(draftId)}`, {
    params: { user_id: userId },
  });

export const listSessions = () =>
  request<{ sessions: SessionSummary[] }>("/draft/sessions");

export const getDraftState = (sessionId: string) =>
  request<DraftState>("/draft/state", { params: { session_id: sessionId } });

export const syncSleeper = (sessionId: string, signal?: AbortSignal) =>
  request<SyncResponse>("/draft/sync", {
    method: "POST",
    params: { session_id: sessionId },
    signal,
  });

export const recordPick = (sessionId: string, playerId: string) =>
  request<SessionResponse>("/draft/picks", {
    method: "POST",
    params: { session_id: sessionId },
    body: json({ player_id: playerId }),
  });

export const undoLastPick = (sessionId: string) =>
  request<SessionResponse>("/draft/picks/last", {
    method: "DELETE",
    params: { session_id: sessionId },
  });

// --- players --------------------------------------------------------------

export const getPlayers = (sessionId: string, limit = 300) =>
  request<PlayerListResponse>("/players", { params: { session_id: sessionId, limit } });

export const getPlayerDetail = (sessionId: string, playerId: string) =>
  request<PlayerDetail>(`/players/${encodeURIComponent(playerId)}`, {
    params: { session_id: sessionId },
  });

// --- advice ---------------------------------------------------------------

/**
 * `validate` defaults to false everywhere: the Claude audit adds seconds and
 * cost, so it only runs when the user presses the button.
 */
export const getAdviceBoard = (
  sessionId: string,
  limit = 10,
  validate = false,
  depth: "quick" | "deep" = "deep",
  strategy: StrategyKey = "balanced",
) =>
  request<AdviceBoard>("/advice/board", {
    params: {
      session_id: sessionId,
      limit,
      validate_with_claude: validate,
      depth,
      strategy,
    },
  });

export const comparePlayers = (sessionId: string, playerIds: string[]) =>
  request<Envelope>("/advice/compare", {
    params: { session_id: sessionId, player_ids: playerIds },
  });

export const whatIf = (sessionId: string, playerId: string) =>
  request<Envelope>("/advice/what-if", {
    method: "POST",
    params: { session_id: sessionId },
    body: json({ player_id: playerId, horizon: 2, validate_with_claude: false }),
  });

export const getWaitVsTake = (sessionId: string, playerId: string, validate = false) =>
  request<WaitVsTake>("/advice/wait-vs-take", {
    params: { session_id: sessionId, player_id: playerId, validate_with_claude: validate },
  });

// --- chat -----------------------------------------------------------------

export const askChat = (sessionId: string, question: string, history: unknown[] = []) =>
  request<ChatResponse>("/chat", {
    method: "POST",
    params: { session_id: sessionId },
    body: json({ question, history, stream: false }),
  });
