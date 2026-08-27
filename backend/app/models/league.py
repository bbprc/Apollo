"""League configuration.

Replacement level, flex maths and therefore every VORP number downstream key off
this object, so it is the first thing a client must set.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Position = Literal["QB", "RB", "WR", "TE", "K", "DST"]
ScoringPreset = Literal["standard", "half_ppr", "ppr", "custom"]

#: Points per unit of each stat. Everything not listed scores zero.
#:
#: Keys are nflverse ``load_player_stats`` column names, so a stat line coming
#: off the wire can be scored without a translation table in between.
SCORING_PRESETS: dict[str, dict[str, float]] = {
    "standard": {
        "passing_yards": 0.04,
        "passing_tds": 4.0,
        "passing_interceptions": -2.0,
        "passing_2pt_conversions": 2.0,
        "rushing_yards": 0.1,
        "rushing_tds": 6.0,
        "rushing_2pt_conversions": 2.0,
        "receptions": 0.0,
        "receiving_yards": 0.1,
        "receiving_tds": 6.0,
        "receiving_2pt_conversions": 2.0,
        "fumbles_lost_total": -2.0,
        "special_teams_tds": 6.0,
        # Kicking. Most leagues pay by distance; these are the common tiers.
        "fg_made_0_19": 3.0,
        "fg_made_20_29": 3.0,
        "fg_made_30_39": 3.0,
        "fg_made_40_49": 4.0,
        "fg_made_50_59": 5.0,
        "fg_made_60_": 5.0,
        "fg_missed": -1.0,
        "pat_made": 1.0,
        "pat_missed": -1.0,
    },
}
SCORING_PRESETS["half_ppr"] = {**SCORING_PRESETS["standard"], "receptions": 0.5}
SCORING_PRESETS["ppr"] = {**SCORING_PRESETS["standard"], "receptions": 1.0}

DEFAULT_ROSTER: dict[str, int] = {
    "QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BENCH": 6,
}


class LeagueSettings(BaseModel):
    """Everything about a league that changes what a player is worth."""

    name: str = "My League"
    scoring: ScoringPreset = "ppr"
    #: Per-stat overrides layered on top of the preset. Required when
    #: ``scoring == "custom"``, optional otherwise.
    custom_scoring: dict[str, float] | None = None

    teams: int = Field(default=12, ge=2, le=32)
    roster: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_ROSTER))
    flex_eligible: list[str] = Field(default_factory=lambda: ["RB", "WR", "TE"])
    superflex: bool = False

    draft_type: Literal["snake", "linear"] = "snake"
    my_draft_slot: int = Field(default=1, ge=1)
    rounds: int = Field(default=15, ge=1, le=40)

    @model_validator(mode="after")
    def _check(self) -> "LeagueSettings":
        if self.my_draft_slot > self.teams:
            raise ValueError(
                f"my_draft_slot {self.my_draft_slot} exceeds teams {self.teams}"
            )
        if self.scoring == "custom" and not self.custom_scoring:
            raise ValueError("custom_scoring is required when scoring is 'custom'")
        return self

    def scoring_rules(self) -> dict[str, float]:
        """The resolved per-stat point values for this league.

        Presets provide the base; ``custom_scoring`` overrides individual stats.
        Every projection in the app is scored through this one dict, so changing
        the preset re-ranks the entire board with no other code path involved.
        """
        base = dict(SCORING_PRESETS.get(self.scoring, SCORING_PRESETS["ppr"]))
        if self.custom_scoring:
            base.update(self.custom_scoring)
        return base

    def starters_at(self, position: str) -> int:
        """Dedicated starting slots for a position, excluding flex."""
        return self.roster.get(position, 0)

    def flex_slots(self) -> int:
        n = self.roster.get("FLEX", 0)
        if self.superflex:
            n += self.roster.get("SUPERFLEX", 1) if "SUPERFLEX" in self.roster else 1
        return n

    def total_roster_size(self) -> int:
        return sum(self.roster.values())

    def pick_numbers_for_slot(self, slot: int) -> list[int]:
        """Overall pick numbers belonging to a draft slot, round by round."""
        picks = []
        for rnd in range(1, self.rounds + 1):
            if self.draft_type == "snake" and rnd % 2 == 0:
                position_in_round = self.teams - slot + 1
            else:
                position_in_round = slot
            picks.append((rnd - 1) * self.teams + position_in_round)
        return picks

    def my_picks(self) -> list[int]:
        return self.pick_numbers_for_slot(self.my_draft_slot)

    def slot_on_the_clock(self, overall_pick: int) -> int:
        """Which draft slot owns a given overall pick number."""
        rnd, idx = divmod(overall_pick - 1, self.teams)
        if self.draft_type == "snake" and rnd % 2 == 1:
            return self.teams - idx
        return idx + 1
