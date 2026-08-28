/**
 * Getting into a draft.
 *
 * The old form asked for a Sleeper *user id* — an opaque 19-digit number
 * nobody knows — and, when it could not work out your draft slot, silently
 * used slot 1. A drafter sitting at 12 then got a board computed for someone
 * else's picks, which quietly poisons replacement level and every
 * recommendation downstream. Now: username, pick your draft, confirm your slot.
 */

import { useState } from "react";

import * as api from "../api/client";
import type {
  LeagueSettings,
  ScoringPreset,
  SessionResponse,
  SleeperDraftRow,
  SleeperLookup,
} from "../api/types";

interface Props {
  onReady: (session: SessionResponse) => void;
}

const DEFAULT_ROSTER = { QB: 1, RB: 2, WR: 3, TE: 1, FLEX: 1, K: 1, DST: 1, BENCH: 6 };

export default function SetupScreen({ onReady }: Props) {
  const [mode, setMode] = useState<"sleeper" | "manual">("sleeper");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sleeper flow
  const [username, setUsername] = useState("");
  const [lookup, setLookup] = useState<SleeperLookup | null>(null);
  const [chosen, setChosen] = useState<SleeperDraftRow | null>(null);
  const [mockId, setMockId] = useState("");
  const [slot, setSlot] = useState<number | null>(null);

  // Manual flow
  const [name, setName] = useState("My League");
  const [scoring, setScoring] = useState<ScoringPreset>("ppr");
  const [teams, setTeams] = useState(12);
  const [rounds, setRounds] = useState(15);
  const [manualSlot, setManualSlot] = useState(1);
  const [superflex, setSuperflex] = useState(false);

  async function run(work: () => Promise<SessionResponse>) {
    setBusy(true);
    setError(null);
    try {
      onReady(await work());
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function findAccount() {
    setBusy(true);
    setError(null);
    setChosen(null);
    try {
      const result = await api.sleeperLookup(username.trim());
      setLookup(result);
    } catch (caught) {
      setError((caught as Error).message);
      setLookup(null);
    } finally {
      setBusy(false);
    }
  }

  /** A mock draft never appears in the account listing; look it up directly. */
  async function loadMock() {
    setBusy(true);
    setError(null);
    try {
      const preview = await api.sleeperDraftPreview(
        mockId.trim(),
        lookup?.user.user_id,
      );
      setChosen(preview);
      setSlot(preview.your_slot);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const startSleeper = () =>
    run(() =>
      api.createSession({
        sleeper_draft_id: chosen!.draft_id,
        sleeper_user_id: lookup?.user.user_id,
        my_draft_slot: slot ?? undefined,
      }),
    );

  const startManual = () =>
    run(async () => {
      const league: LeagueSettings = {
        name,
        scoring,
        custom_scoring: null,
        teams,
        roster: DEFAULT_ROSTER,
        flex_eligible: ["RB", "WR", "TE"],
        superflex,
        draft_type: "snake",
        my_draft_slot: Math.min(manualSlot, teams),
        rounds,
      };
      const created = await api.createLeague(league);
      return api.createSession({ league_id: created.league_id });
    });

  const slotCount = chosen?.teams ?? 12;

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6">
      <div className="w-full max-w-xl py-6">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">Apollo</h1>
          <p className="mt-1 text-sm text-muted">
            Draft cockpit — what to take, and why.
          </p>
        </div>

        <div className="panel overflow-hidden">
          <div className="flex border-b border-line">
            {(["sleeper", "manual"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setMode(option)}
                className={`flex-1 px-4 py-2.5 text-sm font-semibold transition ${
                  mode === option ? "bg-raised text-slate-100" : "text-muted hover:text-slate-300"
                }`}
              >
                {option === "sleeper" ? "Connect Sleeper" : "Manual league"}
              </button>
            ))}
          </div>

          <div className="space-y-4 p-5">
            {mode === "sleeper" ? (
              <>
                <Field label="Your Sleeper username">
                  <div className="flex gap-2">
                    <input
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      onKeyDown={(event) => event.key === "Enter" && findAccount()}
                      placeholder="e.g. bokchoy01"
                      className={inputClass}
                    />
                    <button
                      type="button"
                      onClick={findAccount}
                      disabled={busy || !username.trim()}
                      className="shrink-0 rounded-md border border-line px-3 text-sm text-slate-200 transition hover:bg-raised disabled:opacity-40"
                    >
                      {busy && !lookup ? "…" : "Find"}
                    </button>
                  </div>
                </Field>

                {lookup && (
                  <>
                    <p className="text-xs text-muted">
                      Found <span className="text-slate-200">{lookup.user.display_name}</span>.
                      Pick a draft:
                    </p>
                    <div className="space-y-1">
                      {lookup.drafts.length === 0 && (
                        <p className="text-xs text-muted">
                          No {lookup.season} drafts on this account.
                        </p>
                      )}
                      {lookup.drafts.map((draft) => (
                        <button
                          key={draft.draft_id}
                          type="button"
                          onClick={() => {
                            setChosen(draft);
                            setSlot(draft.your_slot);
                          }}
                          className={`flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left transition ${
                            chosen?.draft_id === draft.draft_id
                              ? "border-sky-500/60 bg-sky-500/10"
                              : "border-line hover:bg-raised"
                          }`}
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-slate-100">
                              {draft.name}
                            </span>
                            <span className="block text-[11px] text-muted">
                              {draft.teams}-team · {draft.rounds} rounds ·{" "}
                              {(draft.scoring ?? "ppr").toUpperCase()} · {draft.status}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>

                    <Field label="Or paste a mock draft ID (mocks aren't listed above)">
                      <div className="flex gap-2">
                        <input
                          value={mockId}
                          onChange={(event) => setMockId(event.target.value)}
                          placeholder="1398971381416259584"
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={loadMock}
                          disabled={busy || !mockId.trim()}
                          className="shrink-0 rounded-md border border-line px-3 text-sm text-slate-200 transition hover:bg-raised disabled:opacity-40"
                        >
                          Load
                        </button>
                      </div>
                    </Field>
                  </>
                )}

                {chosen && (
                  <div className="rounded-md border border-line bg-raised/40 p-3">
                    <p className="mb-2 text-xs text-slate-200">
                      <span className="font-semibold">{chosen.name}</span> —{" "}
                      {chosen.teams}-team, {chosen.rounds} rounds
                    </p>
                    <Field
                      label={
                        chosen.your_slot
                          ? "Your draft slot (from Sleeper)"
                          : "Which slot are you? Sleeper hasn't set the order yet"
                      }
                    >
                      <div className="flex flex-wrap gap-1">
                        {Array.from({ length: slotCount }, (_, index) => index + 1).map(
                          (option) => (
                            <button
                              key={option}
                              type="button"
                              onClick={() => setSlot(option)}
                              className={`h-8 w-8 rounded border text-xs font-semibold transition ${
                                slot === option
                                  ? "border-sky-500 bg-sky-500 text-slate-950"
                                  : "border-line text-slate-300 hover:bg-raised"
                              }`}
                            >
                              {option}
                            </button>
                          ),
                        )}
                      </div>
                    </Field>
                    {!slot && (
                      <p className="mt-2 text-[11px] text-amber-300">
                        Pick your slot — everything on the board depends on it, so it
                        is never guessed.
                      </p>
                    )}
                    <button
                      type="button"
                      disabled={busy || !slot}
                      onClick={startSleeper}
                      className={`${primaryClass} mt-3`}
                    >
                      {busy ? "Building the board…" : `Start from slot ${slot ?? "—"}`}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <>
                <Field label="League name">
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className={inputClass}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Scoring">
                    <select
                      value={scoring}
                      onChange={(event) => setScoring(event.target.value as ScoringPreset)}
                      className={inputClass}
                    >
                      <option value="ppr">PPR</option>
                      <option value="half_ppr">Half-PPR</option>
                      <option value="standard">Standard</option>
                    </select>
                  </Field>
                  <Field label="Teams">
                    <input
                      type="number"
                      min={2}
                      max={32}
                      value={teams}
                      onChange={(event) => setTeams(Number(event.target.value))}
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Rounds">
                    <input
                      type="number"
                      min={1}
                      max={40}
                      value={rounds}
                      onChange={(event) => setRounds(Number(event.target.value))}
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Your draft slot">
                    <input
                      type="number"
                      min={1}
                      max={teams}
                      value={manualSlot}
                      onChange={(event) => setManualSlot(Number(event.target.value))}
                      className={inputClass}
                    />
                  </Field>
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={superflex}
                    onChange={(event) => setSuperflex(event.target.checked)}
                    className="h-4 w-4 rounded border-line bg-raised"
                  />
                  Superflex
                </label>
                <button type="button" disabled={busy} onClick={startManual} className={primaryClass}>
                  {busy ? "Building the board…" : "Start drafting"}
                </button>
              </>
            )}

            {error && (
              <p className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-md border border-line bg-raised px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-muted/60 focus:border-sky-500/60";

const primaryClass =
  "w-full rounded-md bg-sky-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}
