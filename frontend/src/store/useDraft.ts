/**
 * Session lifecycle, the three live queries, and the Sleeper poll loop.
 *
 * The three queries — draft state, the player pool, and the suggestion board —
 * are the only things that refetch when a pick lands. The poll itself is cheap
 * (one Sleeper call); re-scoring the board every five seconds would not be, so
 * that only happens when `current_pick` actually moves.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import * as api from "../api/client";
import { API_BASE } from "../api/client";
import type { SessionResponse, StrategyKey } from "../api/types";

const SESSION_KEY = "apollo.session";

export const queryKeys = {
  health: ["health"] as const,
  draftState: (id: string, version: string) => ["draft-state", id, version] as const,
  advice: (id: string, version: string) => ["advice-board", id, version] as const,
};

// --- session --------------------------------------------------------------

function readStored(): SessionResponse | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as SessionResponse) : null;
  } catch {
    return null;
  }
}

export function useSession() {
  const [session, setSessionState] = useState<SessionResponse | null>(readStored);
  const [restoring, setRestoring] = useState(session !== null);

  // A stored id is only trusted once the server confirms the session still
  // exists — the backend keeps sessions in SQLite, which the user may have wiped.
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    api
      .getDraftState(session.session_id)
      .then(() => !cancelled && setRestoring(false))
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem(SESSION_KEY);
        setSessionState(null);
        setRestoring(false);
      });
    return () => {
      cancelled = true;
    };
    // Deliberately mount-only: this validates the id restored from storage,
    // not every later session change.
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setSession = useCallback((next: SessionResponse | null) => {
    if (next) localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    else localStorage.removeItem(SESSION_KEY);
    setSessionState(next);
    setRestoring(false);
  }, []);

  return { session, setSession, restoring };
}

// --- queries --------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    staleTime: Infinity,
    retry: 1,
  });
}

export function useDraftState(sessionId: string | undefined, version: string) {
  return useQuery({
    queryKey: queryKeys.draftState(sessionId ?? "", version),
    queryFn: () => api.getDraftState(sessionId!),
    enabled: Boolean(sessionId),
    staleTime: Infinity,
    // Keep the previous board on screen while the next one loads, so a pick
    // landing does not blank the screen mid-draft.
    placeholderData: (previous) => previous,
  });
}

export function useAdviceBoard(
  sessionId: string | undefined,
  version: string,
  strategy: StrategyKey = "balanced",
) {
  return useQuery({
    queryKey: [...queryKeys.advice(sessionId ?? "", version), strategy],
    // 300 deep: this one response is both the recommendation and the whole
    // available list, which is what keeps the two from ever disagreeing.
    queryFn: () => api.getAdviceBoard(sessionId!, 300, false, "deep", strategy),
    enabled: Boolean(sessionId),
    staleTime: Infinity,
    placeholderData: (previous) => previous,
  });
}

/**
 * A monotonic marker for "the draft has moved".
 *
 * Everything that depends on the board is keyed on this, so a pick landing
 * produces a new cache key rather than an invalidation that has to win a race
 * against an in-flight request. That race is not theoretical: on a fresh
 * session the first sync arrives while the opening board fetch is still out,
 * and the board was left showing players who had already been drafted.
 */
export function useDataVersion() {
  const [local, setLocal] = useState(0);
  const [remotePick, setRemotePick] = useState<number | null>(null);
  return {
    version: `${remotePick ?? "-"}:${local}`,
    /** Called after a pick we made ourselves. */
    bump: useCallback(() => setLocal((n) => n + 1), []),
    /** Called from the live stream when Sleeper moves. */
    setRemotePick,
  };
}

// --- Sleeper live updates -------------------------------------------------

export interface SyncStatus {
  enabled: boolean;
  paused: boolean;
  /** SSE connection state, which is the primary transport. */
  connection: "connecting" | "live" | "reconnecting" | "off";
  lastEventAt: number | null;
  error: string | null;
  unmatched: number;
}

/**
 * A slow safety net only. The live path is the SSE stream; this exists so a
 * blocked or unsupported EventSource cannot leave the board frozen.
 */
const FALLBACK_POLL_MS = 30_000;
/** A sync that has not answered in this long is treated as failed, not pending. */
const SYNC_TIMEOUT_MS = 10_000;

export function useSleeperPoll(
  session: SessionResponse | null,
  onPick: (currentPick: number) => void,
) {
  const [paused, setPaused] = useState(false);
  const [connection, setConnection] =
    useState<SyncStatus["connection"]>("connecting");
  const [status, setStatus] = useState({
    lastEventAt: null as number | null,
    error: null as string | null,
    unmatched: 0,
  });
  const lastPick = useRef<number | null>(null);

  const enabled = Boolean(session?.sleeper_draft_id);
  const sessionId = session?.session_id;

  /** Manual/fallback sync. Times out so a hung request cannot wedge anything. */
  const syncOnce = useCallback(async () => {
    if (!sessionId) return;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), SYNC_TIMEOUT_MS);
    try {
      const result = await api.syncSleeper(sessionId, abort.signal);
      setStatus({
        lastEventAt: Date.now(),
        error: null,
        unmatched: result.unmatched.length,
      });
      if (result.current_pick !== lastPick.current) onPick(result.current_pick);
      lastPick.current = result.current_pick;
    } catch (error) {
      setStatus((prev) => ({
        ...prev,
        error:
          (error as Error)?.name === "AbortError"
            ? "sync timed out"
            : (error as Error).message,
      }));
    } finally {
      clearTimeout(timer);
    }
  }, [sessionId, onPick]);

  // The live stream. The browser throttles setInterval in hidden tabs to about
  // once a minute, and this app lives in a hidden tab while the user drafts in
  // Sleeper — so updates are pushed rather than polled.
  useEffect(() => {
    if (!enabled || !sessionId || paused) {
      setConnection(paused ? "off" : "connecting");
      return;
    }

    const source = new EventSource(
      `${API_BASE}/draft/events?session_id=${encodeURIComponent(sessionId)}`,
    );

    const onPicks = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as {
          current_pick: number;
          unmatched?: number;
        };
        setConnection("live");
        setStatus({
          lastEventAt: Date.now(),
          error: null,
          unmatched: data.unmatched ?? 0,
        });
        if (data.current_pick !== lastPick.current) {
          lastPick.current = data.current_pick;
          onPick(data.current_pick);
        }
      } catch {
        /* a malformed frame is not worth tearing the stream down for */
      }
    };

    const onSyncError = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as { detail?: string };
        setStatus((prev) => ({ ...prev, error: data.detail ?? "sync failed" }));
      } catch {
        /* ignore */
      }
    };

    source.addEventListener("open", () => setConnection("live"));
    source.addEventListener("picks", onPicks as EventListener);
    source.addEventListener("sync_error", onSyncError as EventListener);
    source.addEventListener("idle", () => setConnection("off"));
    source.onopen = () => setConnection("live");
    // EventSource reconnects on its own; surface that rather than hiding it.
    source.onerror = () => setConnection("reconnecting");

    return () => source.close();
  }, [enabled, sessionId, paused, onPick]);

  // Coming back to the tab, take nothing on trust — resync immediately.
  useEffect(() => {
    if (!enabled || paused) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void syncOnce();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [enabled, paused, syncOnce]);

  // Safety net for a blocked or failed stream.
  useEffect(() => {
    if (!enabled || paused) return;
    void syncOnce();
    const timer = setInterval(() => void syncOnce(), FALLBACK_POLL_MS);
    return () => clearInterval(timer);
  }, [enabled, paused, syncOnce]);

  return {
    status: {
      ...status,
      enabled,
      paused,
      connection: enabled ? (paused ? "off" : connection) : "off",
    } as SyncStatus,
    togglePause: () => setPaused((p) => !p),
    syncNow: syncOnce,
  };
}
