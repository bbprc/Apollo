import { useCallback, useMemo, useState } from "react";

import * as api from "./api/client";
import type { PlayerScore, SessionResponse, StrategyKey } from "./api/types";
import ChatPanel from "./components/ChatPanel";
import ComparePanel from "./components/ComparePanel";
import DraftBoard from "./components/DraftBoard";
import DraftPulse from "./components/DraftPulse";
import PickCard from "./components/PickCard";
import PlayerDrawer from "./components/PlayerDrawer";
import PlayerList from "./components/PlayerList";
import RosterTab from "./components/RosterTab";
import SetupScreen from "./components/SetupScreen";
import TopBar from "./components/TopBar";
import {
  useAdviceBoard,
  useDataVersion,
  useDraftState,
  useHealth,
  useSession,
  useSleeperPoll,
} from "./store/useDraft";
import { useSelection } from "./store/useSelection";

export default function App() {
  const { session, setSession, restoring } = useSession();

  if (restoring) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted">
        Restoring your draft…
      </div>
    );
  }
  if (!session) return <SetupScreen onReady={setSession} />;

  return <Cockpit key={session.session_id} session={session} onReset={() => setSession(null)} />;
}

type Tab = "pick" | "team" | "chat";

const STRATEGY_KEY = "apollo.strategy";

function Cockpit({ session, onReset }: { session: SessionResponse; onReset: () => void }) {
  const sessionId = session.session_id;

  const [strategy, setStrategy] = useState<StrategyKey>(() => {
    try {
      return (localStorage.getItem(STRATEGY_KEY) as StrategyKey) || "balanced";
    } catch {
      return "balanced";
    }
  });

  const health = useHealth();
  const { version, bump, setRemotePick } = useDataVersion();
  const state = useDraftState(sessionId, version);
  const advice = useAdviceBoard(sessionId, version, strategy);
  const { status: sync, togglePause, syncNow } = useSleeperPoll(session, setRemotePick);
  const { selected, select, close } = useSelection();
  const [mutating, setMutating] = useState(false);
  const [tab, setTab] = useState<Tab>("pick");
  const [comparing, setComparing] = useState<string[] | null>(null);

  const league = session.league;
  const myRoster = state.data?.rosters[String(league.my_draft_slot)];
  const rosterCounts = myRoster?.positions ?? {};
  const claudeAvailable = health.data?.validation.configured ?? false;
  const manual = !session.sleeper_draft_id;

  const playersById = useMemo(() => {
    const map = new Map<string, PlayerScore>();
    advice.data?.evidence.players.forEach((score) => map.set(score.player.player_id, score));
    return map;
  }, [advice.data?.evidence.players]);

  const draftPlayer = useCallback(
    async (score: PlayerScore) => {
      setMutating(true);
      try {
        await api.recordPick(sessionId, score.player.player_id);
        close();
        bump();
      } finally {
        setMutating(false);
      }
    },
    [sessionId, close, bump],
  );

  const undo = useCallback(async () => {
    setMutating(true);
    try {
      await api.undoLastPick(sessionId);
      bump();
    } finally {
      setMutating(false);
    }
  }, [sessionId, bump]);

  const loadError = state.error ?? advice.error;
  const currentPick = state.data?.current_pick ?? 1;
  const picksAway =
    state.data?.my_next_pick != null
      ? Math.max(0, state.data.my_next_pick - currentPick)
      : null;
  const openSlots = advice.data?.recommendation.open_starting_slots ?? 0;

  return (
    <div className="flex h-full flex-col">
      <TopBar
        session={session}
        state={state.data}
        sync={sync}
        onTogglePause={togglePause}
        onSyncNow={syncNow}
        onUndo={undo}
        undoing={mutating}
        onReset={onReset}
      />

      {loadError && (
        <p className="shrink-0 border-b border-rose-500/30 bg-rose-500/10 px-4 py-1.5 text-xs text-rose-300">
          {(loadError as Error).message}
        </p>
      )}

      <div className="relative flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <DraftPulse state={state.data} />
          <DraftBoard league={league} state={state.data} />
          <PlayerList
            advice={advice.data}
            loading={advice.isLoading}
            currentPick={currentPick}
            league={league}
            rosterCounts={rosterCounts}
            selectedId={selected?.player.player_id ?? null}
            onSelect={select}
            onDraft={manual ? draftPlayer : undefined}
          />
        </main>

        {/* Right rail: the answer, your team, and somewhere to argue with it. */}
        <div className="flex w-[26rem] shrink-0 flex-col border-l border-line bg-panel">
          <div className="flex shrink-0 border-b border-line">
            {(
              [
                ["pick", "Pick"],
                ["team", openSlots > 0 ? `Team · ${openSlots} open` : "Team"],
                ["chat", "Chat"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={`flex-1 px-3 py-2 text-xs font-semibold transition ${
                  tab === key
                    ? "border-b-2 border-sky-500 text-slate-100"
                    : "text-muted hover:text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "pick" && (
            <PickCard
              sessionId={sessionId}
              advice={advice.data}
              loading={advice.isLoading}
              isMyPick={state.data?.is_my_pick ?? false}
              currentPick={currentPick}
              picksAway={picksAway}
              league={league}
              rosterCounts={rosterCounts}
              claudeAvailable={claudeAvailable}
              playersById={playersById}
              strategy={strategy}
              onStrategyChange={(next) => {
                setStrategy(next);
                try {
                  localStorage.setItem(STRATEGY_KEY, next);
                } catch {
                  /* private mode: the choice still holds for this session */
                }
              }}
              onSelect={select}
              onCompare={setComparing}
            />
          )}
          {tab === "team" && <RosterTab state={state.data} league={league} />}
          {tab === "chat" && (
            <ChatPanel
              sessionId={sessionId}
              available={claudeAvailable}
              currentPick={currentPick}
            />
          )}
        </div>

        {comparing && (
          <ComparePanel
            sessionId={sessionId}
            playerIds={comparing}
            playersById={playersById}
            onClose={() => setComparing(null)}
            onSelect={(score) => {
              setComparing(null);
              select(score);
            }}
          />
        )}

        {selected && (
          <PlayerDrawer
            sessionId={sessionId}
            score={selected}
            league={league}
            roster={rosterCounts}
            claudeAvailable={claudeAvailable}
            playersById={playersById}
            onClose={close}
            onSelectPlayer={select}
            onDraft={manual ? () => void draftPlayer(selected) : undefined}
          />
        )}
      </div>
    </div>
  );
}
