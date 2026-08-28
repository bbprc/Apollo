/**
 * Ask Claude about the draft.
 *
 * The answer streams as plain chunked text (not SSE), so deltas are appended
 * straight onto the in-flight assistant turn. The backend appends a bracketed
 * warning when an answer names players outside the registry — that gets split
 * off and styled separately rather than read as part of the answer.
 */

import { useEffect, useRef, useState } from "react";

import { splitWarning, streamChat } from "../api/stream";
import type { ChatTurn } from "../api/types";

interface Message {
  role: "user" | "assistant";
  content: string;
  warning?: string | null;
  streaming?: boolean;
  failed?: boolean;
}

interface Props {
  sessionId: string;
  available: boolean;
  /** Seeded into the composer when the user clicks a suggested prompt. */
  currentPick: number;
}

const SUGGESTIONS = [
  "Who should I take here and why?",
  "Am I too thin at RB?",
  "Which of the top three has the safest floor?",
];

export default function ChatPanel({ sessionId, available, currentPick }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const handle = useRef<{ cancel: () => void } | null>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  // A stream outliving the session it was asked about would answer the wrong
  // draft, so cancel it on unmount or a session change.
  useEffect(() => () => handle.current?.cancel(), []);

  function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;

    // Only completed turns become history; the one being typed is not one yet.
    const history: ChatTurn[] = messages
      .filter((message) => !message.failed)
      .map(({ role, content }) => ({ role, content }));

    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setBusy(true);

    const patchLast = (patch: Partial<Message>) =>
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], ...patch };
        return next;
      });

    handle.current = streamChat(
      sessionId,
      trimmed,
      history,
      (delta) =>
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + delta };
          return next;
        }),
      (full) => {
        const { body, warning } = splitWarning(full);
        patchLast({ content: body, warning, streaming: false });
        setBusy(false);
      },
      (message) => {
        patchLast({ content: message, streaming: false, failed: true });
        setBusy(false);
      },
    );
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col border-t border-line">
      <div className="flex shrink-0 items-center gap-2 px-3 py-2">
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted">Ask Claude</h2>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => setMessages([])}
            className="ml-auto text-[10px] text-muted transition hover:text-slate-300"
          >
            clear
          </button>
        )}
      </div>

      <div ref={scroller} className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pb-2">
        {messages.length === 0 && (
          <div className="space-y-2 pt-1">
            <p className="text-xs leading-relaxed text-muted">
              Grounded in your board and roster at pick {currentPick}. Every player named is
              checked against the current-season registry before the answer lands.
            </p>
            {available &&
              SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => send(suggestion)}
                  className="block w-full rounded-md border border-line px-2.5 py-1.5 text-left text-xs text-slate-300 transition hover:border-sky-500/40 hover:bg-raised"
                >
                  {suggestion}
                </button>
              ))}
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index}>
            {message.role === "user" ? (
              <p className="ml-auto w-fit max-w-[90%] rounded-lg rounded-br-sm bg-sky-500/15 px-2.5 py-1.5 text-xs text-sky-100">
                {message.content}
              </p>
            ) : (
              <div
                className={`w-fit max-w-[95%] rounded-lg rounded-bl-sm px-2.5 py-1.5 text-xs leading-relaxed ${
                  message.failed
                    ? "border border-rose-500/30 bg-rose-500/10 text-rose-300"
                    : "bg-raised text-slate-200"
                }`}
              >
                <span className="whitespace-pre-wrap">{message.content}</span>
                {message.streaming && (
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
                )}
                {message.warning && (
                  <p className="mt-1.5 border-t border-amber-500/20 pt-1.5 text-[11px] text-amber-300">
                    {message.warning}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="shrink-0 border-t border-line p-2">
        {available ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              send(input);
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about the board…"
              disabled={busy}
              className="min-w-0 flex-1 rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs text-slate-100 outline-none placeholder:text-muted/60 focus:border-sky-500/60 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="rounded-md bg-sky-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-30"
            >
              {busy ? "…" : "Ask"}
            </button>
          </form>
        ) : (
          <p className="rounded-md border border-dashed border-line px-2.5 py-2 text-[11px] leading-relaxed text-muted">
            Chat needs <code className="text-slate-300">ANTHROPIC_API_KEY</code> in{" "}
            <code className="text-slate-300">backend/.env</code>. Everything else on this
            screen works without it.
          </p>
        )}
      </div>
    </section>
  );
}
