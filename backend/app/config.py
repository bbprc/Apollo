"""Application settings.

Scoring weights live here rather than inline in the scoring modules so that the
model is tunable and auditable from one place.
"""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_season() -> int:
    """The NFL season currently in play.

    A season is labelled by the year it starts in, so anything before March
    belongs to the previous year's season.
    """
    today = _dt.date.today()
    return today.year if today.month >= 3 else today.year - 1


class ConfidenceWeights(BaseSettings):
    """Weights for the composite Draft Confidence Score.

    Each component is a z-score; the weighted sum is squashed to 0-100. Weights
    need not sum to 1 (the squash handles scale), but keeping them near 1 makes
    the relative contributions easy to read.
    """

    adp_value: float = 0.30
    strength_of_schedule: float = 0.15
    injury_risk: float = 0.20
    opportunity_share: float = 0.25
    consensus_uncertainty: float = 0.10

    # Within strength of schedule, how much the fantasy-playoff weeks matter
    # relative to the full regular season.
    playoff_sos_share: float = 0.40

    model_config = SettingsConfigDict(env_prefix="APOLLO_WEIGHT_")


class Settings(BaseSettings):
    # --- credentials -------------------------------------------------------
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    fantasypros_api_key: str | None = Field(default=None, alias="FANTASYPROS_API_KEY")

    # --- data --------------------------------------------------------------
    season: int = Field(default_factory=default_season)
    cache_dir: Path = Path(".cache")
    cache_ttl_hours: int = 12
    db_path: Path = Path("apollo.db")

    # How many prior seasons feed the injury and opportunity models.
    lookback_seasons: int = 3
    # Recent-form window for target/carry share, in games.
    recent_form_games: int = 8
    # Weeks treated as the fantasy playoffs for the secondary SOS number.
    playoff_weeks: tuple[int, ...] = (15, 16, 17)

    # --- simulation --------------------------------------------------------
    monte_carlo_runs: int = 1000
    simulation_seed: int = 20260827
    # Temperature of the ADP-weighted softmax used to pick for other teams.
    # Lower = drafters hew closer to consensus.
    adp_softmax_temperature: float = 6.0
    # VORP gap (in projected points) above which we say TAKE rather than WAIT.
    wait_vs_take_threshold: float = 8.0

    # --- llm ---------------------------------------------------------------
    model: str = "claude-opus-5"
    llm_effort: str = "high"
    #: Effort for the "quick check" button. The deep button keeps llm_effort.
    llm_effort_quick: str = "medium"
    #: Fast Mode runs the same model at up to 2.5x output speed for 2x the token
    #: price. On a two-minute draft clock that trade is worth making, and it
    #: costs nothing in quality - it is the same model at the same effort.
    llm_fast_mode: bool = True
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 120.0

    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

    model_config = SettingsConfigDict(
        env_prefix="APOLLO_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def fantasypros_enabled(self) -> bool:
        return bool(self.fantasypros_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
