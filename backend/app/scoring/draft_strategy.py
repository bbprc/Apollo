"""When each position should actually come off the board.

The engine's value numbers are all *local*: VORP compares a player to
replacement, and VONA looks one turn ahead. Neither can see the cost of taking a
quarterback in round two, because that cost is not paid at your next pick - it
is paid across the whole draft, in the running back or receiver you never got.

That is the reason every published strategy guide gives for waiting on
quarterback, and it is why positional timing has to be stated explicitly rather
than derived from the numbers already here.

The windows below are the consensus for a 12-team, 1-QB, PPR league. The
reasoning, the sources, and the named strategies are written up in
``.claude/skills/fantasy-draft-strategy/SKILL.md``; this module is the machine
-readable half, and the LLM prompt is generated from it so the two cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

from app.models.league import LeagueSettings

#: Round windows are quoted for a 15-round draft and scaled to the real length.
REFERENCE_ROUNDS = 15

#: How much of a candidate's value survives per round taken too early, and the
#: floor below which it cannot fall. Suppressed, never hard-blocked: a drafter
#: who wants the player should still be able to find him.
DECAY_PER_ROUND = 0.25
FLOOR = 0.15


@dataclass(frozen=True)
class Window:
    """When a position is sensible, and who is allowed to break the rule."""

    earliest: int
    normal: tuple[int, int]
    #: Positional rank at or above which a player escapes the timing penalty.
    #:
    #: This is the subtle one, and it is a property of the *position*, not the
    #: player. Elite tight end is a real exception because tight end replacement
    #: level is dreadful - the gap from TE1 to TE12 decides weeks. Elite
    #: quarterback is not, because QB12 scores nearly what QB1 does, so the
    #: elite costs a fortune and returns very little over waiting.
    #:
    #: A generic "he's tier one" rule would let both through. That is precisely
    #: the mistake this field exists to prevent: it lets Bowers and McBride go
    #: in round two while keeping Josh Allen out.
    elite_rank: int = 0


BASE_WINDOWS: dict[str, Window] = {
    "RB": Window(earliest=1, normal=(1, 12)),
    "WR": Window(earliest=1, normal=(1, 12)),
    "TE": Window(earliest=1, normal=(7, 14), elite_rank=2),
    "QB": Window(earliest=6, normal=(6, 12), elite_rank=0),
    "DST": Window(earliest=10, normal=(13, 15)),
    "K": Window(earliest=13, normal=(15, 15)),
}


@dataclass(frozen=True)
class Profile:
    """A named approach, expressed as overrides on the base windows.

    ``dynamic`` exists because the two running-back strategies are not static
    rules: Hero RB means "one elite back, *then* receivers", so what it says
    about running backs depends on whether you already have one. A profile
    that could not see the roster could not express that.
    """

    key: str
    label: str
    blurb: str
    overrides: dict[str, Window] = field(default_factory=dict)
    dynamic: Callable[[dict[str, Window], dict[str, int]], dict[str, Window]] | None = None


PROFILES: dict[str, Profile] = {
    "balanced": Profile(
        key="balanced",
        label="Balanced",
        blurb="Best available inside the normal windows for each position.",
    ),
    "hero_rb": Profile(
        key="hero_rb",
        label="Hero RB",
        blurb=(
            "One elite back early, then receivers. The bet is that a round 2-4 "
            "receiver becomes a WR1 more often than a round 5+ back becomes an RB1."
        ),
        # The first back is free; every one after him waits, which is the whole
        # point of the strategy.
        dynamic=lambda base, roster: {
            **base,
            "RB": base["RB"] if roster.get("RB", 0) == 0
            else replace(base["RB"], earliest=5, normal=(5, 12)),
        },
    ),
    "zero_rb": Profile(
        key="zero_rb",
        label="Zero RB",
        blurb=(
            "Skip backs for the first four to six rounds and stack receivers and "
            "an elite tight end, then buy volume backs late. The bet is injury "
            "arbitrage: early backs bust and break at the highest rate."
        ),
        overrides={"RB": Window(earliest=6, normal=(6, 14))},
    ),
    "robust_rb": Profile(
        key="robust_rb",
        label="Robust RB",
        blurb=(
            "Two backs in the first two rounds to corner the scarcest volume, "
            "then fill receiver later. Doubles your injury exposure."
        ),
        # Receivers wait until the two early backs are banked.
        dynamic=lambda base, roster: {
            **base,
            "WR": base["WR"] if roster.get("RB", 0) >= 2
            else replace(base["WR"], earliest=3, normal=(3, 12)),
        },
    ),
    "late_qb": Profile(
        key="late_qb",
        label="Late-round QB",
        blurb=(
            "Be the last team without a quarterback, then take two late darts. "
            "Reigning QB1s regularly slip past round 10."
        ),
        overrides={"QB": Window(earliest=9, normal=(9, 14))},
    ),
}

DEFAULT_PROFILE = "balanced"


def _scale(round_number: int, rounds: int) -> int:
    """Move a reference-length round onto this draft's actual length."""
    if rounds == REFERENCE_ROUNDS:
        return round_number
    scaled = round(round_number * rounds / REFERENCE_ROUNDS)
    return max(1, min(rounds, scaled))


def windows_for(
    league: LeagueSettings,
    profile: str = DEFAULT_PROFILE,
    roster_counts: dict[str, int] | None = None,
) -> dict[str, Window]:
    """The windows in force for a league, after profile and format adjustments."""
    chosen = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    resolved = {**BASE_WINDOWS, **chosen.overrides}
    if chosen.dynamic:
        resolved = chosen.dynamic(resolved, roster_counts or {})

    # Superflex inverts the quarterback rule completely: you start two, so the
    # position becomes genuinely scarce and elite QBs go in the first round.
    # Leaving the 1-QB window in place here would be badly wrong.
    if league.superflex:
        resolved["QB"] = Window(earliest=1, normal=(1, 8), elite_rank=4)

    # Kicker belongs in the last round and defense in the last few, whatever the
    # draft's length - these are the two positions people waste picks on.
    rounds = league.rounds
    resolved["K"] = replace(resolved["K"], earliest=max(1, rounds - 1), normal=(rounds, rounds))
    dst_earliest = _scale(resolved["DST"].earliest, rounds)
    resolved["DST"] = replace(
        resolved["DST"],
        earliest=dst_earliest,
        normal=(max(1, rounds - 2), rounds),
    )
    for position in ("RB", "WR", "TE", "QB"):
        window = resolved[position]
        resolved[position] = replace(
            window,
            earliest=_scale(window.earliest, rounds),
            normal=(_scale(window.normal[0], rounds), _scale(window.normal[1], rounds)),
        )
    return resolved


def timing_multiplier(
    position: str,
    current_round: int,
    positional_rank: int | None,
    league: LeagueSettings,
    profile: str = DEFAULT_PROFILE,
    roster_counts: dict[str, int] | None = None,
) -> float:
    """How much of a candidate's value survives being considered this early.

    1.0 once the position is in its window, or for a player elite enough at a
    genuinely scarce position to be worth breaking the rule for. Otherwise it
    decays with how many rounds early this is.
    """
    window = windows_for(league, profile, roster_counts).get(position.upper())
    if window is None or current_round >= window.earliest:
        return 1.0
    if window.elite_rank and positional_rank and positional_rank <= window.elite_rank:
        return 1.0
    rounds_early = window.earliest - current_round
    return max(FLOOR, 1.0 - DECAY_PER_ROUND * rounds_early)


def note_for(
    position: str,
    current_round: int,
    league: LeagueSettings,
    profile: str = DEFAULT_PROFILE,
    roster_counts: dict[str, int] | None = None,
) -> str | None:
    """Plain-English reason a position is being held back, if it is."""
    window = windows_for(league, profile, roster_counts).get(position.upper())
    if window is None or current_round >= window.earliest:
        return None
    low, high = window.normal
    if position.upper() == "K":
        return "Kickers belong in the last round — anyone you take now, you could take then."
    if position.upper() == "DST":
        return f"Defenses normally go round {window.earliest} at the earliest."
    return (
        f"{position.upper()}s normally go rounds {low}-{high}. Taking one in round "
        f"{current_round} costs you a starter at a position that is scarcer."
    )


def prompt_block(league: LeagueSettings, profile: str = DEFAULT_PROFILE) -> str:
    """The same rules, rendered for the model's system prompt.

    Generated rather than written out so the audit layer and the engine can
    never disagree about what the windows are.
    """
    resolved = windows_for(league, profile)
    chosen = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    lines = [
        "POSITIONAL TIMING. Draft-community consensus for this league's format, "
        "which the engine applies as a penalty on candidates considered too "
        "early. It is not derived from the numbers above: VORP and VONA are "
        "local measures and cannot see that taking a quarterback in round two "
        "costs a starting running back or receiver across the whole draft.",
        "",
        f"Strategy in force: {chosen.label} — {chosen.blurb}",
        "",
    ]
    for position in ("RB", "WR", "TE", "QB", "DST", "K"):
        window = resolved[position]
        low, high = window.normal
        line = f"- {position}: normally rounds {low}-{high}; not before round {window.earliest}"
        if window.elite_rank:
            line += (
                f". The top {window.elite_rank} at the position may go earlier, "
                "because replacement level here is poor enough to justify it"
            )
        lines.append(line + ".")
    lines.append("")
    lines.append(
        "Quarterback and kicker are the classic traps: QB12 scores nearly what "
        "QB1 does, so an early quarterback pays a large price for a small edge. "
        "Elite tight end is a genuine exception because the gap from TE1 to TE12 "
        "is large."
    )
    return "\n".join(lines)
