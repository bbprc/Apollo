"""Draft session state."""

from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, Field

from app.models.league import LeagueSettings


class Pick(BaseModel):
    overall: int = Field(ge=1)
    round: int = Field(ge=1)
    slot: int = Field(ge=1)
    player_id: str
    player_name: str | None = None
    position: str | None = None
    source: str = "manual"          # "manual" | "sleeper"


class Roster(BaseModel):
    """One team's haul so far, plus what it still needs."""

    slot: int
    player_ids: list[str] = Field(default_factory=list)
    positions: dict[str, int] = Field(default_factory=dict)

    def add(self, position: str | None, player_id: str) -> None:
        self.player_ids.append(player_id)
        if position:
            self.positions[position] = self.positions.get(position, 0) + 1

    def needs(self, league: LeagueSettings) -> dict[str, int]:
        """Unfilled starting slots by position, flex included.

        Flex demand is attributed to whichever eligible position is furthest
        from its own requirement, which is what a drafter actually does.
        """
        gaps: dict[str, int] = {}
        for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
            required = league.starters_at(pos)
            gaps[pos] = max(0, required - self.positions.get(pos, 0))

        flex = league.flex_slots()
        if flex > 0:
            eligible = [p for p in league.flex_eligible if p in gaps]
            if league.superflex and "QB" not in eligible:
                eligible.append("QB")
            for _ in range(flex):
                if not eligible:
                    break
                # Give the flex to whoever is thinnest relative to requirement.
                target = min(
                    eligible,
                    key=lambda p: self.positions.get(p, 0) - league.starters_at(p),
                )
                gaps[target] = gaps.get(target, 0) + 1
        return gaps


class DraftSession(BaseModel):
    session_id: str
    league: LeagueSettings
    picks: list[Pick] = Field(default_factory=list)
    sleeper_draft_id: str | None = None
    created_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))
    updated_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))

    # --- derived state -----------------------------------------------------

    @property
    def drafted_ids(self) -> set[str]:
        return {p.player_id for p in self.picks}

    @property
    def current_pick(self) -> int:
        """The overall pick number on the clock."""
        return len(self.picks) + 1

    @property
    def current_round(self) -> int:
        return (self.current_pick - 1) // self.league.teams + 1

    def is_my_pick(self) -> bool:
        return self.league.slot_on_the_clock(self.current_pick) == self.league.my_draft_slot

    def my_next_pick(self, after: int | None = None) -> int | None:
        """My next pick at or after the current one (or after a given pick)."""
        floor = after if after is not None else self.current_pick
        return next((p for p in self.league.my_picks() if p >= floor), None)

    def my_following_pick(self) -> int | None:
        """The pick after my next one — the horizon for 'should I wait?'."""
        nxt = self.my_next_pick()
        if nxt is None:
            return None
        return next((p for p in self.league.my_picks() if p > nxt), None)

    def picks_until(self, target_pick: int) -> int:
        return max(0, target_pick - self.current_pick)

    def rosters(self) -> dict[int, Roster]:
        rosters = {s: Roster(slot=s) for s in range(1, self.league.teams + 1)}
        for pick in self.picks:
            rosters[pick.slot].add(pick.position, pick.player_id)
        return rosters

    def my_roster(self) -> Roster:
        return self.rosters()[self.league.my_draft_slot]

    def add_pick(self, player_id: str, name: str | None, position: str | None,
                 source: str = "manual") -> Pick:
        overall = self.current_pick
        pick = Pick(
            overall=overall,
            round=(overall - 1) // self.league.teams + 1,
            slot=self.league.slot_on_the_clock(overall),
            player_id=player_id,
            player_name=name,
            position=position,
            source=source,
        )
        self.picks.append(pick)
        self.updated_at = _dt.datetime.now(_dt.UTC)
        return pick
