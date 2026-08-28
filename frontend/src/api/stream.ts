/**
 * Streaming chat.
 *
 * `POST /chat` with `stream: true` returns a plain chunked `text/plain` body —
 * not SSE — so the deltas are read straight off the reader and appended.
 */

import { API_BASE } from "./client";
import type { ChatTurn } from "./types";

/** The backend appends this when an answer strayed outside the registry. */
export const WARNING_MARKER = "\n\n[warning:";

export interface StreamHandle {
  cancel: () => void;
}

export function streamChat(
  sessionId: string,
  question: string,
  history: ChatTurn[],
  onDelta: (text: string) => void,
  onDone: (full: string) => void,
  onError: (message: string) => void,
): StreamHandle {
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(
        `${API_BASE}/chat?session_id=${encodeURIComponent(sessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, history, stream: true }),
          signal: controller.signal,
        },
      );

      if (!response.ok || !response.body) {
        const text = await response.text().catch(() => "");
        onError(text || `chat failed (${response.status})`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let full = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        // stream:true keeps multi-byte characters whole across chunk edges.
        const delta = decoder.decode(value, { stream: true });
        if (!delta) continue;
        full += delta;
        onDelta(delta);
      }
      full += decoder.decode();
      onDone(full);
    } catch (error) {
      if ((error as Error)?.name === "AbortError") return;
      onError((error as Error)?.message ?? "chat stream failed");
    }
  })();

  return { cancel: () => controller.abort() };
}

/** Split a finished answer into its body and the registry warning, if any. */
export function splitWarning(text: string): { body: string; warning: string | null } {
  const index = text.indexOf(WARNING_MARKER);
  if (index === -1) return { body: text, warning: null };
  return {
    body: text.slice(0, index).trimEnd(),
    warning: text.slice(index).trim().replace(/^\[|\]$/g, ""),
  };
}
