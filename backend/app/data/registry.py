"""The current-player knowledge base.

This is the structural half of the "only current players" guarantee. Nothing in
the app may name a player that is not in here: prompts are built from registry
rows, and model output is checked back against it (see :func:`unknown_names`).

Membership means the player appears on a current-season NFL roster in nflverse
*or* in Sleeper's active player list. That union is deliberate — a strict
intersection drops rookies and just-signed players that one source hasn't
picked up yet, and a missing rookie is a worse failure than a stale veteran,
whom the roster-status filter catches anyway.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from functools import lru_cache
from typing import Any, Iterable

from app.config import get_settings
from app.data import nflverse, sleeper
from app.models.player import Player, normalize_name

log = logging.getLogger(__name__)

FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K"})

#: Sleeper spells team defenses "DEF"; FantasyPros and most leagues say "DST".
POSITION_ALIASES = {"DEF": "DST", "PK": "K", "FB": "RB"}

NFL_TEAMS = (
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV "
    "MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS"
).split()


def _canon_position(raw: str | None) -> str | None:
    if not raw:
        return None
    pos = raw.strip().upper()
    return POSITION_ALIASES.get(pos, pos)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _age_from_birth_date(birth_date: Any, season: int) -> float | None:
    """Age at the start of the season, from a birth date of any usual shape."""
    if not birth_date:
        return None
    try:
        if hasattr(birth_date, "year"):
            born = birth_date
        else:
            born = _dt.date.fromisoformat(str(birth_date)[:10])
        kickoff = _dt.date(season, 9, 1)
        return round((kickoff - _dt.date(born.year, born.month, born.day)).days / 365.25, 1)
    except (ValueError, TypeError):
        return None


class PlayerRegistry:
    """An immutable snapshot of who can be drafted right now."""

    def __init__(self, players: list[Player], season: int) -> None:
        self.season = season
        self.players: dict[str, Player] = {p.player_id: p for p in players}

        self._by_name: dict[str, list[Player]] = {}
        self._by_fp_id: dict[str, Player] = {}
        self._by_sleeper_id: dict[str, Player] = {}
        self._by_gsis_id: dict[str, Player] = {}

        for player in players:
            self._by_name.setdefault(player.search_key, []).append(player)
            if player.fantasypros_id:
                self._by_fp_id[str(player.fantasypros_id)] = player
            if player.sleeper_id:
                self._by_sleeper_id[str(player.sleeper_id)] = player
            if player.gsis_id:
                self._by_gsis_id[str(player.gsis_id)] = player

        # Last name -> players, for the "Chase" / "Jefferson" shorthand people
        # actually type into a chat box.
        self._by_last: dict[str, list[Player]] = {}
        for player in players:
            parts = player.search_key.split()
            if parts:
                self._by_last.setdefault(parts[-1], []).append(player)

    # -- lookup ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.players)

    def __contains__(self, player_id: str) -> bool:
        return player_id in self.players

    def get(self, player_id: str) -> Player | None:
        return self.players.get(player_id)

    def by_fantasypros_id(self, fp_id: Any) -> Player | None:
        return self._by_fp_id.get(str(fp_id)) if fp_id is not None else None

    def by_sleeper_id(self, sleeper_id: Any) -> Player | None:
        return self._by_sleeper_id.get(str(sleeper_id)) if sleeper_id is not None else None

    def by_gsis_id(self, gsis_id: Any) -> Player | None:
        return self._by_gsis_id.get(str(gsis_id)) if gsis_id is not None else None

    def resolve(self, name: str, position: str | None = None,
                team: str | None = None) -> Player | None:
        """Find a player by name, optionally disambiguated by position/team."""
        if not name:
            return None
        candidates = self._by_name.get(normalize_name(name), [])
        if not candidates:
            key = normalize_name(name)
            if key and " " not in key:
                candidates = self._by_last.get(key, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        pos = _canon_position(position)
        narrowed = [p for p in candidates if not pos or p.position == pos]
        if team:
            by_team = [p for p in narrowed if p.team == team.upper()]
            if by_team:
                return by_team[0]
        return narrowed[0] if narrowed else candidates[0]

    def knows_name(self, name: str) -> bool:
        return self.resolve(name) is not None

    def search(self, query: str, limit: int = 10) -> list[Player]:
        """Substring search over normalized names, for chat and autocomplete."""
        key = normalize_name(query)
        if not key:
            return []
        exact = self._by_name.get(key, [])
        partial = [
            p for name, group in self._by_name.items()
            if key in name and name != key
            for p in group
        ]
        return (exact + partial)[:limit]

    def by_position(self, position: str) -> list[Player]:
        pos = _canon_position(position)
        return [p for p in self.players.values() if p.position == pos]

    # -- the output-side guardrail ----------------------------------------

    def unknown_names(self, text: str) -> list[str]:
        """Person-looking names in ``text`` that are not current players.

        The other half of the guarantee: prompts only ever carry registry rows,
        and anything the model says is checked back through here. A non-empty
        result means the response referenced somebody we cannot vouch for.

        Capitalised runs are split on stopwords first, so a sentence-initial
        word ("Consider Puka Nacua") neither masks a real name nor invents a
        fake one.
        """
        found: list[str] = []
        seen: set[str] = set()

        for match in _NAME_PATTERN.finditer(text or ""):
            for segment in _name_segments(match.group(0)):
                key = normalize_name(segment)
                if not key or key in seen:
                    continue
                seen.add(key)
                if self.knows_name(segment):
                    continue
                # A longer run may contain a real name plus trailing prose;
                # accept it if any adjacent pair inside it is a known player.
                words = segment.split()
                if len(words) > 2 and any(
                    self.knows_name(" ".join(words[i:i + 2]))
                    for i in range(len(words) - 1)
                ):
                    continue
                found.append(segment)

        # "Consider Tom Brady" and "Tom Brady" are the same finding; keep the
        # tighter one so the caller sees the name, not the sentence around it.
        keys = {normalize_name(name): name for name in found}
        return [
            name for key, name in keys.items()
            if not any(other != key and other in key.split(" ") for other in keys)
            and not any(
                other != key and f" {other} " in f" {key} " for other in keys
            )
        ]


def _name_segments(phrase: str) -> list[str]:
    """Split a capitalised run into candidate names on stopword boundaries."""
    segments: list[str] = []
    current: list[str] = []
    for word in phrase.split():
        if normalize_name(word) in _NAME_STOPWORDS:
            if len(current) >= 2:
                segments.append(" ".join(current))
            current = []
        else:
            current.append(word)
    if len(current) >= 2:
        segments.append(" ".join(current))
    return segments


#: Two or three capitalised words — the shape of a player name in prose.
_NAME_PATTERN = re.compile(r"\b[A-Z][a-zA-Z'’.-]+(?:\s+[A-Z][a-zA-Z'’.-]+){1,2}\b")

#: Words that make a capitalised phrase something other than a player name.
_NAME_STOPWORDS = frozenset(
    """
    the a an and or but if then so of to in on at for with by from
    i you he she it we they this that these those
    draft pick picks round rounds league team teams roster rosters bench flex
    ppr half standard superflex scoring points value adp ecr vorp confidence
    target share strength schedule injury injuries risk upside floor ceiling
    week weeks season seasons game games bye starter starters
    wait take waiting taking recommend recommendation because however
    consider considering avoid avoiding grab grabbing prefer preferring
    like likes target targeting start starting sit sitting stash handcuff
    trade trading add adding drop dropping expect expecting given overall
    both either neither instead also still yet meanwhile alternatively
    monday tuesday wednesday thursday friday saturday sunday
    january february march april may june july august september october
    november december
    nfl afc nfc espn yahoo sleeper fantasypros claude apollo
    quarterback runningback wide receiver tight end kicker defense
    qb rb wr te k dst def
    arizona atlanta baltimore buffalo carolina chicago cincinnati cleveland
    dallas denver detroit green bay houston indianapolis jacksonville
    kansas city las vegas los angeles miami minnesota new england new orleans
    new york philadelphia pittsburgh san francisco seattle tampa bay
    tennessee washington
    cardinals falcons ravens bills panthers bears bengals browns cowboys
    broncos lions packers texans colts jaguars chiefs raiders chargers rams
    dolphins vikings patriots saints giants jets eagles steelers niners
    seahawks buccaneers titans commanders
    """.split()
)


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------

def _index_id_map(rows: Iterable[dict[str, Any]]) -> tuple[dict, dict, dict]:
    """Crosswalk indexes: by gsis id, by sleeper id, by normalized name."""
    by_gsis: dict[str, dict] = {}
    by_sleeper: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for row in rows:
        if row.get("gsis_id"):
            by_gsis[str(row["gsis_id"])] = row
        if row.get("sleeper_id"):
            by_sleeper[str(row["sleeper_id"])] = row
        name = row.get("merge_name") or row.get("name")
        if name:
            by_name.setdefault(normalize_name(name), row)
    return by_gsis, by_sleeper, by_name


def build_registry(season: int | None = None) -> PlayerRegistry:
    """Assemble the registry from nflverse rosters and Sleeper's active list."""
    settings = get_settings()
    season = season or settings.season

    rosters = nflverse.load_rosters(season)
    bios = {r["gsis_id"]: r for r in nflverse.load_players() if r.get("gsis_id")}
    id_by_gsis, id_by_sleeper, id_by_name = _index_id_map(nflverse.load_id_map())
    sleeper_players = sleeper.load_active_players()

    players: dict[str, Player] = {}
    unmatched_fp = 0

    # --- pass 1: nflverse rosters (authoritative on who is on a team) -----
    for row in rosters:
        position = _canon_position(row.get("position") or row.get("depth_chart_position"))
        if position not in FANTASY_POSITIONS:
            continue
        status = (row.get("status") or "").upper()
        if status and status not in nflverse.DRAFTABLE_STATUSES:
            continue

        gsis_id = row.get("gsis_id")
        sleeper_id = row.get("sleeper_id")
        name = row.get("full_name") or row.get("football_name")
        if not name:
            continue

        crosswalk = (
            id_by_gsis.get(str(gsis_id))
            or id_by_sleeper.get(str(sleeper_id))
            or id_by_name.get(normalize_name(name))
            or {}
        )
        if not crosswalk.get("fantasypros_id"):
            unmatched_fp += 1

        bio = bios.get(gsis_id, {})
        age = (
            _age_from_birth_date(bio.get("birth_date") or row.get("birth_date"), season)
            or crosswalk.get("age")
        )

        player_id = str(gsis_id) if gsis_id else f"sleeper:{sleeper_id}"
        players[player_id] = Player(
            player_id=player_id,
            name=name,
            position=position,
            team=(row.get("team") or "").upper() or None,
            age=age,
            years_exp=_as_int(row.get("years_exp")),
            status=status or None,
            gsis_id=str(gsis_id) if gsis_id else None,
            sleeper_id=str(sleeper_id) if sleeper_id else None,
            fantasypros_id=(
                str(crosswalk["fantasypros_id"])
                if crosswalk.get("fantasypros_id") else None
            ),
            espn_id=str(row.get("espn_id")) if row.get("espn_id") else None,
        )

    known_sleeper_ids = {p.sleeper_id for p in players.values() if p.sleeper_id}

    # --- pass 2: Sleeper actives nflverse hasn't listed yet ---------------
    for sleeper_id, row in sleeper_players.items():
        if sleeper_id in known_sleeper_ids:
            continue
        position = _canon_position(row.get("position"))
        if position not in FANTASY_POSITIONS:
            continue
        team = (row.get("team") or "").upper()
        if not team:                       # free agents are not draftable
            continue
        name = row.get("full_name") or " ".join(
            filter(None, [row.get("first_name"), row.get("last_name")])
        )
        if not name:
            continue

        crosswalk = id_by_sleeper.get(str(sleeper_id)) or id_by_name.get(
            normalize_name(name)
        ) or {}
        gsis_id = crosswalk.get("gsis_id")
        player_id = str(gsis_id) if gsis_id else f"sleeper:{sleeper_id}"
        if player_id in players:
            continue
        players[player_id] = Player(
            player_id=player_id,
            name=name,
            position=position,
            team=team,
            age=row.get("age") or crosswalk.get("age"),
            years_exp=_as_int(row.get("years_exp")),
            status=(row.get("status") or "").upper() or None,
            gsis_id=str(gsis_id) if gsis_id else None,
            sleeper_id=str(sleeper_id),
            fantasypros_id=(
                str(crosswalk["fantasypros_id"]) if crosswalk.get("fantasypros_id") else None
            ),
            espn_id=str(row.get("espn_id")) if row.get("espn_id") else None,
        )

    # --- pass 3: team defenses, which have no roster row ------------------
    for team in NFL_TEAMS:
        players[f"dst:{team}"] = Player(
            player_id=f"dst:{team}",
            name=f"{team} Defense",
            position="DST",
            team=team,
        )

    registry = PlayerRegistry(list(players.values()), season)
    log.info(
        "registry built: %d players for %s (%d without a FantasyPros id)",
        len(registry), season, unmatched_fp,
    )
    return registry


@lru_cache(maxsize=1)
def get_registry() -> PlayerRegistry:
    """Process-wide registry singleton."""
    return build_registry()


def reset_registry() -> None:
    get_registry.cache_clear()
