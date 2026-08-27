"""Player identity and per-player analytics."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Player(BaseModel):
    """A player who is on an NFL roster right now.

    Instances only ever come from the registry, which is built from active
    rosters. Nothing in the app constructs a Player from a model response.
    """

    player_id: str                      # canonical id (gsis, else sleeper)
    name: str
    position: str
    team: str | None = None
    age: float | None = None
    years_exp: int | None = None
    status: str | None = None

    # cross-source ids, used to join and to reach back to a source
    gsis_id: str | None = None
    sleeper_id: str | None = None
    fantasypros_id: str | None = None
    espn_id: str | None = None

    @property
    def search_key(self) -> str:
        return normalize_name(self.name)


def normalize_name(name: str) -> str:
    """Fold a player name for matching.

    Handles the usual sources of mismatch between FantasyPros, Sleeper and
    nflverse: punctuation, suffixes, and case.
    """
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", "and")
    text = re.sub(r"[.'`’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text).strip()
    return re.sub(r"\s+", " ", text)


class ScoreComponent(BaseModel):
    """One input to the confidence score, kept in both raw and z-scored form.

    Both are carried so a UI can show the human-readable number ("22.4% target
    share") next to its standardized contribution.
    """

    name: str
    raw: float | None = None
    z_score: float = 0.0
    weight: float = 0.0
    contribution: float = 0.0
    detail: str | None = None


class PlayerProjection(BaseModel):
    """League-scored projection for the season."""

    player_id: str
    projected_points: float = 0.0
    stat_line: dict[str, float] = Field(default_factory=dict)
    source: str = "unknown"


class PlayerConsensus(BaseModel):
    """What the expert field thinks — the FantasyPros half of the picture."""

    player_id: str
    ecr: float | None = None            # expert consensus rank
    adp: float | None = None
    rank_min: float | None = None
    rank_max: float | None = None
    rank_std: float | None = None
    positional_rank: int | None = None
    source: str = "unknown"

    @property
    def adp_spread(self) -> float | None:
        """Standard deviation of where this player actually goes.

        Prefers the reported expert std; falls back to a range-derived estimate
        (a normal distribution spans roughly 4 sigma across min..max).
        """
        if self.rank_std:
            return float(self.rank_std)
        if self.rank_min is not None and self.rank_max is not None:
            spread = (float(self.rank_max) - float(self.rank_min)) / 4.0
            return max(spread, 1.0)
        return None


class PlayerScore(BaseModel):
    """The full analytic picture for one player at one point in a draft."""

    player: Player
    confidence: float = Field(ge=0.0, le=100.0)
    components: list[ScoreComponent] = Field(default_factory=list)

    projected_points: float | None = None
    vorp: float | None = None
    adp: float | None = None
    ecr: float | None = None
    positional_rank: int | None = None

    sos_season: float | None = None
    sos_playoffs: float | None = None
    injury_risk: float | None = None
    opportunity_share: float | None = None

    notes: list[str] = Field(default_factory=list)

    def explain(self) -> str:
        """One-line human summary of what drove the score."""
        ranked = sorted(self.components, key=lambda c: abs(c.contribution), reverse=True)
        parts = [f"{c.name} {c.contribution:+.2f}" for c in ranked[:3]]
        return f"confidence {self.confidence:.0f} ({', '.join(parts)})"
