
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from itertools import combinations
from pathlib import Path
import json
import csv
import io
import hashlib
import re
import math
import os
from datetime import datetime

app = FastAPI(title="DFS Edge MLB API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SALARY_CAP = 50000
ADMIN_PASSWORD = "dfsedge_admin_2026"

BASE_DIR = Path(__file__).parent
SAMPLE_PLAYERS_PATH = BASE_DIR / "sample_players.json"
ACTIVE_SLATE_PATH = BASE_DIR / "active_slate.json"
MARKET_STATE_PATH = BASE_DIR / "market_state.json"
USERS_PATH = BASE_DIR / "users.json"
ADMIN_EMAIL = "zero2sixtygraphics@gmail.com"
DEFAULT_ADMIN_PASSWORD = "Zero2SixtyAdmin2026!"

ROSTER_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]

POOL_LIMITS = {
    "P": 22,
    "C": 16,
    "1B": 18,
    "2B": 18,
    "3B": 18,
    "SS": 18,
    "OF": 42,
}

# Reduced for performance (prevents Pro mode timeout)
MAX_COMBINATIONS_TO_CHECK = 60000

# Auto Slate Cleanup keeps large DraftKings CSV uploads usable for DFS.
# These are MVP safety caps until real confirmed-lineup/injury APIs are connected.
AUTO_CLEANUP_POSITION_LIMITS = {
    # Keep enough players to always build lineups, but still trim giant 700+ DK pools.
    # Real injury/confirmed-lineup APIs will tighten this later.
    "P": 60,
    "C": 45,
    "1B": 45,
    "2B": 45,
    "3B": 45,
    "SS": 45,
    "OF": 140,
}


BUILT_IN_SAMPLE_PLAYERS = [
    {"name": "Spencer Strider", "position": "P", "team": "ATL", "opponent": "MIA", "salary": 10800, "projection": 25.4, "ownership": 31.0},
    {"name": "Zack Wheeler", "position": "P", "team": "PHI", "opponent": "NYM", "salary": 10300, "projection": 23.7, "ownership": 24.0},
    {"name": "Logan Gilbert", "position": "P", "team": "SEA", "opponent": "OAK", "salary": 9100, "projection": 20.5, "ownership": 18.0},
    {"name": "Joe Ryan", "position": "P", "team": "MIN", "opponent": "KC", "salary": 8600, "projection": 18.9, "ownership": 13.0},
    {"name": "Value Arm", "position": "P", "team": "TB", "opponent": "BAL", "salary": 6900, "projection": 14.8, "ownership": 8.0},
    {"name": "Cheap SP2", "position": "P", "team": "SF", "opponent": "COL", "salary": 6100, "projection": 12.6, "ownership": 5.0},

    {"name": "Will Smith", "position": "C", "team": "LAD", "opponent": "COL", "salary": 4600, "projection": 9.8, "ownership": 12.0},
    {"name": "Sean Murphy", "position": "C", "team": "ATL", "opponent": "MIA", "salary": 4100, "projection": 8.7, "ownership": 9.0},
    {"name": "Value Catcher", "position": "C", "team": "SEA", "opponent": "OAK", "salary": 2900, "projection": 6.5, "ownership": 5.0},

    {"name": "Freddie Freeman", "position": "1B", "team": "LAD", "opponent": "COL", "salary": 6100, "projection": 12.4, "ownership": 21.0},
    {"name": "Matt Olson", "position": "1B", "team": "ATL", "opponent": "MIA", "salary": 5900, "projection": 11.9, "ownership": 19.0},
    {"name": "Value First Base", "position": "1B", "team": "SEA", "opponent": "OAK", "salary": 3500, "projection": 7.7, "ownership": 6.0},

    {"name": "Mookie Betts", "position": "2B", "team": "LAD", "opponent": "COL", "salary": 6500, "projection": 13.5, "ownership": 25.0},
    {"name": "Ozzie Albies", "position": "2B", "team": "ATL", "opponent": "MIA", "salary": 5400, "projection": 10.9, "ownership": 15.0},
    {"name": "Value Second Base", "position": "2B", "team": "TB", "opponent": "BAL", "salary": 3200, "projection": 7.1, "ownership": 5.0},

    {"name": "Austin Riley", "position": "3B", "team": "ATL", "opponent": "MIA", "salary": 5700, "projection": 11.5, "ownership": 17.0},
    {"name": "Max Muncy", "position": "3B", "team": "LAD", "opponent": "COL", "salary": 5100, "projection": 10.4, "ownership": 13.0},
    {"name": "Value Third Base", "position": "3B", "team": "SEA", "opponent": "OAK", "salary": 3300, "projection": 7.4, "ownership": 6.0},

    {"name": "Corey Seager", "position": "SS", "team": "TEX", "opponent": "LAA", "salary": 6000, "projection": 11.8, "ownership": 18.0},
    {"name": "Trea Turner", "position": "SS", "team": "PHI", "opponent": "NYM", "salary": 5800, "projection": 11.4, "ownership": 16.0},
    {"name": "Value Shortstop", "position": "SS", "team": "ATL", "opponent": "MIA", "salary": 3400, "projection": 7.6, "ownership": 7.0},

    {"name": "Ronald Acuna Jr.", "position": "OF", "team": "ATL", "opponent": "MIA", "salary": 6600, "projection": 13.7, "ownership": 27.0},
    {"name": "Julio Rodriguez", "position": "OF", "team": "SEA", "opponent": "OAK", "salary": 5900, "projection": 11.7, "ownership": 16.0},
    {"name": "Yordan Alvarez", "position": "OF", "team": "HOU", "opponent": "TEX", "salary": 5800, "projection": 11.6, "ownership": 15.0},
    {"name": "Teoscar Hernandez", "position": "OF", "team": "LAD", "opponent": "COL", "salary": 4800, "projection": 9.8, "ownership": 12.0},
    {"name": "Michael Harris II", "position": "OF", "team": "ATL", "opponent": "MIA", "salary": 4500, "projection": 9.2, "ownership": 10.0},
    {"name": "Value Outfielder One", "position": "OF", "team": "LAD", "opponent": "COL", "salary": 3600, "projection": 7.9, "ownership": 7.0},
    {"name": "Value Outfielder Two", "position": "OF", "team": "TB", "opponent": "BAL", "salary": 3300, "projection": 7.3, "ownership": 5.0},
    {"name": "Cheap Outfielder", "position": "OF", "team": "SEA", "opponent": "OAK", "salary": 2800, "projection": 6.4, "ownership": 3.0},
]


class OptimizeRequest(BaseModel):
    mode: str = "cash"
    locked_players: list[str] = Field(default_factory=list)
    excluded_players: list[str] = Field(default_factory=list)
    min_salary: int = 0
    max_players_per_team: int = 5
    force_qb_stack: bool = False
    force_bring_back: bool = True
    force_team_stack: bool = False
    avoid_pitcher_vs_hitter: bool = True
    randomness: int = 0


class MultiOptimizeRequest(BaseModel):
    mode: str = "cash"
    count: int = 1
    max_exposure: int = 60
    max_same_players: int = 7
    locked_players: list[str] = Field(default_factory=list)
    excluded_players: list[str] = Field(default_factory=list)
    min_salary: int = 0
    max_players_per_team: int = 5
    force_qb_stack: bool = False
    force_bring_back: bool = True
    force_team_stack: bool = False
    avoid_pitcher_vs_hitter: bool = True
    randomness: int = 0
    player_min_exposure: dict[str, int] = Field(default_factory=dict)
    player_max_exposure: dict[str, int] = Field(default_factory=dict)


class UpdatePlayerRequest(BaseModel):
    admin_password: str
    player_name: str
    projection: float
    ownership: float


class UpdatePlayerStatusRequest(BaseModel):
    admin_password: str
    player_name: str
    active: bool
    inactive_reason: str = "manual_cleanup"


class AdminPasswordRequest(BaseModel):
    admin_password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthTokenRequest(BaseModel):
    token: str


class SaveLineupRequest(BaseModel):
    token: str
    session: dict = Field(default_factory=dict)


class UpdateUserRoleRequest(BaseModel):
    admin_password: str
    email: str
    role: str


class ContestSimulationRequest(BaseModel):
    lineups: list[dict] = Field(default_factory=list)
    mode: str = "gpp"
    contest_type: str = "large_gpp"

    # Custom contest simulator inputs.
    # These make rank/ROI more realistic for cash games, single-entry GPPs,
    # and massive-field tournaments.
    contest_size: int = 5000
    field_size: int = 5000
    entry_fee: float = 5.0
    prize_pool: float = 1000.0
    top_prize: float = 1000.0
    paid_positions: int = 0
    payout_rate: float = 0.20
    payout_percent: float = 20.0
    max_entries: int = 1
    single_entry: bool = False

    count: int = 1
    locked_players: list[str] = Field(default_factory=list)
    excluded_players: list[str] = Field(default_factory=list)
    min_salary: int = 0
    max_players_per_team: int = 5
    force_qb_stack: bool = False
    force_bring_back: bool = True
    force_team_stack: bool = False
    avoid_pitcher_vs_hitter: bool = True
    randomness: int = 0


class AutoLineupBuilderRequest(BaseModel):
    contest_focus: str = "big_gpp"
    build_style: str = "balanced"
    count: int = 5
    mode: str = "gpp"
    locked_players: list[str] = Field(default_factory=list)
    excluded_players: list[str] = Field(default_factory=list)
    min_salary: int = 0
    max_exposure: int = 60
    max_same_players: int = 7
    max_players_per_team: int = 5
    force_qb_stack: bool = False
    force_bring_back: bool = True
    force_team_stack: bool = False
    avoid_pitcher_vs_hitter: bool = True
    randomness: int = 0
    player_min_exposure: dict[str, int] = Field(default_factory=dict)
    player_max_exposure: dict[str, int] = Field(default_factory=dict)
    stack_type: str = "auto"
    strategy_mode: str = "custom"


class LineupAlertsRequest(BaseModel):
    lineups: list[dict] = Field(default_factory=list)


class LateSwapRequest(BaseModel):
    lineup: dict = Field(default_factory=dict)
    started_players: list[str] = Field(default_factory=list)
    locked_players: list[str] = Field(default_factory=list)
    excluded_players: list[str] = Field(default_factory=list)
    mode: str = "gpp"
    min_salary: int = 0
    max_players_per_team: int = 5
    force_qb_stack: bool = False
    force_bring_back: bool = True
    force_team_stack: bool = False
    avoid_pitcher_vs_hitter: bool = True
    stack_type: str = "auto"
    strategy_mode: str = "custom"
    randomness: int = 0


def safe_float(value, default=0.0):
    try:
        cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        return float(cleaned) if cleaned else default
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return int(float(cleaned)) if cleaned else default
    except Exception:
        return default


def normalize_team(value):
    team = str(value or "UNK").upper().strip()
    team = team.replace("@", "").replace("VS", "").replace(" ", "")
    return team if team else "UNK"


def normalize_position(position):
    raw = str(position or "").upper().strip()

    if "/" in raw:
        parts = [p.strip() for p in raw.split("/") if p.strip()]
        for preferred in ["P", "C", "1B", "2B", "3B", "SS", "OF"]:
            if preferred in parts:
                return preferred

    if raw in ["SP", "RP", "PITCHER", "P"]:
        return "P"

    if raw in ["C", "1B", "2B", "3B", "SS", "OF"]:
        return raw

    if "1B" in raw:
        return "1B"
    if "2B" in raw:
        return "2B"
    if "3B" in raw:
        return "3B"
    if "SS" in raw:
        return "SS"
    if "OF" in raw:
        return "OF"
    if "SP" in raw or "RP" in raw:
        return "P"

    return raw


def clean_csv_row(row):
    clean = {}
    for key, value in row.items():
        if key is None:
            continue
        clean_key = str(key).strip().replace("\ufeff", "")
        clean[clean_key] = value
    return clean


def find_column(row, names):
    for name in names:
        if name in row and row[name] not in [None, ""]:
            return row[name]

    lower_map = {str(k).strip().lower(): v for k, v in row.items()}

    for name in names:
        value = lower_map.get(str(name).strip().lower())
        if value not in [None, ""]:
            return value

    return ""


def extract_name_from_name_plus_id(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", raw).strip()
    return cleaned if cleaned else raw


def extract_id_from_name_plus_id(value):
    raw = str(value or "").strip()
    match = re.search(r"\((\d+)\)\s*$", raw)
    return match.group(1) if match else ""


def extract_opponent_from_game_info(game_info, team):
    text = str(game_info or "").upper()
    team = normalize_team(team)
    if not text:
        return ""

    first_piece = text.split(" ")[0]
    normalized = first_piece.replace("@", " @ ").replace("VS", " VS ").replace("V", " V ")
    teams = re.findall(r"[A-Z]{2,3}", normalized)

    for item in teams:
        if item != team:
            return item

    return ""


def estimate_ownership_for_player(player):
    salary = safe_int(player.get("salary", 0))
    projection = safe_float(player.get("projection", 0))
    position = normalize_position(player.get("position", ""))
    value = (projection / salary) * 1000 if salary > 0 else 0

    if position == "P":
        base = 4.0
        if salary >= 10500:
            base += 20
        elif salary >= 9500:
            base += 15
        elif salary >= 8500:
            base += 10
        elif salary >= 7500:
            base += 6
        else:
            base += 2
        base += max(0, projection - 14) * 0.75
    else:
        base = 3.0
        if salary >= 6000:
            base += 16
        elif salary >= 5200:
            base += 12
        elif salary >= 4500:
            base += 8
        elif salary >= 3500:
            base += 5
        else:
            base += 2
        base += max(0, projection - 6) * 0.9
        base += max(0, value - 2.0) * 1.4

    return round(max(1.0, min(base, 38.0)), 1)




def calculate_real_ownership_projection(player):
    """
    MVP ownership projection model.

    Until a paid ownership source is connected, this estimates projected DFS ownership
    from the signals we already have: projection, salary, value, Vegas/team total,
    lineup spot, trend score, position scarcity, and risk flags.
    """
    salary = safe_int(player.get("salary", 0))
    projection = safe_float(player.get("projection", 0))
    position = normalize_position(player.get("position", ""))
    value = (projection / salary) * 1000 if salary > 0 else 0
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    trend_score = safe_float(player.get("trend_score", 50), 50)
    lineup_spot = safe_int(player.get("lineup_spot", 0), 0)
    starter_status = str(player.get("starter_status", "unknown")).lower()
    injury_status = str(player.get("injury_status", "active")).lower()
    pull_risk = str(player.get("pull_risk", "medium")).lower()
    weather_risk = str(player.get("weather_risk", "low")).lower()
    matchup_rating = str(player.get("matchup_rating", player.get("stack_matchup_rating", "neutral"))).lower()

    if position == "P":
        base = 3.0
        base += max(0, projection - 10) * 0.95
        base += max(0, salary - 6500) / 850
        if projection >= 22:
            base += 7.5
        elif projection >= 18:
            base += 4.5
        elif projection >= 14:
            base += 2.0
        if pull_risk == "low":
            base += 1.5
        elif pull_risk == "high":
            base -= 2.5
    else:
        base = 2.0
        base += max(0, projection - 4.5) * 1.05
        base += max(0, value - 1.6) * 2.25
        base += max(0, team_total - 3.8) * 2.65
        base += max(0, trend_score - 50) * 0.055
        if lineup_spot in [1, 2, 3, 4, 5]:
            base += 3.0
        elif lineup_spot in [6, 7]:
            base += 0.8
        elif lineup_spot in [8, 9]:
            base -= 1.4
        if position == "C":
            base -= 1.0

    if matchup_rating in ["elite", "great"]:
        base += 2.2
    elif matchup_rating == "good":
        base += 1.1
    elif matchup_rating in ["bad", "poor", "risky"]:
        base -= 1.5

    if starter_status in ["bench_risk", "unknown"]:
        base -= 1.75
    elif starter_status in ["confirmed", "projected"]:
        base += 1.0

    if injury_status in ["day_to_day", "questionable"]:
        base -= 2.0
    elif injury_status in ["il", "out"]:
        base = 0.5

    if weather_risk == "high":
        base -= 2.0
    elif weather_risk == "medium":
        base -= 0.75

    return round(max(0.5, min(base, 45.0)), 1)


def leverage_profile_for_player(player):
    ownership = safe_float(player.get("ownership", 10), 10)
    boosted = boosted_projection(player) if "boosted_projection" not in player else safe_float(player.get("boosted_projection", 0), 0)
    salary = safe_int(player.get("salary", 0))
    value = (boosted / salary) * 1000 if salary > 0 else 0
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    trend_score = safe_float(player.get("trend_score", 50), 50)

    # Positive leverage means projection/upside is stronger than expected popularity.
    leverage_score = (boosted * 1.8) + (value * 4.0) + max(0, team_total - 4.0) * 2.0 + max(0, trend_score - 50) * 0.05 - (ownership * 0.72)
    leverage_score = round(max(0.0, min(leverage_score, 100.0)), 1)

    chalk_score = round(max(0.0, min(100.0, ownership * 2.15 - boosted * 0.7)), 1)
    leverage_gap = round(leverage_score - chalk_score, 1)

    if leverage_score >= 72 and ownership <= 18:
        rating = "Elite leverage"
    elif leverage_score >= 58 and ownership <= 24:
        rating = "Strong leverage"
    elif chalk_score >= 62 and leverage_score < 50:
        rating = "Chalk risk"
    elif ownership >= 28:
        rating = "Popular chalk"
    else:
        rating = "Neutral"

    return {
        "projected_ownership": round(ownership, 1),
        "leverage_score": leverage_score,
        "chalk_score": chalk_score,
        "leverage_gap": leverage_gap,
        "leverage_rating": rating,
    }


def lineup_leverage_profile(lineup):
    if not lineup:
        return {
            "average_leverage_score": 0,
            "average_chalk_score": 0,
            "leverage_rating": "No lineup",
            "elite_leverage_count": 0,
            "chalk_risk_count": 0,
        }

    leverage_scores = [safe_float(p.get("leverage_score", 0), 0) for p in lineup]
    chalk_scores = [safe_float(p.get("chalk_score", 0), 0) for p in lineup]
    elite_count = len([p for p in lineup if "elite leverage" in str(p.get("leverage_rating", "")).lower() or "strong leverage" in str(p.get("leverage_rating", "")).lower()])
    chalk_count = len([p for p in lineup if "chalk" in str(p.get("leverage_rating", "")).lower()])
    avg_lev = round(sum(leverage_scores) / len(lineup), 1)
    avg_chalk = round(sum(chalk_scores) / len(lineup), 1)

    if avg_lev >= 62 and elite_count >= 3:
        rating = "Elite leverage build"
    elif avg_lev >= 52:
        rating = "Strong leverage build"
    elif chalk_count >= 4 and avg_chalk > avg_lev:
        rating = "Chalk-heavy build"
    else:
        rating = "Balanced leverage"

    return {
        "average_leverage_score": avg_lev,
        "average_chalk_score": avg_chalk,
        "leverage_rating": rating,
        "elite_leverage_count": elite_count,
        "chalk_risk_count": chalk_count,
    }


def core_play_profile_for_player(player):
    """
    Converts projection, ownership, leverage, trend, Vegas, and data-engine risk
    into a simple DFS label users can act on.
    """
    active = bool(player.get("active", True))
    projection = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    raw_projection = safe_float(player.get("projection", 0), 0)
    ownership = safe_float(player.get("ownership", 10), 10)
    leverage_score = safe_float(player.get("leverage_score", 0), 0)
    chalk_score = safe_float(player.get("chalk_score", 0), 0)
    trend_score = safe_float(player.get("trend_score", 50), 50)
    vegas_boost = safe_float(player.get("vegas_boost", 0), 0)
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    data_boost = safe_float(player.get("data_engine_boost", 0), 0)
    salary = safe_int(player.get("salary", 0), 0)
    position = normalize_position(player.get("position", ""))
    starter_status = str(player.get("starter_status", "unknown")).lower()
    injury_status = str(player.get("injury_status", "active")).lower()
    pull_risk = str(player.get("pull_risk", "medium")).lower()
    weather_risk = str(player.get("weather_risk", "low")).lower()

    value = (projection / salary) * 1000 if salary > 0 else 0

    score = 50.0
    score += min(28.0, projection * (1.15 if position == "P" else 1.55))
    score += min(18.0, leverage_score * 0.28)
    score += max(-10.0, min(10.0, (trend_score - 50) * 0.12))
    score += max(-8.0, min(8.0, vegas_boost * 1.35))
    score += max(-8.0, min(8.0, data_boost * 1.5))
    score += max(-5.0, min(7.0, (team_total - 4.2) * 2.2))
    score += min(8.0, max(0.0, value - 1.8) * 3.5)

    # Penalize bad chalk: popular players with weak leverage.
    if ownership >= 25 and leverage_score < 45:
        score -= 16.0
    elif ownership >= 20 and leverage_score < 38:
        score -= 10.0

    if chalk_score >= 65:
        score -= 8.0
    elif chalk_score >= 52 and leverage_score < 50:
        score -= 4.0

    # Risk flags.
    if not active:
        score = min(score, 12.0)
    if injury_status in ["il", "out"]:
        score = min(score, 5.0)
    elif injury_status in ["day_to_day", "questionable"]:
        score -= 12.0
    if starter_status in ["bench_risk", "not_starting", "out"]:
        score -= 12.0
    elif starter_status in ["confirmed", "projected"]:
        score += 4.0
    if pull_risk == "high":
        score -= 7.0
    elif pull_risk == "low":
        score += 2.0
    if weather_risk == "high":
        score -= 8.0
    elif weather_risk == "medium":
        score -= 3.0

    score = round(max(0.0, min(score, 100.0)), 1)

    reasons = []
    if not active:
        reasons.append("Inactive / removed from optimizer")
    if projection >= (18 if position == "P" else 9.5):
        reasons.append("Strong projection")
    if leverage_score >= 65:
        reasons.append("Strong leverage")
    if ownership <= 10 and projection >= (14 if position == "P" else 7):
        reasons.append("Low-owned upside")
    if ownership >= 25 and leverage_score < 45:
        reasons.append("Bad chalk risk")
    if trend_score >= 65:
        reasons.append("Positive trend")
    if vegas_boost > 0:
        reasons.append("Good run environment")
    if team_total >= 5.0 and position != "P":
        reasons.append("High team total")
    if injury_status in ["day_to_day", "questionable", "il", "out"]:
        reasons.append(f"Injury flag: {injury_status}")
    if weather_risk in ["medium", "high"]:
        reasons.append(f"Weather risk: {weather_risk}")

    if not active or injury_status in ["il", "out"]:
        label = "OUT / INACTIVE"
        tier = "inactive"
    elif ownership >= 25 and leverage_score < 42 and projection < (18 if position == "P" else 9):
        label = "BAD CHALK"
        tier = "bad_chalk"
    elif score >= 82 and leverage_score >= 55:
        label = "CORE PLAY"
        tier = "core"
    elif score >= 72:
        label = "STRONG PLAY"
        tier = "strong"
    elif score >= 56:
        label = "NEUTRAL"
        tier = "neutral"
    elif score >= 42:
        label = "RISKY"
        tier = "risky"
    else:
        label = "FADE"
        tier = "fade"

    if not reasons:
        reasons.append("Balanced profile")

    return {
        "core_play_score": score,
        "core_play_label": label,
        "core_play_tier": tier,
        "core_play_reasons": reasons[:5],
    }


def lineup_core_profile(lineup):
    if not lineup:
        return {
            "core_play_count": 0,
            "strong_play_count": 0,
            "fade_count": 0,
            "bad_chalk_count": 0,
            "average_core_play_score": 0,
            "lineup_core_rating": "No lineup",
        }

    core_count = len([p for p in lineup if str(p.get("core_play_tier", "")).lower() == "core"])
    strong_count = len([p for p in lineup if str(p.get("core_play_tier", "")).lower() == "strong"])
    fade_count = len([p for p in lineup if str(p.get("core_play_tier", "")).lower() in ["fade", "inactive"]])
    bad_chalk_count = len([p for p in lineup if str(p.get("core_play_tier", "")).lower() == "bad_chalk"])
    avg_score = round(sum(safe_float(p.get("core_play_score", 0), 0) for p in lineup) / len(lineup), 1)

    if core_count >= 3 and bad_chalk_count == 0 and fade_count == 0:
        rating = "Core-heavy build"
    elif core_count + strong_count >= 6 and bad_chalk_count <= 1:
        rating = "Strong player pool"
    elif bad_chalk_count >= 3:
        rating = "Bad chalk warning"
    elif fade_count >= 2:
        rating = "Risky player mix"
    else:
        rating = "Balanced build"

    return {
        "core_play_count": core_count,
        "strong_play_count": strong_count,
        "fade_count": fade_count,
        "bad_chalk_count": bad_chalk_count,
        "average_core_play_score": avg_score,
        "lineup_core_rating": rating,
    }

def convert_dk_csv_to_players(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    players = []

    for raw_row in reader:
        row = clean_csv_row(raw_row)

        name = find_column(row, ["Name", "name", "Player", "Player Name", "Nickname"])
        name_plus_id = find_column(row, ["Name + ID", "Name+ID", "Name ID"])
        player_id = find_column(row, ["ID", "Id", "id", "PlayerID", "Player Id"])

        if not name and name_plus_id:
            name = extract_name_from_name_plus_id(name_plus_id)

        if not player_id and name_plus_id:
            player_id = extract_id_from_name_plus_id(name_plus_id)

        position = find_column(row, ["Position", "Roster Position", "Pos"])
        roster_position = find_column(row, ["Roster Position", "RosterPosition"])
        if roster_position:
            normalized_roster_position = normalize_position(roster_position)
            if normalized_roster_position in ["P", "C", "1B", "2B", "3B", "SS", "OF"]:
                position = roster_position

        salary = find_column(row, ["Salary", "salary"])
        team = find_column(row, ["TeamAbbrev", "Team", "team", "TeamAbbr"])
        game_info = find_column(row, ["Game Info", "GameInfo", "Game", "Matchup"])
        opponent = find_column(row, ["Opponent", "Opp", "OPP"])
        projection = find_column(row, [
            "Projection", "Projected Points", "ProjectedPoints", "FPTS",
            "AvgPointsPerGame", "Avg Points Per Game", "AveragePointsPerGame"
        ])
        ownership = find_column(row, [
            "Ownership", "Projected Ownership", "ProjectedOwnership", "Own",
            "Own%", "Ownership %", "Projected Own", "ProjectedOwn"
        ])

        position = normalize_position(position)
        team = normalize_team(team)
        opponent = normalize_team(opponent or extract_opponent_from_game_info(game_info, team))

        if not name or position not in ["P", "C", "1B", "2B", "3B", "SS", "OF"]:
            continue

        raw_ownership = safe_float(ownership, 0.0)

        player = {
            "name": str(name).strip(),
            "position": position,
            "team": team,
            "opponent": opponent,
            "salary": safe_int(salary),
            "projection": safe_float(projection, 0.0),
            "ownership": raw_ownership,
            "ownership_estimated": False,
            "active": True,
            "inactive_reason": "",
        }

        if player_id:
            player["id"] = str(player_id).strip()

        if player["ownership"] <= 0:
            player["ownership"] = estimate_ownership_for_player(player)
            player["ownership_estimated"] = True

        if player["salary"] > 0:
            players.append(player)

    return players


def ensure_sample_players_file():
    if not SAMPLE_PLAYERS_PATH.exists():
        with open(SAMPLE_PLAYERS_PATH, "w", encoding="utf-8") as f:
            json.dump(BUILT_IN_SAMPLE_PLAYERS, f, indent=2)
        return

    try:
        with open(SAMPLE_PLAYERS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        positions = set(p.get("position") for p in existing if isinstance(p, dict))
        if not isinstance(existing, list) or len(existing) < 10 or "QB" in positions:
            with open(SAMPLE_PLAYERS_PATH, "w", encoding="utf-8") as f:
                json.dump(BUILT_IN_SAMPLE_PLAYERS, f, indent=2)
    except Exception:
        with open(SAMPLE_PLAYERS_PATH, "w", encoding="utf-8") as f:
            json.dump(BUILT_IN_SAMPLE_PLAYERS, f, indent=2)


def load_players():
    if ACTIVE_SLATE_PATH.exists():
        try:
            with open(ACTIVE_SLATE_PATH, "r", encoding="utf-8") as f:
                active_players = json.load(f)
            if isinstance(active_players, list) and len(active_players) >= 10:
                return active_players
        except Exception:
            pass

    ensure_sample_players_file()

    try:
        with open(SAMPLE_PLAYERS_PATH, "r", encoding="utf-8") as f:
            sample_players = json.load(f)
        if isinstance(sample_players, list) and len(sample_players) >= 10:
            return sample_players
    except Exception:
        pass

    return BUILT_IN_SAMPLE_PLAYERS


def save_active_slate(players):
    with open(ACTIVE_SLATE_PATH, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2)


def current_slate_source():
    if ACTIVE_SLATE_PATH.exists():
        return "imported_or_edited_slate"
    return "sample_players"


@app.on_event("startup")
def startup_setup():
    ensure_sample_players_file()
    ensure_admin_user()



# =========================
# MLB DATA ENGINE + VEGAS LAYER
# =========================
# MVP note:
# - These fields are API-ready and use deterministic estimates when real APIs are not connected.
# - Later, plug SportsDataIO/Sportradar/Odds/OpenWeather responses into these same fields.
# - The optimizer reads these fields through add_values() and projection_boost_for_player().

DATA_ENGINE_VERSION = "mlb_data_engine_v1_api_ready"

DATA_ENGINE_SOURCES = {
    "mlb_stats_api": {
        "enabled": True,
        "status": "fallback_ready",
        "purpose": "schedule, probable pitchers, game logs, player history, parks",
        "env_key": "MLB_STATS_API_KEY_NOT_REQUIRED",
    },
    "odds_api": {
        "enabled": bool(os.getenv("ODDS_API_KEY")),
        "status": "connected" if os.getenv("ODDS_API_KEY") else "not_configured",
        "purpose": "odds, game totals, implied team totals",
        "env_key": "ODDS_API_KEY",
    },
    "openweather": {
        "enabled": bool(os.getenv("OPENWEATHER_API_KEY")),
        "status": "connected" if os.getenv("OPENWEATHER_API_KEY") else "not_configured",
        "purpose": "weather, wind, delay risk",
        "env_key": "OPENWEATHER_API_KEY",
    },
    "sportsdataio": {
        "enabled": bool(os.getenv("SPORTSDATAIO_API_KEY")),
        "status": "connected" if os.getenv("SPORTSDATAIO_API_KEY") else "not_configured",
        "purpose": "injuries, confirmed lineups, starters, DFS projections, news",
        "env_key": "SPORTSDATAIO_API_KEY",
    },
    "sportradar": {
        "enabled": bool(os.getenv("SPORTRADAR_API_KEY")),
        "status": "connected" if os.getenv("SPORTRADAR_API_KEY") else "not_configured",
        "purpose": "premium injuries, lineups, real-time stats, roster status",
        "env_key": "SPORTRADAR_API_KEY",
    },
}

TEAM_TOTAL_OVERRIDES = {
    "LAD": 5.7, "ATL": 5.6, "TEX": 5.4, "HOU": 5.2, "PHI": 5.1,
    "NYY": 5.0, "BAL": 4.9, "BOS": 4.8, "CHC": 4.8, "SD": 4.7,
    "SEA": 4.6, "MIN": 4.5, "TB": 4.5, "ARI": 4.4, "MIL": 4.4,
    "NYM": 4.3, "TOR": 4.3, "SF": 4.2, "STL": 4.2, "CLE": 4.1,
    "LAA": 4.0, "DET": 3.9, "KC": 3.8, "CIN": 3.8, "MIA": 3.7,
    "WSH": 3.6, "PIT": 3.6, "COL": 3.5, "CWS": 3.4, "OAK": 3.3,
}

PARK_FACTOR_OVERRIDES = {
    "COL": {"park_factor": "Extreme Hitter", "park_boost": 1.10},
    "BOS": {"park_factor": "Hitter", "park_boost": 0.55},
    "CIN": {"park_factor": "Hitter", "park_boost": 0.45},
    "NYY": {"park_factor": "Power", "park_boost": 0.35},
    "PHI": {"park_factor": "Power", "park_boost": 0.30},
    "SF": {"park_factor": "Pitcher", "park_boost": -0.25},
    "SEA": {"park_factor": "Pitcher", "park_boost": -0.20},
    "SD": {"park_factor": "Neutral", "park_boost": 0.0},
    "MIA": {"park_factor": "Pitcher", "park_boost": -0.25},
    "OAK": {"park_factor": "Pitcher", "park_boost": -0.30},
}


def stable_bucket_for_player(player, salt="", modulo=100):
    raw = f"{player.get('name','')}|{player.get('team','')}|{player.get('opponent','')}|{player.get('position','')}|{salt}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def estimated_team_total(team):
    team = normalize_team(team)
    if team in TEAM_TOTAL_OVERRIDES:
        return TEAM_TOTAL_OVERRIDES[team]
    digest = hashlib.md5(team.encode("utf-8")).hexdigest()
    bucket = int(digest[:4], 16) % 19
    return round(3.6 + (bucket * 0.1), 1)


def matchup_rating_from_total(total, is_pitcher=False):
    if is_pitcher:
        if total <= 3.6:
            return "Elite"
        if total <= 4.1:
            return "Strong"
        if total <= 4.7:
            return "Neutral"
        return "Risky"

    if total >= 5.3:
        return "Elite"
    if total >= 4.8:
        return "Strong"
    if total >= 4.2:
        return "Neutral"
    return "Low Total"


def vegas_environment_for_player(player):
    position = normalize_position(player.get("position", ""))
    team = normalize_team(player.get("team", ""))
    opponent = normalize_team(player.get("opponent", ""))
    team_total = estimated_team_total(team)
    opponent_total = estimated_team_total(opponent) if opponent and opponent != "UNK" else 4.4

    if position == "P":
        boost = max(-0.85, min(1.25, (4.4 - opponent_total) * 0.65))
        matchup_rating = matchup_rating_from_total(opponent_total, is_pitcher=True)
        environment_note = f"Opp total {opponent_total}"
    else:
        boost = max(-0.70, min(1.35, (team_total - 4.2) * 0.55))
        matchup_rating = matchup_rating_from_total(team_total, is_pitcher=False)
        environment_note = f"Team total {team_total}"

    return {
        "team_total": round(team_total, 1),
        "opponent_total": round(opponent_total, 1),
        "matchup_rating": matchup_rating,
        "vegas_boost": round(boost, 2),
        "environment_note": environment_note,
    }


def lineup_vegas_boost(lineup):
    return round(sum(safe_float(p.get("vegas_boost", 0)) for p in lineup), 2)


def lineup_stack_team_total(lineup):
    stack = best_stack_info(lineup)
    team = stack.get("team", "")
    if not team:
        return 0.0
    return estimated_team_total(team)


def data_engine_park_info(player):
    team = normalize_team(player.get("team", ""))
    opponent = normalize_team(player.get("opponent", ""))
    park_team = team if stable_bucket_for_player(player, "home_away", 2) == 0 else opponent
    info = PARK_FACTOR_OVERRIDES.get(park_team, {"park_factor": "Neutral", "park_boost": 0.0})
    return {"park_team": park_team, "park_factor": info["park_factor"], "park_boost": round(float(info["park_boost"]), 2)}


def estimated_weather_risk(player):
    bucket = stable_bucket_for_player(player, "weather", 100)
    if bucket >= 94:
        return {"weather_risk": "High", "weather_boost": -0.65, "weather_note": "Delay/rain risk estimate"}
    if bucket >= 82:
        return {"weather_risk": "Medium", "weather_boost": -0.25, "weather_note": "Weather watch estimate"}
    if bucket <= 12:
        return {"weather_risk": "Boost", "weather_boost": 0.20, "weather_note": "Good hitting weather estimate"}
    return {"weather_risk": "Low", "weather_boost": 0.0, "weather_note": "No weather concern estimate"}


def estimated_starter_status(player):
    position = normalize_position(player.get("position", ""))
    projection = safe_float(player.get("projection", 0))
    salary = safe_int(player.get("salary", 0))
    bucket = stable_bucket_for_player(player, "starter", 100)

    if position == "P":
        if projection >= 14 or salary >= 7000:
            return "probable_pitcher"
        if bucket >= 85:
            return "long_relief_risk"
        return "pitcher_pool"

    if projection >= 7.5 or salary >= 4300:
        return "projected_starter"
    if projection >= 5.2:
        return "starter_risk"
    if bucket >= 82:
        return "bench_risk"
    return "unknown"


def estimated_injury_status(player):
    bucket = stable_bucket_for_player(player, "injury", 100)
    if bucket >= 98:
        return "watch"
    if bucket >= 94:
        return "day_to_day_risk"
    return "active_estimated"


def estimated_lineup_spot_and_abs(player):
    position = normalize_position(player.get("position", ""))
    projection = safe_float(player.get("projection", 0))
    salary = safe_int(player.get("salary", 0))
    value = player_value(player)
    bucket = stable_bucket_for_player(player, "lineup_spot", 9)

    if position == "P":
        projected_innings = 4.2
        if projection >= 22:
            projected_innings = 6.2
        elif projection >= 18:
            projected_innings = 5.8
        elif projection >= 14:
            projected_innings = 5.1
        elif salary <= 6500:
            projected_innings = 4.3
        return {"lineup_spot": None, "avg_at_bats": None, "projected_innings": round(projected_innings, 1)}

    if projection >= 10 or salary >= 5600:
        spot = 1 + (bucket % 4)
    elif projection >= 7 or value >= 2.0:
        spot = 3 + (bucket % 4)
    else:
        spot = min(9, 6 + (bucket % 4))

    avg_abs = 4.5 if spot <= 2 else 4.2 if spot <= 5 else 3.8 if spot <= 7 else 3.4
    return {"lineup_spot": spot, "avg_at_bats": round(avg_abs, 1), "projected_innings": None}


def estimated_pull_risk(player, starter_status, injury_status):
    position = normalize_position(player.get("position", ""))
    projection = safe_float(player.get("projection", 0))
    salary = safe_int(player.get("salary", 0))

    if "day_to_day" in injury_status or injury_status == "watch":
        return "High"
    if position == "P":
        if salary <= 6500 or projection < 12:
            return "High"
        if salary <= 8000 or projection < 17:
            return "Medium"
        return "Low"
    if starter_status in ["bench_risk", "starter_risk"]:
        return "Medium"
    if projection < 4.5:
        return "Medium"
    return "Low"


def estimated_bvp_rating(player):
    bucket = stable_bucket_for_player(player, "bvp", 100)
    if bucket >= 88:
        return {"batter_vs_pitcher": "Strong", "bvp_boost": 0.35}
    if bucket <= 12:
        return {"batter_vs_pitcher": "Weak", "bvp_boost": -0.25}
    return {"batter_vs_pitcher": "Neutral", "bvp_boost": 0.0}


def estimated_trend_score(player):
    projection = safe_float(player.get("projection", 0))
    ownership = safe_float(player.get("ownership", 10))
    value = player_value(player)
    salary = safe_int(player.get("salary", 0))
    bucket = stable_bucket_for_player(player, "trend", 21) - 10
    score = 50 + bucket + min(18, projection * 1.1) + min(12, value * 3.0)
    if ownership <= 8:
        score += 6
    if salary >= 5500:
        score += 4
    return round(max(1, min(score, 99)), 1)


def data_engine_for_player(player):
    position = normalize_position(player.get("position", ""))
    starter_status = player.get("starter_status") or estimated_starter_status(player)
    injury_status = player.get("injury_status") or estimated_injury_status(player)
    line_abs = estimated_lineup_spot_and_abs(player)
    park = data_engine_park_info(player)
    weather = estimated_weather_risk(player)
    bvp = estimated_bvp_rating(player)
    trend_score = safe_float(player.get("trend_score", 0), 0)
    if trend_score <= 0:
        trend_score = estimated_trend_score(player)
    pull_risk = player.get("pull_risk") or estimated_pull_risk(player, starter_status, injury_status)

    adjustment = 0.0
    reasons = []

    if position == "P":
        innings = safe_float(line_abs.get("projected_innings"), 0)
        if innings >= 6:
            adjustment += 0.55
            reasons.append("Workload upside")
        elif innings < 4.6:
            adjustment -= 0.45
            reasons.append("Early pull risk")
    else:
        spot = line_abs.get("lineup_spot")
        if isinstance(spot, int) and spot <= 2:
            adjustment += 0.45
            reasons.append("Top lineup spot")
        elif isinstance(spot, int) and spot >= 8:
            adjustment -= 0.25
            reasons.append("Low lineup spot")
        if line_abs.get("avg_at_bats") and safe_float(line_abs.get("avg_at_bats"), 0) >= 4.2:
            adjustment += 0.20
            reasons.append("AB volume")

    if injury_status in ["day_to_day_risk", "watch"]:
        adjustment -= 0.75
        reasons.append("Injury watch")
    if starter_status in ["bench_risk", "starter_risk", "long_relief_risk"]:
        adjustment -= 0.65
        reasons.append("Starting risk")
    if pull_risk == "High":
        adjustment -= 0.45
        reasons.append("High pull risk")
    elif pull_risk == "Low":
        adjustment += 0.15
        reasons.append("Low pull risk")

    adjustment += safe_float(park.get("park_boost"), 0)
    if safe_float(park.get("park_boost"), 0) != 0:
        reasons.append(f"Park: {park.get('park_factor')}")
    adjustment += safe_float(weather.get("weather_boost"), 0)
    if safe_float(weather.get("weather_boost"), 0) != 0:
        reasons.append(weather.get("weather_note", "Weather adjustment"))
    adjustment += safe_float(bvp.get("bvp_boost"), 0)
    if safe_float(bvp.get("bvp_boost"), 0) != 0:
        reasons.append(f"BvP {bvp.get('batter_vs_pitcher')}")
    if trend_score >= 80:
        adjustment += 0.45
        reasons.append("Trending up")
    elif trend_score <= 35:
        adjustment -= 0.25
        reasons.append("Cold trend")

    auto_active_recommendation = "active"
    projection = safe_float(player.get("projection", 0), 0)
    salary = safe_int(player.get("salary", 0), 0)
    ownership = safe_float(player.get("ownership", 0), 0)
    if injury_status in ["il", "out", "confirmed_out"] or starter_status in ["confirmed_not_starting", "out"]:
        auto_active_recommendation = "inactive"
    elif position == "P" and safe_float(line_abs.get("projected_innings"), 0) > 0 and safe_float(line_abs.get("projected_innings"), 0) < 3.5:
        auto_active_recommendation = "inactive"
    elif position != "P" and projection > 0 and projection < 2.2 and salary <= 3200:
        auto_active_recommendation = "inactive"
    elif ownership > 0 and ownership < 0.7 and projection > 0 and projection < 4.0:
        auto_active_recommendation = "inactive"
    elif starter_status in ["bench_risk", "starter_risk", "long_relief_risk"] or injury_status in ["day_to_day_risk", "watch"]:
        auto_active_recommendation = "review"
    elif position != "P" and line_abs.get("lineup_spot") in [8, 9] and safe_float(line_abs.get("avg_at_bats"), 0) < 3.4:
        auto_active_recommendation = "review"

    confidence = "estimated"
    connected_paid_sources = DATA_ENGINE_SOURCES["sportsdataio"]["enabled"] or DATA_ENGINE_SOURCES["sportradar"]["enabled"]
    if connected_paid_sources:
        confidence = "api_ready_connected"

    return {
        "data_engine_version": DATA_ENGINE_VERSION,
        "data_confidence": confidence,
        "starter_status": starter_status,
        "injury_status": injury_status,
        "lineup_spot": line_abs.get("lineup_spot"),
        "avg_at_bats": line_abs.get("avg_at_bats"),
        "projected_innings": line_abs.get("projected_innings"),
        "pull_risk": pull_risk,
        "park_team": park.get("park_team"),
        "park_factor": park.get("park_factor"),
        "park_boost": park.get("park_boost"),
        "weather_risk": weather.get("weather_risk"),
        "weather_boost": weather.get("weather_boost"),
        "weather_note": weather.get("weather_note"),
        "batter_vs_pitcher": bvp.get("batter_vs_pitcher"),
        "bvp_boost": bvp.get("bvp_boost"),
        "trend_score": trend_score,
        "data_engine_boost": round(max(-3.0, min(adjustment, 3.0)), 2),
        "data_engine_reasons": reasons[:6],
        "auto_active_recommendation": auto_active_recommendation,
        "source_notes": [
            "MVP estimates active. Plug SportsDataIO/Sportradar for confirmed injury/lineup data.",
            "Odds/OpenWeather env keys can replace simulated totals/weather later.",
        ],
    }

def player_value(player):
    salary = player.get("salary", 0)
    if salary <= 0:
        return 0
    return round((player.get("projection", 0) / salary) * 1000, 2)


def projection_boost_for_player(player):
    position = player.get("position")
    projection = safe_float(player.get("projection", 0))
    salary = safe_int(player.get("salary", 0))
    ownership = safe_float(player.get("ownership", 10))
    value = player_value(player)

    boost = 0.0
    reasons = []

    if position == "P":
        if projection >= 20:
            boost += 1.4
            reasons.append("Pitcher safety")
        elif projection >= 16:
            boost += 0.7
            reasons.append("SP2 stability")

        if salary <= 7800 and projection >= 14:
            boost += 0.55
            reasons.append("Value arm")
    else:
        if value >= 2.5:
            boost += 0.45
            reasons.append("Value bat")
        if projection >= 10:
            boost += 0.35
            reasons.append("Hitter upside")
        if ownership <= 8:
            boost += 0.25
            reasons.append("Low-owned leverage")
        if salary <= 3500 and projection >= 6:
            boost += 0.25
            reasons.append("Salary saver")

    leverage_score = safe_float(player.get("leverage_score", 0), 0)
    ownership = safe_float(player.get("ownership", 10), 10)
    if position != "P" and leverage_score >= 65 and ownership <= 20:
        boost += 0.45
        reasons.append("Leverage edge")
    elif position == "P" and leverage_score >= 60 and ownership <= 22:
        boost += 0.35
        reasons.append("Pitcher leverage")

    data_engine_boost = safe_float(player.get("data_engine_boost", 0), 0)
    if data_engine_boost != 0:
        boost += data_engine_boost
        reasons.append("Data engine")

    for reason in player.get("data_engine_reasons", [])[:3]:
        if reason not in reasons:
            reasons.append(reason)

    return {
        "boost": round(boost, 2),
        "reasons": reasons,
    }


def boosted_projection(player):
    boost = projection_boost_for_player(player)
    return round(safe_float(player.get("projection", 0)) + boost["boost"] + safe_float(player.get("market_boost", 0), 0), 2)


def player_grade(player):
    ownership = safe_float(player.get("ownership", 10))
    leverage_score = safe_float(player.get("leverage_score", 0), 0)
    chalk_score = safe_float(player.get("chalk_score", 0), 0)
    core_score = safe_float(player.get("core_play_score", 50), 50)
    core_tier = str(player.get("core_play_tier", "neutral")).lower()
    core_bonus = 0.0
    if core_tier == "core":
        core_bonus = 2.4
    elif core_tier == "strong":
        core_bonus = 1.25
    elif core_tier == "bad_chalk":
        core_bonus = -2.0
    elif core_tier == "fade":
        core_bonus = -2.6
    elif core_tier == "inactive":
        core_bonus = -100.0

    return (
        boosted_projection(player) * 2.35
        + player_value(player) * 3.15
        + leverage_score * 0.045
        + core_score * 0.018
        + core_bonus
        - chalk_score * 0.018
        - ownership * 0.018
    )


def add_values(players):
    clean_players = []
    for player in players:
        clean_player = dict(player)
        clean_player["position"] = normalize_position(clean_player.get("position"))
        clean_player["team"] = normalize_team(clean_player.get("team"))
        clean_player["opponent"] = normalize_team(clean_player.get("opponent", ""))
        clean_player["active"] = bool(clean_player.get("active", True))
        clean_player["inactive_reason"] = str(clean_player.get("inactive_reason", ""))
        current_ownership = safe_float(clean_player.get("ownership", 0))
        ownership_is_old_default = abs(current_ownership - 10.0) < 0.01 and clean_player.get("ownership_estimated") is not False

        if current_ownership <= 0 or ownership_is_old_default:
            clean_player["ownership"] = estimate_ownership_for_player(clean_player)
            clean_player["ownership_estimated"] = True

        vegas_env = vegas_environment_for_player(clean_player)
        clean_player.update(vegas_env)

        data_engine = data_engine_for_player(clean_player)
        clean_player.update(data_engine)

        # Recalculate ownership when it is estimated/missing, then score leverage.
        if clean_player.get("ownership_estimated") is True or safe_float(clean_player.get("ownership", 0), 0) <= 0:
            clean_player["ownership"] = calculate_real_ownership_projection(clean_player)
            clean_player["ownership_estimated"] = True

        clean_player["value"] = player_value(clean_player)
        clean_player.update(leverage_profile_for_player(clean_player))
        clean_player.update(market_movement_profile(clean_player))
        boost_info = projection_boost_for_player(clean_player)
        clean_player["projection_boost"] = boost_info["boost"]
        clean_player["boosted_projection"] = boosted_projection(clean_player)
        clean_player["boost_reasons"] = boost_info["reasons"]
        clean_player.update(core_play_profile_for_player(clean_player))
        clean_players.append(clean_player)
    return clean_players


def auto_cleanup_decision(player):
    """
    SAFE MVP auto-cleanup decision.

    Important: until we connect a paid/official injury + confirmed lineup feed,
    this should NOT hard-remove too many players. It only marks truly unusable
    data as inactive. Everything else stays active but gets a review reason so
    the optimizer can still build lineups.
    """
    position = normalize_position(player.get("position", ""))
    projection = safe_float(player.get("projection", 0), 0)
    salary = safe_int(player.get("salary", 0), 0)
    ownership = safe_float(player.get("ownership", 0), 0)
    starter_status = str(player.get("starter_status", "")).lower()
    injury_status = str(player.get("injury_status", "")).lower()
    pull_risk = str(player.get("pull_risk", "")).lower()
    projected_innings = safe_float(player.get("projected_innings", 0), 0)
    avg_at_bats = safe_float(player.get("avg_at_bats", 0), 0)
    lineup_spot = player.get("lineup_spot")

    reasons = []

    # Only hard-inactivate when we have an actual out/IL style signal.
    if injury_status in ["il", "out", "confirmed_out"]:
        return False, "auto_injury_or_il", ["IL/out estimate"]

    if starter_status in ["confirmed_not_starting", "out"]:
        return False, "auto_not_starting", ["Not-starting estimate"]

    # Broken row / non-usable salary only.
    if salary <= 0 or position not in ["P", "C", "1B", "2B", "3B", "SS", "OF"]:
        return False, "auto_invalid_player_row", ["Invalid salary or position"]

    # Soft review signals. These stay active so Generate never silently fails.
    if position == "P":
        if projected_innings > 0 and projected_innings < 3.5:
            reasons.append("Low projected innings")
        if projection > 0 and projection < 5.0 and salary <= 5500:
            reasons.append("Low pitcher projection")
        if pull_risk == "high":
            reasons.append("High pitcher pull risk")
        if starter_status in ["long_relief_risk", "starter_risk"]:
            reasons.append("Pitcher role risk")
    else:
        if projection > 0 and projection < 2.2 and salary <= 3200:
            reasons.append("Low hitter projection")
        if ownership > 0 and ownership < 0.7 and projection > 0 and projection < 4.0:
            reasons.append("Very low ownership / bench risk")
        if starter_status in ["bench_risk", "starter_risk"]:
            reasons.append("Starting role review")
        if lineup_spot in [8, 9] and avg_at_bats > 0 and avg_at_bats < 3.4:
            reasons.append("Low lineup spot / lower AB estimate")

    if injury_status in ["day_to_day_risk", "watch"]:
        reasons.append("Injury watch")

    return True, "auto_review" if reasons else "auto_active", reasons

def apply_auto_slate_cleanup(players, respect_manual_overrides=True):
    enriched = add_values(players)
    kept_by_basic_rules = []
    inactive_players = []

    for player in enriched:
        manual_override = bool(player.get("manual_status_override", False))
        if respect_manual_overrides and manual_override:
            player["auto_cleanup_applied"] = False
            player["auto_cleanup_reason"] = "manual_override"
            kept_by_basic_rules.append(player) if bool(player.get("active", True)) else inactive_players.append(player)
            continue

        active, reason, reasons = auto_cleanup_decision(player)
        player["auto_cleanup_applied"] = True
        player["auto_cleanup_reason"] = reason
        player["auto_cleanup_reasons"] = reasons

        if active:
            player["active"] = True
            player["inactive_reason"] = ""
            kept_by_basic_rules.append(player)
        else:
            player["active"] = False
            player["inactive_reason"] = reason
            inactive_players.append(player)

    final_active = []
    final_inactive = list(inactive_players)

    for position, limit in AUTO_CLEANUP_POSITION_LIMITS.items():
        manual_active = [
            p for p in kept_by_basic_rules
            if normalize_position(p.get("position", "")) == position and bool(p.get("manual_status_override", False)) and bool(p.get("active", True))
        ]
        candidates = [
            p for p in kept_by_basic_rules
            if normalize_position(p.get("position", "")) == position and p not in manual_active
        ]
        candidates.sort(key=player_grade, reverse=True)

        room = max(0, limit - len(manual_active))
        selected = manual_active + candidates[:room]
        overflow = candidates[room:]

        for player in selected:
            player["active"] = True
            if player.get("inactive_reason", "").startswith("auto_"):
                player["inactive_reason"] = ""
            final_active.append(player)

        for player in overflow:
            if bool(player.get("manual_status_override", False)):
                final_active.append(player)
                continue
            player["active"] = False
            player["inactive_reason"] = "auto_slate_pool_trim"
            player["auto_cleanup_reason"] = "auto_slate_pool_trim"
            overflow_reasons = list(player.get("auto_cleanup_reasons", []))
            overflow_reasons.append(f"Outside top {limit} {position} pool")
            player["auto_cleanup_reasons"] = overflow_reasons[:5]
            final_inactive.append(player)

    known_names = set(p.get("name") for p in final_active + final_inactive)
    for player in enriched:
        if player.get("name") not in known_names:
            player["active"] = False
            player["inactive_reason"] = "auto_unknown_position_trim"
            player["auto_cleanup_reason"] = "auto_unknown_position_trim"
            final_inactive.append(player)

    cleaned = final_active + final_inactive
    cleaned.sort(key=lambda p: (not bool(p.get("active", True)), normalize_position(p.get("position", "")), -safe_float(p.get("boosted_projection", p.get("projection", 0)), 0)))

    stats = {
        "original_count": len(players),
        "enriched_count": len(enriched),
        "active_count": len([p for p in cleaned if bool(p.get("active", True))]),
        "inactive_count": len([p for p in cleaned if not bool(p.get("active", True))]),
        "position_limits": AUTO_CLEANUP_POSITION_LIMITS,
        "inactive_reasons": {},
    }
    for player in cleaned:
        if not bool(player.get("active", True)):
            reason = player.get("inactive_reason", "unknown")
            stats["inactive_reasons"][reason] = stats["inactive_reasons"].get(reason, 0) + 1

    return cleaned, stats


def trim_player_pool(players, locked_players):
    locked_names = set(locked_players)
    trimmed = []
    report = {}

    for position, limit in POOL_LIMITS.items():
        position_players = [p for p in players if p["position"] == position]
        locked = [p for p in position_players if p["name"] in locked_names]
        unlocked = [p for p in position_players if p["name"] not in locked_names]
        unlocked.sort(key=player_grade, reverse=True)
        selected = locked + unlocked[: max(0, limit - len(locked))]
        trimmed.extend(selected)
        report[position] = {
            "before": len(position_players),
            "after": len(selected),
            "limit": limit,
        }

    return trimmed, report


def validate_locks(players, locked_players, excluded_players):
    names = set(p["name"] for p in players)
    missing_locked = [p for p in locked_players if p not in names]
    missing_excluded = [p for p in excluded_players if p not in names]
    both = [p for p in locked_players if p in excluded_players]

    if missing_locked:
        return f"Locked player not found: {', '.join(missing_locked)}"
    if missing_excluded:
        return f"Excluded player not found: {', '.join(missing_excluded)}"
    if both:
        return f"Player cannot be both locked and excluded: {', '.join(both)}"
    if len(locked_players) > 10:
        return "You cannot lock more than 10 players."

    return None


def lineup_key(lineup):
    return "|".join(sorted(p["name"] for p in lineup))


def deterministic_random_bonus(lineup, randomness):
    randomness = min(max(randomness, 0), 100)
    if randomness <= 0:
        return 0
    key = lineup_key(lineup)
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    normalized = int(digest[:8], 16) / 0xFFFFFFFF
    return round(normalized * (randomness / 100) * 8.0, 4)


def get_pitchers(lineup):
    return [p for p in lineup if p["position"] == "P"]


def get_hitters(lineup):
    return [p for p in lineup if p["position"] != "P"]


def count_team_players(lineup, hitters_only=False):
    counts = {}
    for player in lineup:
        if hitters_only and player.get("position") == "P":
            continue
        team = player.get("team", "UNK")
        counts[team] = counts.get(team, 0) + 1
    return counts


def best_stack_info(lineup):
    hitter_counts = count_team_players(lineup, hitters_only=True)
    if not hitter_counts:
        return {"team": "", "size": 0, "counts": {}}
    best_team = max(hitter_counts, key=hitter_counts.get)
    return {
        "team": best_team,
        "size": hitter_counts[best_team],
        "counts": hitter_counts,
    }


def has_team_stack(lineup, minimum_stack_size=3):
    return best_stack_info(lineup)["size"] >= minimum_stack_size


def pitcher_vs_hitter_conflict(lineup):
    pitchers = get_pitchers(lineup)
    hitters = get_hitters(lineup)

    pitcher_teams = set(p.get("team") for p in pitchers)
    pitcher_opponents = set(p.get("opponent") for p in pitchers if p.get("opponent"))

    for hitter in hitters:
        hitter_team = hitter.get("team")
        hitter_opp = hitter.get("opponent")
        if hitter_team in pitcher_opponents:
            return True
        if hitter_opp and hitter_opp in pitcher_teams:
            return True

    return False


def stack_bonus_for_lineup(lineup, mode):
    info = best_stack_info(lineup)
    size = info["size"]

    if str(mode).lower() == "cash":
        if size >= 5:
            return -0.35
        if size == 4:
            return 0.15
        if size == 3:
            return 0.2
        return 0

    bonus = 0
    if size == 3:
        bonus += 1.15
    elif size == 4:
        bonus += 2.65
    elif size == 5:
        bonus += 3.45
    elif size >= 6:
        bonus += 2.6

    counts = info["counts"]
    secondary_stacks = [count for count in counts.values() if 2 <= count < size]
    if secondary_stacks:
        bonus += 0.7

    return bonus


def ownership_score_for_lineup(lineup, mode):
    if not lineup:
        return 0
    avg_ownership = sum(p.get("ownership", 10) for p in lineup) / len(lineup)
    avg_leverage = sum(safe_float(p.get("leverage_score", 0), 0) for p in lineup) / len(lineup)
    avg_chalk = sum(safe_float(p.get("chalk_score", 0), 0) for p in lineup) / len(lineup)

    if str(mode).lower() == "cash":
        # Cash can eat some chalk, but still rewards efficient lower-owned plays.
        return max(0, 20 - avg_ownership) * 0.025 + max(0, avg_leverage - 45) * 0.018

    leverage_bonus = max(0, avg_leverage - 42) * 0.07
    low_owned_bonus = sum(max(0, 18 - p.get("ownership", 10)) * 0.05 for p in lineup)
    chalk_penalty = max(0, avg_chalk - avg_leverage) * 0.055
    extreme_chalk_penalty = sum(max(0, p.get("ownership", 10) - 32) * 0.035 for p in lineup)
    return leverage_bonus + low_owned_bonus - chalk_penalty - extreme_chalk_penalty


def pitcher_safety_bonus(lineup, mode):
    pitchers = get_pitchers(lineup)
    if not pitchers:
        return 0
    projection_bonus = sum(p.get("projection", 0) for p in pitchers) * 0.035
    if str(mode).lower() == "cash":
        return projection_bonus + 0.6
    return projection_bonus


def salary_usage_bonus(salary, mode):
    remaining = SALARY_CAP - salary
    if str(mode).lower() == "cash":
        if remaining <= 800:
            return 0.55
        if remaining <= 1500:
            return 0.25
        return -0.25
    if remaining <= 500:
        return 0.25
    if remaining >= 3500:
        return 0.35
    return 0


def lineup_boost_breakdown(lineup, mode):
    total_player_boost = round(sum(safe_float(p.get("projection_boost", 0)) for p in lineup), 2)
    stack_bonus = round(stack_bonus_for_lineup(lineup, mode), 2)
    ownership_bonus = round(ownership_score_for_lineup(lineup, mode), 2)
    pitcher_bonus = round(pitcher_safety_bonus(lineup, mode), 2)
    salary_bonus = round(salary_usage_bonus(sum(p["salary"] for p in lineup), mode), 2)
    conflict_penalty = -5.0 if pitcher_vs_hitter_conflict(lineup) else 0.0

    return {
        "player_projection_boost": total_player_boost,
        "stack_upside": stack_bonus,
        "ownership_leverage": ownership_bonus,
        "pitcher_safety": pitcher_bonus,
        "salary_efficiency": salary_bonus,
        "pitcher_conflict_penalty": conflict_penalty,
        "total_boost": round(total_player_boost + stack_bonus + ownership_bonus + pitcher_bonus + salary_bonus + conflict_penalty, 2),
    }


def lineup_explanation(lineup, mode):
    stack = best_stack_info(lineup)
    pitchers = get_pitchers(lineup)
    avg_ownership = round(sum(p.get("ownership", 0) for p in lineup) / len(lineup), 2) if lineup else 0

    notes = []
    if pitchers:
        notes.append(f"Built around {len(pitchers)} pitchers with combined projection {round(sum(p.get('projection', 0) for p in pitchers), 2)}.")
    if stack["size"] >= 4:
        notes.append(f"Strong {stack['team']} {stack['size']}-hitter stack for ceiling.")
    elif stack["size"] >= 3:
        notes.append(f"Valid {stack['team']} {stack['size']}-hitter MLB stack.")
    else:
        notes.append("Balanced hitter build with no heavy stack.")
    notes.append(f"Average ownership estimate: {avg_ownership}%.")
    if pitcher_vs_hitter_conflict(lineup):
        notes.append("Warning: pitcher-vs-hitter conflict detected.")
    else:
        notes.append("No pitcher-vs-hitter conflict detected.")

    return " ".join(notes)


def score_lineup(lineup, mode, randomness=0):
    mode = str(mode or "cash").lower()
    projection = sum(p["projection"] for p in lineup)
    salary = sum(p["salary"] for p in lineup)

    # Base score still matters, but GPP builds now get a separate takedown objective.
    # The old model over-weighted median projection and produced safe/playable lineups.
    # Massive-field DFS needs lineups with top-end ceiling, stack correlation, and leverage.
    score = projection
    score += sum(safe_float(p.get("projection_boost", 0)) for p in lineup)
    score += ownership_score_for_lineup(lineup, mode)
    score += pitcher_safety_bonus(lineup, mode)
    score += salary_usage_bonus(salary, mode)

    if mode == "gpp":
        score += stack_bonus_for_lineup(lineup, mode)
    else:
        score += stack_bonus_for_lineup(lineup, "cash")

    core_profile = lineup_core_profile(lineup)
    score += safe_float(core_profile.get("core_play_count", 0), 0) * 0.75
    score += safe_float(core_profile.get("strong_play_count", 0), 0) * 0.35
    score -= safe_float(core_profile.get("bad_chalk_count", 0), 0) * (0.9 if mode == "gpp" else 0.35)
    score -= safe_float(core_profile.get("fade_count", 0), 0) * 1.15

    if pitcher_vs_hitter_conflict(lineup):
        score -= 5.0

    if mode == "cash":
        randomness = min(randomness, 10)
        return score + deterministic_random_bonus(lineup, randomness)

    # TRUE TAKEDOWN MODE:
    # In GPP, the primary sort key becomes top-end outcome strength, not median safety.
    # This pushes 4/5-man stacks, low-owned leverage, high ceiling, core-play counts,
    # and uniqueness while heavily penalizing bad chalk/fades/conflicts.
    return takedown_score_for_lineup(lineup, base_score=score, randomness=randomness)


def has_all_locked(lineup, locked_players):
    names = set(p["name"] for p in lineup)
    return all(name in names for name in locked_players)


def lineup_passes_advanced_rules(
    lineup,
    salary,
    min_salary,
    max_players_per_team,
    force_team_stack,
    avoid_pitcher_vs_hitter,
    mode,
):
    mode = str(mode or "cash").lower()
    min_salary = min(max(min_salary, 0), SALARY_CAP)
    max_players_per_team = min(max(max_players_per_team, 1), 8)

    if min_salary > 0 and salary < min_salary:
        return False

    hitter_team_counts = count_team_players(lineup, hitters_only=True)
    if any(count > max_players_per_team for count in hitter_team_counts.values()):
        return False

    if force_team_stack and not has_team_stack(lineup, minimum_stack_size=3):
        return False

    if mode == "gpp" and force_team_stack and not has_team_stack(lineup, minimum_stack_size=4):
        return False

    if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(lineup):
        return False

    return True



def lineup_quality_profile(lineup, mode="gpp"):
    """
    DFS Edge lineup quality model.
    Combines projection, ceiling, ownership leverage, stack quality, core plays,
    fade/bad chalk penalties, salary usage, and conflict safety into one score.
    """
    if not lineup:
        return {
            "lineup_quality_score": 0,
            "win_probability": 0,
            "lineup_quality_label": "No Lineup",
            "lineup_quality_breakdown": {
                "projection_score": 0,
                "ceiling_score": 0,
                "leverage_score": 0,
                "stack_score": 0,
                "core_score": 0,
                "salary_score": 0,
                "safety_score": 0,
                "fade_penalty": 0,
                "bad_chalk_penalty": 0,
                "conflict_penalty": 0,
            },
        }

    mode = str(mode or "gpp").lower()
    projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
    boosted = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    avg_ownership = sum(safe_float(p.get("ownership", 10), 10) for p in lineup) / len(lineup)
    avg_leverage = sum(safe_float(p.get("leverage_score", 50), 50) for p in lineup) / len(lineup)
    avg_core_score = sum(safe_float(p.get("core_play_score", 50), 50) for p in lineup) / len(lineup)
    avg_trend = sum(safe_float(p.get("trend_score", 50), 50) for p in lineup) / len(lineup)
    total_vegas_boost = sum(safe_float(p.get("vegas_boost", 0), 0) for p in lineup)
    total_data_boost = sum(safe_float(p.get("data_engine_boost", 0), 0) for p in lineup)
    core_profile = lineup_core_profile(lineup)
    leverage_profile = lineup_leverage_profile(lineup)
    stack = best_stack_info(lineup)
    stack_size = safe_int(stack.get("size", 0), 0)
    secondary_stacks = [count for count in stack.get("counts", {}).values() if 2 <= count < stack_size]
    conflict = pitcher_vs_hitter_conflict(lineup)

    projection_score = max(0.0, min(100.0, (projection - 55.0) * 1.35))
    ceiling_score = max(0.0, min(100.0, (boosted - 57.0) * 1.30 + max(0.0, total_vegas_boost) * 2.2 + max(0.0, avg_trend - 50.0) * 0.42))
    leverage_score = max(0.0, min(100.0, avg_leverage + max(0.0, 18.0 - avg_ownership) * 1.15 - max(0.0, avg_ownership - 28.0) * 0.85))

    stack_score = 42.0
    if stack_size >= 5:
        stack_score += 35.0
    elif stack_size == 4:
        stack_score += 28.0
    elif stack_size == 3:
        stack_score += 18.0
    elif stack_size == 2:
        stack_score += 7.0
    if secondary_stacks:
        stack_score += 12.0
    if mode == "cash" and stack_size >= 5:
        stack_score -= 10.0
    stack_score = max(0.0, min(100.0, stack_score))

    core_count = safe_int(core_profile.get("core_play_count", 0), 0)
    strong_count = safe_int(core_profile.get("strong_play_count", 0), 0)
    fade_count = safe_int(core_profile.get("fade_count", 0), 0)
    bad_chalk_count = safe_int(core_profile.get("bad_chalk_count", 0), 0)

    core_score = max(0.0, min(100.0, avg_core_score + core_count * 4.0 + strong_count * 2.0))
    salary_score = 78.0
    if mode == "cash":
        if remaining <= 500:
            salary_score = 96.0
        elif remaining <= 1200:
            salary_score = 88.0
        elif remaining <= 2500:
            salary_score = 76.0
        else:
            salary_score = 58.0
    else:
        if remaining <= 800:
            salary_score = 84.0
        elif remaining <= 2200:
            salary_score = 88.0
        elif remaining <= 4200:
            salary_score = 76.0
        else:
            salary_score = 64.0

    safety_score = 88.0
    inactive_count = len([p for p in lineup if bool(p.get("active", True)) is False])
    review_count = len([p for p in lineup if str(p.get("auto_active_recommendation", "active")).lower() == "review"])
    safety_score -= inactive_count * 30.0
    safety_score -= review_count * 6.0
    if conflict:
        safety_score -= 24.0
    safety_score = max(0.0, min(100.0, safety_score))

    fade_penalty = fade_count * 7.0
    bad_chalk_penalty = bad_chalk_count * (8.0 if mode == "gpp" else 3.5)
    conflict_penalty = 10.0 if conflict else 0.0

    if mode == "cash":
        quality_score = (
            projection_score * 0.31
            + ceiling_score * 0.13
            + leverage_score * 0.12
            + stack_score * 0.08
            + core_score * 0.16
            + salary_score * 0.12
            + safety_score * 0.18
            - fade_penalty
            - bad_chalk_penalty
            - conflict_penalty
        )
    else:
        quality_score = (
            projection_score * 0.22
            + ceiling_score * 0.24
            + leverage_score * 0.20
            + stack_score * 0.15
            + core_score * 0.13
            + salary_score * 0.06
            + safety_score * 0.08
            - fade_penalty
            - bad_chalk_penalty
            - conflict_penalty
        )

    quality_score = round(max(0.0, min(100.0, quality_score)), 1)

    if mode == "cash":
        win_probability = round(max(1.0, min(99.0, quality_score * 0.82 + safety_score * 0.12 + projection_score * 0.06)), 1)
    else:
        win_probability = round(max(1.0, min(99.0, quality_score * 0.72 + ceiling_score * 0.14 + leverage_score * 0.10 + stack_score * 0.04)), 1)

    if quality_score >= 88:
        label = "Elite Build"
    elif quality_score >= 78:
        label = "Strong Build"
    elif quality_score >= 66:
        label = "Playable"
    elif quality_score >= 52:
        label = "Risky"
    else:
        label = "Weak Build"

    return {
        "lineup_quality_score": quality_score,
        "win_probability": win_probability,
        "lineup_quality_label": label,
        "lineup_quality_breakdown": {
            "projection_score": round(projection_score, 1),
            "ceiling_score": round(ceiling_score, 1),
            "leverage_score": round(leverage_score, 1),
            "stack_score": round(stack_score, 1),
            "core_score": round(core_score, 1),
            "salary_score": round(salary_score, 1),
            "safety_score": round(safety_score, 1),
            "fade_penalty": round(fade_penalty, 1),
            "bad_chalk_penalty": round(bad_chalk_penalty, 1),
            "conflict_penalty": round(conflict_penalty, 1),
        },
    }


def takedown_score_for_lineup(lineup, base_score=0.0, randomness=0):
    """
    Massive-field GPP objective. This is intentionally different from cash/safe
    optimization. It rewards a lineup for the things that actually create a
    first-place outcome: ceiling, stack correlation, leverage, uniqueness, and
    core strength. Median projection still matters, but it is not allowed to
    dominate the sort.
    """
    if not lineup:
        return 0.0

    projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
    boosted = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    ownership_values = [safe_float(p.get("ownership", 10), 10) for p in lineup]
    avg_ownership = sum(ownership_values) / len(ownership_values)
    max_ownership = max(ownership_values) if ownership_values else 0
    low_owned_count = len([o for o in ownership_values if o <= 10])
    chalk_count = len([o for o in ownership_values if o >= 24])

    leverage_values = [safe_float(p.get("leverage_score", 50), 50) for p in lineup]
    avg_leverage = sum(leverage_values) / len(leverage_values)
    high_leverage_count = len([v for v in leverage_values if v >= 62])

    core_profile = lineup_core_profile(lineup)
    core_count = safe_int(core_profile.get("core_play_count", 0), 0)
    strong_count = safe_int(core_profile.get("strong_play_count", 0), 0)
    fade_count = safe_int(core_profile.get("fade_count", 0), 0)
    bad_chalk_count = safe_int(core_profile.get("bad_chalk_count", 0), 0)

    stack = best_stack_info(lineup)
    stack_size = safe_int(stack.get("size", 0), 0)
    team_counts = stack.get("counts", {}) if isinstance(stack, dict) else {}
    secondary_stack = max([c for c in team_counts.values() if c < stack_size], default=0)

    stack_bonus = 0.0
    if stack_size >= 5:
        stack_bonus += 42.0
    elif stack_size == 4:
        stack_bonus += 31.0
    elif stack_size == 3:
        stack_bonus += 16.0
    if secondary_stack >= 3:
        stack_bonus += 20.0
    elif secondary_stack == 2:
        stack_bonus += 11.0

    # A winning MLB GPP lineup usually needs correlation, but it cannot be made
    # only of weak projected bats. Use boosted ceiling as the first pillar.
    ceiling_component = boosted * 1.24 + projection * 0.34
    leverage_component = avg_leverage * 0.54 + high_leverage_count * 3.2 + low_owned_count * 1.7
    core_component = core_count * 5.4 + strong_count * 2.2

    # Do not blindly reward leaving too much salary. A little leftover can reduce
    # duplicates, but too much usually lowers raw-score potential.
    if 300 <= remaining <= 2200:
        uniqueness_bonus = 7.5
    elif 2201 <= remaining <= 3900:
        uniqueness_bonus = 4.0
    elif remaining > 3900:
        uniqueness_bonus = -6.5
    else:
        uniqueness_bonus = 2.0

    chalk_penalty = max(0.0, avg_ownership - 18.0) * 1.65 + max(0.0, max_ownership - 32.0) * 1.2
    chalk_penalty += chalk_count * 2.2 + bad_chalk_count * 9.5
    fade_penalty = fade_count * 12.0
    conflict_penalty = 18.0 if pitcher_vs_hitter_conflict(lineup) else 0.0

    takedown_score = (
        base_score * 0.22
        + ceiling_component
        + leverage_component
        + stack_bonus
        + core_component
        + uniqueness_bonus
        - chalk_penalty
        - fade_penalty
        - conflict_penalty
    )

    takedown_score += deterministic_random_bonus(lineup, min(max(randomness, 0), 100)) * 0.72
    return round(takedown_score, 4)


def add_lineup_metadata(lineup_data):
    lineup = lineup_data["lineup"]
    mode = lineup_data.get("mode", "cash")
    stack = best_stack_info(lineup)

    lineup_data["best_stack_team"] = stack["team"]
    lineup_data["best_stack_size"] = stack["size"]
    lineup_data["team_breakdown"] = stack["counts"]
    lineup_data["pitcher_conflict"] = pitcher_vs_hitter_conflict(lineup)
    lineup_data["salary_remaining"] = SALARY_CAP - lineup_data["total_salary"]
    lineup_data["roster_slots"] = ROSTER_SLOTS
    lineup_data["boost_breakdown"] = lineup_boost_breakdown(lineup, mode)
    lineup_data["lineup_explanation"] = lineup_explanation(lineup, mode)
    lineup_data["average_ownership"] = round(sum(p.get("ownership", 0) for p in lineup) / len(lineup), 2) if lineup else 0
    leverage_profile = lineup_leverage_profile(lineup)
    lineup_data.update(leverage_profile)
    lineup_data.update(lineup_core_profile(lineup))
    lineup_data.update(lineup_quality_profile(lineup, mode))

    # Frontend compatibility: older UI sections expect a compact lineup_iq object
    # with stack/leverage/ceiling/safety keys. Keep the richer breakdown too.
    q_breakdown = lineup_data.get("lineup_quality_breakdown", {}) or {}
    lineup_data["lineup_iq_score"] = lineup_data.get("lineup_quality_score", 0)
    lineup_data["lineup_iq_label"] = lineup_data.get("lineup_quality_label", "Playable")
    lineup_data["lineup_iq"] = {
        "projection": q_breakdown.get("projection_score", 0),
        "ceiling": q_breakdown.get("ceiling_score", 0),
        "leverage": q_breakdown.get("leverage_score", 0),
        "stack_strength": q_breakdown.get("stack_score", 0),
        "core": q_breakdown.get("core_score", 0),
        "salary": q_breakdown.get("salary_score", 0),
        "safety": q_breakdown.get("safety_score", 0),
        "fade_penalty": q_breakdown.get("fade_penalty", 0),
        "bad_chalk_penalty": q_breakdown.get("bad_chalk_penalty", 0),
    }

    lineup_data["lineup_health"] = calculate_lineup_health_profile(lineup_data)

    return lineup_data


def build_all_lineups(
    mode,
    locked_players=None,
    excluded_players=None,
    min_salary=0,
    max_players_per_team=5,
    force_qb_stack=False,
    force_bring_back=True,
    force_team_stack=False,
    avoid_pitcher_vs_hitter=True,
    randomness=0,
):
    locked_players = locked_players or []
    excluded_players = excluded_players or []
    mode = str(mode or "cash").lower()

    force_team_stack = force_team_stack or force_qb_stack
    if mode == "gpp":
        randomness = min(max(randomness, 0), 100)
    else:
        randomness = min(max(randomness, 0), 10)

    if force_bring_back is not None:
        avoid_pitcher_vs_hitter = bool(force_bring_back)

    players = add_values(load_players())

    error = validate_locks(players, locked_players, excluded_players)
    if error:
        return [], error, {}, 0

    available_players = [
        p for p in players
        if p["name"] not in excluded_players and bool(p.get("active", True))
    ]
    optimized_pool, trim_report = trim_player_pool(available_players, locked_players)

    pitchers = [p for p in optimized_pool if p["position"] == "P"]
    catchers = [p for p in optimized_pool if p["position"] == "C"]
    first_base = [p for p in optimized_pool if p["position"] == "1B"]
    second_base = [p for p in optimized_pool if p["position"] == "2B"]
    third_base = [p for p in optimized_pool if p["position"] == "3B"]
    shortstops = [p for p in optimized_pool if p["position"] == "SS"]
    outfielders = [p for p in optimized_pool if p["position"] == "OF"]

    if (
        len(pitchers) < 2
        or not catchers
        or not first_base
        or not second_base
        or not third_base
        or not shortstops
        or len(outfielders) < 3
    ):
        return [], "Not enough players at each MLB position to build a DraftKings lineup.", trim_report, 0

    for group in [pitchers, catchers, first_base, second_base, third_base, shortstops, outfielders]:
        group.sort(key=player_grade, reverse=True)

    pitcher_combos = list(combinations(pitchers, 2))
    of_combos = list(combinations(outfielders, 3))

    pitcher_combos.sort(
        key=lambda combo: (
            sum(p["projection"] for p in combo),
            -sum(p["salary"] for p in combo),
        ),
        reverse=True,
    )

    of_combos.sort(
        key=lambda combo: (
            sum(p["projection"] for p in combo),
            -sum(p["salary"] for p in combo),
        ),
        reverse=True,
    )

    valid_lineups = []
    seen = set()
    checked = 0

    for p_combo in pitcher_combos:
        pitcher_salary = sum(p["salary"] for p in p_combo)
        if pitcher_salary > SALARY_CAP:
            continue

        for c in catchers:
            for fb in first_base:
                for sb in second_base:
                    for tb in third_base:
                        for ss in shortstops:
                            infield_players = [c, fb, sb, tb, ss]
                            base_players = list(p_combo) + infield_players
                            base_salary = sum(p["salary"] for p in base_players)

                            if base_salary > SALARY_CAP:
                                continue

                            used_names = set(p["name"] for p in base_players)

                            for of_combo in of_combos:
                                checked += 1

                                if any(p["name"] in used_names for p in of_combo):
                                    continue

                                lineup = base_players + list(of_combo)
                                salary = base_salary + sum(p["salary"] for p in of_combo)

                                if salary > SALARY_CAP:
                                    continue

                                if not has_all_locked(lineup, locked_players):
                                    continue

                                if not lineup_passes_advanced_rules(
                                    lineup=lineup,
                                    salary=salary,
                                    min_salary=min_salary,
                                    max_players_per_team=max_players_per_team,
                                    force_team_stack=force_team_stack,
                                    avoid_pitcher_vs_hitter=avoid_pitcher_vs_hitter,
                                    mode=mode,
                                ):
                                    continue

                                key = lineup_key(lineup)
                                if key in seen:
                                    continue

                                seen.add(key)

                                projection = sum(p["projection"] for p in lineup)
                                score = score_lineup(lineup, mode, randomness)

                                lineup_data = {
                                    "mode": mode,
                                    "total_salary": salary,
                                    "projected_points": round(projection, 2),
                                    "optimizer_score": round(score, 2),
                                    "lineup": lineup,
                                }

                                valid_lineups.append(add_lineup_metadata(lineup_data))

                                if len(valid_lineups) >= 1200:
                                    valid_lineups.sort(key=lambda x: x["optimizer_score"], reverse=True)
                                    return valid_lineups, None, trim_report, checked

                                # Early exit for speed (prevents timeout in Pro mode)
                                if checked >= MAX_COMBINATIONS_TO_CHECK:
                                    if len(valid_lineups) >= 20:
                                        valid_lineups.sort(key=lambda x: x["optimizer_score"], reverse=True)
                                        return valid_lineups, None, trim_report, checked

    valid_lineups.sort(key=lambda x: x["optimizer_score"], reverse=True)

    if not valid_lineups:
        return [], "No valid MLB lineups found. Try lowering minimum salary, increasing max hitters per team, clearing locks/excludes, or turning off stack / pitcher-vs-hitter rules.", trim_report, checked

    return valid_lineups, None, trim_report, checked


def count_same_players(a, b):
    return len(set(p["name"] for p in a).intersection(set(p["name"] for p in b)))


def passes_similarity(candidate, selected, max_same_players):
    for lineup in selected:
        if count_same_players(candidate["lineup"], lineup["lineup"]) > max_same_players:
            return False
    return True


def clamp_percent(value, default=0):
    try:
        return min(max(int(value), 0), 100)
    except Exception:
        return default


def exposure_percent_to_uses(percent, count):
    percent = clamp_percent(percent, 0)
    if count <= 0 or percent <= 0:
        return 0
    return max(1, round(count * (percent / 100)))


def normalize_exposure_limits(raw_limits):
    if not isinstance(raw_limits, dict):
        return {}

    normalized = {}
    for name, value in raw_limits.items():
        clean_name = str(name).strip()
        if not clean_name:
            continue
        normalized[clean_name] = clamp_percent(value, 0)

    return normalized


def candidate_has_player(candidate, player_name):
    return any(player["name"] == player_name for player in candidate["lineup"])


def min_exposure_need_score(candidate, exposure_tracker, player_min_exposure, count):
    score = 0
    for player_name, percent in player_min_exposure.items():
        required_uses = exposure_percent_to_uses(percent, count)
        if required_uses <= 0:
            continue
        current_uses = exposure_tracker.get(player_name, 0)
        if current_uses >= required_uses:
            continue
        if candidate_has_player(candidate, player_name):
            score += required_uses - current_uses
    return score


def passes_exposure(candidate, exposure_tracker, max_uses, locked_players, player_max_exposure=None, count=1):
    player_max_exposure = player_max_exposure or {}
    for player in candidate["lineup"]:
        name = player["name"]
        if name in locked_players:
            continue
        allowed_uses = max_uses
        if name in player_max_exposure:
            allowed_uses = exposure_percent_to_uses(player_max_exposure[name], count)
        if allowed_uses <= 0:
            return False
        if exposure_tracker.get(name, 0) >= allowed_uses:
            return False
    return True


def update_exposure(lineup, exposure_tracker):
    for player in lineup:
        name = player["name"]
        exposure_tracker[name] = exposure_tracker.get(name, 0) + 1


def diversify_lineups(
    all_lineups,
    count,
    max_exposure,
    max_same_players,
    locked_players,
    player_min_exposure=None,
    player_max_exposure=None,
):
    if count == 1:
        return all_lineups[:1]

    player_min_exposure = normalize_exposure_limits(player_min_exposure)
    player_max_exposure = normalize_exposure_limits(player_max_exposure)

    selected = []
    exposure_tracker = {}
    max_uses = max(1, round(count * (max_exposure / 100)))

    first_pass_lineups = list(all_lineups)
    if player_min_exposure:
        first_pass_lineups.sort(
            key=lambda candidate: (
                min_exposure_need_score(candidate, exposure_tracker, player_min_exposure, count),
                candidate.get("optimizer_score", 0),
            ),
            reverse=True,
        )

    for candidate in first_pass_lineups:
        if len(selected) >= count:
            break
        if not passes_similarity(candidate, selected, max_same_players):
            continue
        if not passes_exposure(
            candidate,
            exposure_tracker,
            max_uses,
            locked_players,
            player_max_exposure=player_max_exposure,
            count=count,
        ):
            continue
        selected.append(candidate)
        update_exposure(candidate["lineup"], exposure_tracker)

    if len(selected) < count:
        for candidate in all_lineups:
            if len(selected) >= count:
                break
            key = lineup_key(candidate["lineup"])
            if any(lineup_key(existing["lineup"]) == key for existing in selected):
                continue
            if not passes_exposure(
                candidate,
                exposure_tracker,
                max_uses,
                locked_players,
                player_max_exposure=player_max_exposure,
                count=count,
            ):
                continue
            selected.append(candidate)
            update_exposure(candidate["lineup"], exposure_tracker)

    return selected


def calculate_exposures(lineups):
    counts = {}
    for lineup in lineups:
        for player in lineup["lineup"]:
            name = player["name"]
            if name not in counts:
                counts[name] = {
                    "name": name,
                    "position": player["position"],
                    "team": player["team"],
                    "count": 0,
                    "exposure_percent": 0,
                }
            counts[name]["count"] += 1

    total = len(lineups)
    if total == 0:
        return []

    exposures = []
    for item in counts.values():
        item["exposure_percent"] = round((item["count"] / total) * 100, 1)
        exposures.append(item)

    exposures.sort(key=lambda x: x["exposure_percent"], reverse=True)
    return exposures



def build_fast_multi_lineups_for_pro(request, count):
    """
    Fast lineup builder for Pro multi-lineup mode.
    This avoids the huge brute-force nested search that can time out on large DraftKings CSV slates.
    It still respects locks, excludes, salary cap, team limits, team stacks, and pitcher-vs-hitter rules.
    """
    locked_players = request.locked_players or []
    excluded_players = request.excluded_players or []
    mode = str(request.mode or "cash").lower()
    count = count if count in [1, 5, 10, 20] else 1

    players = add_values(load_players())
    error = validate_locks(players, locked_players, excluded_players)
    if error:
        return [], error, {}, 0

    available = [
        p for p in players
        if p["name"] not in excluded_players and bool(p.get("active", True))
    ]
    optimized_pool, trim_report = trim_player_pool(available, locked_players)

    groups = {
        "P": [p for p in optimized_pool if p["position"] == "P"],
        "C": [p for p in optimized_pool if p["position"] == "C"],
        "1B": [p for p in optimized_pool if p["position"] == "1B"],
        "2B": [p for p in optimized_pool if p["position"] == "2B"],
        "3B": [p for p in optimized_pool if p["position"] == "3B"],
        "SS": [p for p in optimized_pool if p["position"] == "SS"],
        "OF": [p for p in optimized_pool if p["position"] == "OF"],
    }

    if (
        len(groups["P"]) < 2
        or not groups["C"]
        or not groups["1B"]
        or not groups["2B"]
        or not groups["3B"]
        or not groups["SS"]
        or len(groups["OF"]) < 3
    ):
        return [], "Not enough players at each MLB position to build Pro lineups.", trim_report, 0

    for key in groups:
        groups[key].sort(key=player_grade, reverse=True)

    locked_set = set(locked_players)
    locked_objects = [p for p in available if p["name"] in locked_set]

    def same_position_count(lineup, position):
        return len([p for p in lineup if p["position"] == position])

    def required_position_count(position):
        if position == "P":
            return 2
        if position == "OF":
            return 3
        return 1

    def lineup_position_valid(lineup):
        return (
            same_position_count(lineup, "P") == 2
            and same_position_count(lineup, "C") == 1
            and same_position_count(lineup, "1B") == 1
            and same_position_count(lineup, "2B") == 1
            and same_position_count(lineup, "3B") == 1
            and same_position_count(lineup, "SS") == 1
            and same_position_count(lineup, "OF") == 3
        )

    def add_best_available(lineup, used, position, offset):
        needed = required_position_count(position) - same_position_count(lineup, position)
        if needed <= 0:
            return

        pool = groups[position]
        if not pool:
            return

        steps = 0
        cursor = offset % len(pool)
        while needed > 0 and steps < len(pool) * 2:
            candidate = pool[cursor % len(pool)]
            cursor += 1
            steps += 1
            if candidate["name"] in used:
                continue
            lineup.append(candidate)
            used.add(candidate["name"])
            needed -= 1

    def repair_salary(lineup, used):
        salary = sum(p.get("salary", 0) for p in lineup)
        if salary <= SALARY_CAP:
            return lineup

        # Replace expensive unlocked hitters first, then unlocked pitchers if needed.
        for idx, current in sorted(list(enumerate(lineup)), key=lambda item: item[1].get("salary", 0), reverse=True):
            if salary <= SALARY_CAP:
                break
            if current["name"] in locked_set:
                continue

            pos = current["position"]
            cheaper = [
                p for p in groups[pos]
                if p["name"] not in used and p.get("salary", 0) < current.get("salary", 0)
            ]
            cheaper.sort(key=lambda p: (p.get("salary", 0), -player_grade(p)))

            for replacement in cheaper:
                new_salary = salary - current.get("salary", 0) + replacement.get("salary", 0)
                if new_salary <= salary:
                    used.remove(current["name"])
                    used.add(replacement["name"])
                    lineup[idx] = replacement
                    salary = new_salary
                    break

        return lineup

    candidate_lineups = []
    seen = set()
    attempts = max(80, count * 30)
    checked = 0

    for i in range(attempts):
        checked += 1
        lineup = []
        used = set()

        # Add locks first.
        for locked in locked_objects:
            if locked["name"] in used:
                continue
            if same_position_count(lineup, locked["position"]) >= required_position_count(locked["position"]):
                continue
            lineup.append(locked)
            used.add(locked["name"])

        # Use rotating offsets so 5/10/20 lineups are different but still fast.
        add_best_available(lineup, used, "P", i)
        add_best_available(lineup, used, "C", i + 1)
        add_best_available(lineup, used, "1B", i + 2)
        add_best_available(lineup, used, "2B", i + 3)
        add_best_available(lineup, used, "3B", i + 4)
        add_best_available(lineup, used, "SS", i + 5)
        add_best_available(lineup, used, "OF", i + 6)

        if len(lineup) != 10 or not lineup_position_valid(lineup):
            continue

        lineup = repair_salary(lineup, used)
        salary = sum(p.get("salary", 0) for p in lineup)

        if salary > SALARY_CAP:
            continue

        if not has_all_locked(lineup, locked_players):
            continue

        if not lineup_passes_advanced_rules(
            lineup=lineup,
            salary=salary,
            min_salary=request.min_salary,
            max_players_per_team=request.max_players_per_team,
            force_team_stack=request.force_team_stack or request.force_qb_stack,
            avoid_pitcher_vs_hitter=request.avoid_pitcher_vs_hitter if request.force_bring_back is None else bool(request.force_bring_back),
            mode=mode,
        ):
            continue

        key = lineup_key(lineup)
        if key in seen:
            continue
        seen.add(key)

        projection = sum(p.get("projection", 0) for p in lineup)
        score = score_lineup(lineup, mode, request.randomness)
        lineup_data = {
            "mode": mode,
            "total_salary": salary,
            "projected_points": round(projection, 2),
            "optimizer_score": round(score, 2),
            "lineup": lineup,
        }
        candidate_lineups.append(add_lineup_metadata(lineup_data))

        if len(candidate_lineups) >= max(count * 3, count):
            break

    candidate_lineups.sort(key=lambda x: x["optimizer_score"], reverse=True)

    if not candidate_lineups:
        # Fallback 1: relax advanced rules but still respect locks/excludes and active slate.
        for i in range(max(120, count * 40)):
            checked += 1
            lineup = []
            used = set()

            for locked in locked_objects:
                if locked["name"] in used:
                    continue
                if same_position_count(lineup, locked["position"]) >= required_position_count(locked["position"]):
                    continue
                lineup.append(locked)
                used.add(locked["name"])

            add_best_available(lineup, used, "P", i + 11)
            add_best_available(lineup, used, "C", i + 12)
            add_best_available(lineup, used, "1B", i + 13)
            add_best_available(lineup, used, "2B", i + 14)
            add_best_available(lineup, used, "3B", i + 15)
            add_best_available(lineup, used, "SS", i + 16)
            add_best_available(lineup, used, "OF", i + 17)

            if len(lineup) != 10 or not lineup_position_valid(lineup):
                continue

            lineup = repair_salary(lineup, used)
            salary = sum(p.get("salary", 0) for p in lineup)

            if salary > SALARY_CAP:
                continue
            if not has_all_locked(lineup, locked_players):
                continue

            key = lineup_key(lineup)
            if key in seen:
                continue
            seen.add(key)

            projection = sum(p.get("projection", 0) for p in lineup)
            score = score_lineup(lineup, mode, min(max(getattr(request, "randomness", 0), 0), 20))
            lineup_data = {
                "mode": mode,
                "total_salary": salary,
                "projected_points": round(projection, 2),
                "optimizer_score": round(score, 2),
                "lineup": lineup,
            }
            candidate_lineups.append(add_lineup_metadata(lineup_data))

            if len(candidate_lineups) >= max(count * 2, count):
                break

    if not candidate_lineups:
        # Fallback 2: include review/inactive players only as a last resort so the button returns a clear result.
        fallback_available = [p for p in players if p["name"] not in excluded_players]
        fallback_pool, fallback_trim = trim_player_pool(fallback_available, locked_players)
        old_groups = groups
        groups = {
            "P": [p for p in fallback_pool if p["position"] == "P"],
            "C": [p for p in fallback_pool if p["position"] == "C"],
            "1B": [p for p in fallback_pool if p["position"] == "1B"],
            "2B": [p for p in fallback_pool if p["position"] == "2B"],
            "3B": [p for p in fallback_pool if p["position"] == "3B"],
            "SS": [p for p in fallback_pool if p["position"] == "SS"],
            "OF": [p for p in fallback_pool if p["position"] == "OF"],
        }
        for key in groups:
            groups[key].sort(key=player_grade, reverse=True)

        for i in range(max(120, count * 40)):
            checked += 1
            lineup = []
            used = set()
            add_best_available(lineup, used, "P", i)
            add_best_available(lineup, used, "C", i + 1)
            add_best_available(lineup, used, "1B", i + 2)
            add_best_available(lineup, used, "2B", i + 3)
            add_best_available(lineup, used, "3B", i + 4)
            add_best_available(lineup, used, "SS", i + 5)
            add_best_available(lineup, used, "OF", i + 6)
            if len(lineup) != 10 or not lineup_position_valid(lineup):
                continue
            lineup = repair_salary(lineup, used)
            salary = sum(p.get("salary", 0) for p in lineup)
            if salary > SALARY_CAP:
                continue
            key = lineup_key(lineup)
            if key in seen:
                continue
            seen.add(key)
            projection = sum(p.get("projection", 0) for p in lineup)
            score = score_lineup(lineup, mode, 0)
            candidate_lineups.append(add_lineup_metadata({
                "mode": mode,
                "total_salary": salary,
                "projected_points": round(projection, 2),
                "optimizer_score": round(score, 2),
                "lineup": lineup,
                "lineup_warning": "Used fallback pool because active-only slate could not build a valid lineup.",
            }))
            if len(candidate_lineups) >= count:
                break
        trim_report = fallback_trim
        groups = old_groups

    if not candidate_lineups:
        return [], "No valid MLB lineups found. Auto cleanup may have removed too much of this slate. Re-upload CSV or reactivate players in Player Lab.", trim_report, checked

    candidate_lineups.sort(key=lambda x: x["optimizer_score"], reverse=True)

    selected = diversify_lineups(
        all_lineups=candidate_lineups,
        count=count,
        max_exposure=min(max(request.max_exposure, 20), 100),
        max_same_players=min(max(request.max_same_players, 3), 9),
        locked_players=locked_players,
        player_min_exposure=request.player_min_exposure,
        player_max_exposure=request.player_max_exposure,
    )

    return selected, None, trim_report, checked


def player_export_name(player):
    player_id = player.get("id") or player.get("ID") or player.get("player_id") or player.get("PlayerID")
    name = player.get("name", "")
    if player_id:
        return f"{name} ({player_id})"
    return name


def sort_lineup_for_export(lineup):
    pitchers = [p for p in lineup if p["position"] == "P"]
    catchers = [p for p in lineup if p["position"] == "C"]
    first_base = [p for p in lineup if p["position"] == "1B"]
    second_base = [p for p in lineup if p["position"] == "2B"]
    third_base = [p for p in lineup if p["position"] == "3B"]
    shortstops = [p for p in lineup if p["position"] == "SS"]
    outfielders = [p for p in lineup if p["position"] == "OF"]

    for group in [pitchers, catchers, first_base, second_base, third_base, shortstops, outfielders]:
        group.sort(key=lambda p: p.get("projection", 0), reverse=True)

    return {
        "P1": pitchers[0] if len(pitchers) > 0 else None,
        "P2": pitchers[1] if len(pitchers) > 1 else None,
        "C": catchers[0] if catchers else None,
        "1B": first_base[0] if first_base else None,
        "2B": second_base[0] if second_base else None,
        "3B": third_base[0] if third_base else None,
        "SS": shortstops[0] if shortstops else None,
        "OF1": outfielders[0] if len(outfielders) > 0 else None,
        "OF2": outfielders[1] if len(outfielders) > 1 else None,
        "OF3": outfielders[2] if len(outfielders) > 2 else None,
    }


def export_player_name(player):
    return player_export_name(player) if player else ""


def build_export_csv(lineups):
    output = io.StringIO()
    writer = csv.writer(output)

    # DraftKings upload-friendly first section.
    writer.writerow(["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"])

    for data in lineups:
        sorted_slots = sort_lineup_for_export(data["lineup"])
        writer.writerow([
            export_player_name(sorted_slots["P1"]),
            export_player_name(sorted_slots["P2"]),
            export_player_name(sorted_slots["C"]),
            export_player_name(sorted_slots["1B"]),
            export_player_name(sorted_slots["2B"]),
            export_player_name(sorted_slots["3B"]),
            export_player_name(sorted_slots["SS"]),
            export_player_name(sorted_slots["OF1"]),
            export_player_name(sorted_slots["OF2"]),
            export_player_name(sorted_slots["OF3"]),
        ])

    writer.writerow([])
    writer.writerow([])
    writer.writerow(["DFS EDGE MLB - ADVANCED DATA"])
    writer.writerow([
        "Lineup",
        "Salary",
        "Remaining",
        "Projection",
        "Score",
        "Best Stack",
        "Stack Size",
        "Pitcher Conflict",
        "Avg Ownership",
        "Avg Leverage",
        "Chalk Score",
        "Leverage Rating",
        "Boost Total",
        "Quality Score",
        "Win Probability",
        "Quality Label",
        "Explanation",
    ])

    for idx, data in enumerate(lineups):
        lineup = data["lineup"]
        total_salary = data.get("total_salary", 0)
        stack = best_stack_info(lineup)
        avg_own = round(sum(p.get("ownership", 0) for p in lineup) / len(lineup), 2) if lineup else 0
        boosts = data.get("boost_breakdown", lineup_boost_breakdown(lineup, data.get("mode", "cash")))

        writer.writerow([
            idx + 1,
            total_salary,
            SALARY_CAP - total_salary,
            data.get("projected_points", 0),
            data.get("optimizer_score", 0),
            stack["team"],
            stack["size"],
            "YES" if pitcher_vs_hitter_conflict(lineup) else "NO",
            avg_own,
            data.get("average_leverage_score", 0),
            data.get("average_chalk_score", 0),
            data.get("leverage_rating", ""),
            boosts.get("total_boost", 0),
            data.get("lineup_quality_score", 0),
            data.get("win_probability", 0),
            data.get("lineup_quality_label", ""),
            data.get("lineup_explanation", ""),
        ])

    return output.getvalue()


def normalize_contest_request(request: ContestSimulationRequest):
    # Field size / number of players in tournament.
    contest_size = safe_int(getattr(request, "contest_size", 0), 0)
    if contest_size <= 0:
        contest_size = safe_int(getattr(request, "field_size", 5000), 5000)
    contest_size = max(10, contest_size)

    # Entry fee / buy-in per entry.
    entry_fee = max(0.0, safe_float(getattr(request, "entry_fee", 5.0), 5.0))

    # Total prize pool. Keep top_prize fallback for older frontend builds.
    prize_pool = safe_float(getattr(request, "prize_pool", 0), 0)
    if prize_pool <= 0:
        prize_pool = safe_float(getattr(request, "top_prize", 1000.0), 1000.0)
    prize_pool = max(1.0, prize_pool)

    # Max entries allowed by contest. Single-entry contests are easier to rank in
    # than max-entry lottery fields, so this affects field pressure.
    max_entries = safe_int(getattr(request, "max_entries", 1), 1)
    max_entries = max(1, min(max_entries, 150))
    single_entry = bool(getattr(request, "single_entry", False)) or max_entries <= 1
    if single_entry:
        max_entries = 1

    # Paid positions can be entered directly. If not provided, fall back to
    # payout_rate / payout_percent.
    paid_positions = safe_int(getattr(request, "paid_positions", 0), 0)

    payout_rate = safe_float(getattr(request, "payout_rate", 0), 0)
    if payout_rate <= 0:
        payout_rate = safe_float(getattr(request, "payout_percent", 20.0), 20.0) / 100

    if paid_positions > 0:
        paid_positions = max(1, min(paid_positions, contest_size))
        payout_rate = paid_positions / contest_size
    else:
        payout_rate = max(0.01, min(payout_rate, 0.80))
        paid_positions = max(1, min(contest_size, round(contest_size * payout_rate)))

    return {
        "contest_size": contest_size,
        "field_size": contest_size,
        "payout_rate": round(payout_rate, 4),
        "payout_percent": round(payout_rate * 100, 2),
        "estimated_paid_spots": paid_positions,
        "paid_positions": paid_positions,
        "entry_fee": entry_fee,
        "prize_pool": prize_pool,
        "max_entries": max_entries,
        "single_entry": single_entry,
        "total_entry_cost": round(entry_fee * max_entries, 2),
    }


def select_player_from_group(group, used_names, offset=0):
    if not group:
        return None

    for step in range(len(group)):
        player = group[(offset + step) % len(group)]
        if player["name"] not in used_names:
            return player

    return None


def build_fast_simulator_portfolio(request: ContestSimulationRequest):
    count = request.count if request.count in [1, 5, 10, 20] else 1
    locked_players = request.locked_players or []
    excluded_players = request.excluded_players or []
    mode = str(request.mode or "gpp").lower()

    players = add_values(load_players())
    error = validate_locks(players, locked_players, excluded_players)
    if error:
        return [], error

    available = [
        p for p in players
        if p["name"] not in excluded_players and bool(p.get("active", True))
    ]
    optimized_pool, _ = trim_player_pool(available, locked_players)

    groups = {
        "P": [p for p in optimized_pool if p["position"] == "P"],
        "C": [p for p in optimized_pool if p["position"] == "C"],
        "1B": [p for p in optimized_pool if p["position"] == "1B"],
        "2B": [p for p in optimized_pool if p["position"] == "2B"],
        "3B": [p for p in optimized_pool if p["position"] == "3B"],
        "SS": [p for p in optimized_pool if p["position"] == "SS"],
        "OF": [p for p in optimized_pool if p["position"] == "OF"],
    }

    if len(groups["P"]) < 2 or not groups["C"] or not groups["1B"] or not groups["2B"] or not groups["3B"] or not groups["SS"] or len(groups["OF"]) < 3:
        return [], "Not enough players at each MLB position to run the simulator. Upload a larger DraftKings slate or clear filters."

    for key in groups:
        groups[key].sort(key=player_grade, reverse=True)

    pitcher_combos = list(combinations(groups["P"][:10], 2))
    pitcher_combos.sort(key=lambda combo: (sum(p.get("projection", 0) for p in combo), -sum(p.get("salary", 0) for p in combo)), reverse=True)

    lineups = []
    seen = set()

    for i in range(count * 4):
        if len(lineups) >= count:
            break

        used = set()
        lineup = []

        for locked_name in locked_players:
            locked = next((p for p in available if p["name"] == locked_name), None)
            if locked and locked["name"] not in used:
                lineup.append(locked)
                used.add(locked["name"])

        if len([p for p in lineup if p["position"] == "P"]) < 2:
            p_combo = pitcher_combos[i % len(pitcher_combos)]
            for pitcher in p_combo:
                if pitcher["name"] not in used and len([p for p in lineup if p["position"] == "P"]) < 2:
                    lineup.append(pitcher)
                    used.add(pitcher["name"])

        target_offsets = {
            "C": i,
            "1B": i + 1,
            "2B": i + 2,
            "3B": i + 3,
            "SS": i + 4,
        }

        for pos, offset in target_offsets.items():
            if any(p["position"] == pos for p in lineup):
                continue
            player = select_player_from_group(groups[pos], used, offset)
            if player:
                lineup.append(player)
                used.add(player["name"])

        of_needed = 3 - len([p for p in lineup if p["position"] == "OF"])
        of_offsets = [i, i + 3, i + 6, i + 9, i + 12]
        for offset in of_offsets:
            if of_needed <= 0:
                break
            player = select_player_from_group(groups["OF"], used, offset)
            if player:
                lineup.append(player)
                used.add(player["name"])
                of_needed -= 1

        if len(lineup) != 10:
            continue

        # If salary is too high, replace non-locked hitters with cheaper players at same position.
        salary = sum(p.get("salary", 0) for p in lineup)
        if salary > SALARY_CAP:
            locked_set = set(locked_players)
            for idx, current in sorted(list(enumerate(lineup)), key=lambda item: item[1].get("salary", 0), reverse=True):
                if salary <= SALARY_CAP:
                    break
                if current["name"] in locked_set:
                    continue
                pos = current["position"]
                cheaper_options = sorted(
                    [p for p in groups[pos] if p["name"] not in used and p.get("salary", 0) < current.get("salary", 0)],
                    key=lambda p: p.get("salary", 0),
                )
                if cheaper_options:
                    replacement = cheaper_options[0]
                    used.remove(current["name"])
                    used.add(replacement["name"])
                    salary = salary - current.get("salary", 0) + replacement.get("salary", 0)
                    lineup[idx] = replacement

        salary = sum(p.get("salary", 0) for p in lineup)
        if salary > SALARY_CAP:
            continue

        if not has_all_locked(lineup, locked_players):
            continue

        if not lineup_passes_advanced_rules(
            lineup=lineup,
            salary=salary,
            min_salary=request.min_salary,
            max_players_per_team=request.max_players_per_team,
            force_team_stack=request.force_team_stack or request.force_qb_stack,
            avoid_pitcher_vs_hitter=request.avoid_pitcher_vs_hitter if request.force_bring_back is None else bool(request.force_bring_back),
            mode=mode,
        ):
            continue

        key = lineup_key(lineup)
        if key in seen:
            continue
        seen.add(key)

        projection = sum(p.get("projection", 0) for p in lineup)
        score = score_lineup(lineup, mode, request.randomness)
        lineup_data = {
            "mode": mode,
            "total_salary": salary,
            "projected_points": round(projection, 2),
            "optimizer_score": round(score, 2),
            "lineup": lineup,
        }
        lineups.append(add_lineup_metadata(lineup_data))

    if not lineups:
        # Last fallback: use normal optimizer, but cap it by requesting only 1 lineup.
        all_lineups, error, _, _ = build_all_lineups(
            mode=mode,
            locked_players=locked_players,
            excluded_players=excluded_players,
            min_salary=request.min_salary,
            max_players_per_team=request.max_players_per_team,
            force_qb_stack=request.force_qb_stack,
            force_bring_back=request.force_bring_back,
            force_team_stack=request.force_team_stack,
            avoid_pitcher_vs_hitter=request.avoid_pitcher_vs_hitter,
            randomness=min(max(request.randomness, 0), 20),
        )
        if error:
            return [], error
        lineups = all_lineups[:count]

    return lineups[:count], None


def simulator_focus_from_request(request: ContestSimulationRequest, contest_size: int):
    raw = str(getattr(request, "contest_type", "") or "").lower().strip()
    mode = str(getattr(request, "mode", "gpp") or "gpp").lower().strip()

    if raw in ["cash", "cash_h2h", "h2h", "double_up", "cash_games"] or mode == "cash":
        return "cash_h2h"
    if raw in ["single_entry", "single_entry_gpp", "small_field", "small_field_gpp", "three_max", "3max"]:
        return "single_entry_gpp"
    if raw in ["big_gpp", "big_field_gpp", "large_gpp", "large_field_gpp", "massive_gpp", "tournament"]:
        return "big_field_gpp"

    if contest_size >= 20000:
        return "big_field_gpp"
    if contest_size <= 2500:
        return "single_entry_gpp"
    return "single_entry_gpp"


def simulator_focus_label(focus: str):
    if focus == "cash_h2h":
        return "Cash / H2H"
    if focus == "big_field_gpp":
        return "Big Field GPP"
    return "Single Entry GPP"



def payout_for_rank(rank, contest):
    """
    Approximate a realistic DFS payout curve when the user enters only contest
    size, paid spots, prize pool, and buy-in. This is not a sportsbook/provider
    payout table, but it behaves like common DFS tournaments:
    - Cash/H2H: flatter min-cash style payout.
    - Single-entry GPP: moderately top-heavy.
    - Massive-field GPP: very top-heavy.
    """
    contest_size = max(1, safe_int(contest.get("contest_size", 1), 1))
    paid_spots = max(1, safe_int(contest.get("estimated_paid_spots", 1), 1))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 1.0), 1.0))
    prize_pool = max(1.0, safe_float(contest.get("prize_pool", 1.0), 1.0))
    max_entries = max(1, safe_int(contest.get("max_entries", 1), 1))
    single_entry = bool(contest.get("single_entry", False))

    rank = max(1, min(safe_int(rank, contest_size), contest_size))
    if rank > paid_spots:
        return 0.0

    payout_rate = paid_spots / contest_size

    # Cash/H2H/double-up style contests should not use top-heavy GPP payouts.
    if payout_rate >= 0.45 and max_entries == 1:
        return round(max(entry_fee * 1.75, prize_pool / max(paid_spots, 1)), 2)

    min_cash = max(entry_fee * 1.5, prize_pool * 0.00035)

    if contest_size >= 100000:
        top_pct = 0.22
        curve_alpha = 4.2
    elif contest_size >= 25000 or max_entries >= 50:
        top_pct = 0.18
        curve_alpha = 3.65
    elif single_entry:
        top_pct = 0.10
        curve_alpha = 2.65
    else:
        top_pct = 0.14
        curve_alpha = 3.05

    top_prize = max(entry_fee * 25, prize_pool * top_pct)
    if paid_spots <= 1:
        return round(min(top_prize, prize_pool), 2)

    # rank_position = 1.0 for 1st, 0.0 for last paid.
    rank_position = (paid_spots - rank) / max(paid_spots - 1, 1)
    payout = min_cash + (top_prize - min_cash) * (rank_position ** curve_alpha)

    # Keep individual payout within the actual prize pool.
    return round(max(0.0, min(payout, prize_pool)), 2)


def estimate_expected_payout_from_probabilities(contest, projected_rank, ceiling_rank, cash_probability, top_10_probability, top_1_probability, top_0_1_probability):
    contest_size = max(1, safe_int(contest.get("contest_size", 1), 1))
    paid_spots = max(1, safe_int(contest.get("estimated_paid_spots", 1), 1))

    p_cash = max(0.0, min(1.0, safe_float(cash_probability, 0) / 100.0))
    p_top10 = max(0.0, min(p_cash, safe_float(top_10_probability, 0) / 100.0))
    p_top1 = max(0.0, min(p_top10, safe_float(top_1_probability, 0) / 100.0))
    p_top01 = max(0.0, min(p_top1, safe_float(top_0_1_probability, 0) / 100.0))

    # Convert cumulative probabilities into non-overlapping buckets.
    bucket_top01 = p_top01
    bucket_top1 = max(0.0, p_top1 - p_top01)
    bucket_top10 = max(0.0, p_top10 - p_top1)
    bucket_cash = max(0.0, p_cash - p_top10)

    rank_top01 = max(1, round(contest_size * 0.0005))
    rank_top1 = max(1, round(contest_size * 0.005))
    rank_top10 = max(1, round(contest_size * 0.05))
    rank_cash = max(1, round((paid_spots + max(rank_top10, 1)) / 2))

    expected = (
        bucket_top01 * payout_for_rank(rank_top01, contest)
        + bucket_top1 * payout_for_rank(rank_top1, contest)
        + bucket_top10 * payout_for_rank(rank_top10, contest)
        + bucket_cash * payout_for_rank(rank_cash, contest)
    )

    projected_payout = payout_for_rank(projected_rank, contest)
    ceiling_payout = payout_for_rank(ceiling_rank, contest)

    # Blend model EV with rank-based payout so the shown projected rank and payout
    # agree with each other. The probabilities still drive upside EV.
    expected = expected * 0.72 + projected_payout * 0.18 + ceiling_payout * 0.10

    return {
        "expected_payout": round(expected, 2),
        "projected_payout": round(projected_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "min_cash_payout": payout_for_rank(paid_spots, contest),
        "top_10_rank_payout": payout_for_rank(max(1, round(contest_size * 0.10)), contest),
        "top_1_rank_payout": payout_for_rank(max(1, round(contest_size * 0.01)), contest),
        "top_0_1_rank_payout": payout_for_rank(max(1, round(contest_size * 0.001)), contest),
    }

def simulate_single_lineup(lineup_data, request: ContestSimulationRequest, lineup_number=1):
    contest = normalize_contest_request(request)
    lineup = lineup_data.get("lineup", [])
    projection = safe_float(lineup_data.get("boosted_projection", lineup_data.get("projected_points", 0)))
    raw_projection = safe_float(lineup_data.get("projected_points", projection))

    ownership = safe_float(lineup_data.get("average_ownership", 0))
    if ownership <= 0 and lineup:
        ownership = sum(safe_float(p.get("ownership", 10)) for p in lineup) / len(lineup)

    stack = best_stack_info(lineup)
    stack_size = safe_int(lineup_data.get("best_stack_size", stack["size"]))
    stack_team = lineup_data.get("best_stack_team", stack["team"])

    contest_size = contest["contest_size"]
    paid_spots = contest["estimated_paid_spots"]
    entry_fee = max(0.01, contest["entry_fee"])
    prize_pool = max(1.0, contest["prize_pool"])
    payout_rate = safe_float(contest.get("payout_rate", 0.20), 0.20)
    max_entries = safe_int(contest.get("max_entries", 1), 1)
    single_entry = bool(contest.get("single_entry", False))
    total_entry_cost = safe_float(contest.get("total_entry_cost", entry_fee), entry_fee)
    focus = simulator_focus_from_request(request, contest_size)
    mode = "cash" if focus == "cash_h2h" else "gpp"

    quality_profile = lineup_quality_profile(lineup, mode)
    quality_score = safe_float(quality_profile.get("lineup_quality_score", 0), 0)
    win_probability = safe_float(quality_profile.get("win_probability", 0), 0)
    quality_label = quality_profile.get("lineup_quality_label", "Playable")
    breakdown = quality_profile.get("lineup_quality_breakdown", {})

    core_profile = lineup_core_profile(lineup)
    core_count = safe_int(core_profile.get("core_play_count", 0), 0)
    strong_count = safe_int(core_profile.get("strong_play_count", 0), 0)
    fade_count = safe_int(core_profile.get("fade_count", 0), 0)
    bad_chalk_count = safe_int(core_profile.get("bad_chalk_count", 0), 0)

    leverage_points = max(0.0, 22.0 - ownership)
    chalk_penalty = max(0.0, ownership - 26.0)
    conflict_penalty = 7.5 if pitcher_vs_hitter_conflict(lineup) else 0.0
    salary_remaining = SALARY_CAP - safe_int(lineup_data.get("total_salary", 0), 0)
    salary_efficiency = 4.0 if 0 <= salary_remaining <= 900 else (1.5 if salary_remaining <= 1800 else -1.0)

    stack_correlation = 0.0
    if stack_size >= 5:
        stack_correlation = 18.0
    elif stack_size == 4:
        stack_correlation = 13.0
    elif stack_size == 3:
        stack_correlation = 7.5

    secondary_stack_bonus = 0.0
    team_counts = stack.get("counts", {}) if isinstance(stack, dict) else {}
    if any(2 <= count < stack_size for count in team_counts.values()):
        secondary_stack_bonus = 5.0

    ceiling_base = (
        projection
        + stack_correlation
        + secondary_stack_bonus
        + leverage_points * 0.9
        + core_count * 1.8
        + strong_count * 0.8
        + salary_efficiency
        - fade_count * 4.0
        - bad_chalk_count * 3.2
        - conflict_penalty
    )

    floor_base = max(
        0,
        projection
        - (10.0 if focus == "cash_h2h" else 14.0)
        + core_count * 0.9
        - fade_count * 2.5
        - conflict_penalty
    )

    cash_safety_score = max(1.0, min(99.0, (
        projection * 0.62
        + quality_score * 0.34
        + max(0, 20 - ownership) * 0.35
        + salary_efficiency * 1.4
        - conflict_penalty * 2.0
        - fade_count * 5.0
    )))

    single_entry_edge_score = max(1.0, min(99.0, (
        projection * 0.40
        + quality_score * 0.38
        + stack_correlation * 0.55
        + leverage_points * 0.55
        + core_count * 2.3
        - bad_chalk_count * 4.2
        - conflict_penalty * 1.5
    )))

    big_gpp_ceiling_score = max(1.0, min(99.0, (
        ceiling_base * 0.46
        + quality_score * 0.24
        + stack_correlation * 0.92
        + secondary_stack_bonus * 0.8
        + leverage_points * 1.15
        + core_count * 1.5
        - chalk_penalty * 0.9
        - fade_count * 3.2
        - conflict_penalty * 1.15
    )))

    if focus == "cash_h2h":
        focus_score = cash_safety_score
        simulated_floor = round(floor_base + 5.0, 2)
        simulated_ceiling = round(ceiling_base + 4.0, 2)
        cash_probability = max(5.0, min(98.0, cash_safety_score * 0.86 + (projection - 72) * 0.45))
        top_10_probability = max(3.0, min(55.0, single_entry_edge_score * 0.38))
        top_1_probability = max(0.1, min(18.0, big_gpp_ceiling_score * 0.12))
        top_0_1_probability = max(0.01, min(4.0, top_1_probability * 0.11))
        rank_strength = cash_safety_score * 0.76 + projection * 0.18 + quality_score * 0.12
        recommendation = "Cash Core" if cash_probability >= 72 else ("Cash Viable" if cash_probability >= 58 else "Cash Risk")
    elif focus == "big_field_gpp":
        focus_score = big_gpp_ceiling_score
        simulated_floor = round(max(0, floor_base - 3.5), 2)
        simulated_ceiling = round(ceiling_base + 12.0 + max(0, stack_size - 3) * 2.0, 2)
        cash_probability = max(1.0, min(72.0, cash_safety_score * 0.48 + projection * 0.08))
        top_10_probability = max(2.0, min(80.0, big_gpp_ceiling_score * 0.72 + leverage_points * 0.8 + stack_correlation * 0.35 - bad_chalk_count * 2.0))
        top_1_probability = max(0.1, min(45.0, big_gpp_ceiling_score * 0.32 + leverage_points * 0.48 + max(0, stack_size - 3) * 2.1 - bad_chalk_count * 1.5))
        top_0_1_probability = max(0.01, min(12.0, top_1_probability * 0.18 + max(0, stack_size - 4) * 0.75 + leverage_points * 0.08))
        rank_strength = big_gpp_ceiling_score * 0.82 + top_1_probability * 0.8 + top_0_1_probability * 2.6
        recommendation = "Massive GPP Winner Profile" if top_0_1_probability >= 4.0 or top_1_probability >= 18 else ("Big GPP Upside" if top_1_probability >= 8 else "Needs More Ceiling")
    else:
        focus_score = single_entry_edge_score
        simulated_floor = round(floor_base + 1.5, 2)
        simulated_ceiling = round(ceiling_base + 7.0, 2)
        cash_probability = max(3.0, min(88.0, cash_safety_score * 0.62 + projection * 0.10))
        top_10_probability = max(4.0, min(72.0, single_entry_edge_score * 0.64 + stack_correlation * 0.25))
        top_1_probability = max(0.1, min(32.0, single_entry_edge_score * 0.22 + big_gpp_ceiling_score * 0.12 + leverage_points * 0.25))
        top_0_1_probability = max(0.01, min(7.0, top_1_probability * 0.14 + max(0, stack_size - 3) * 0.4))
        rank_strength = single_entry_edge_score * 0.76 + quality_score * 0.18 + top_1_probability * 0.55
        recommendation = "Single Entry Hammer" if single_entry_edge_score >= 82 else ("Strong Single Entry" if single_entry_edge_score >= 70 else "Playable")

    # Larger contests and multi-entry formats are harder to beat.
    # Single-entry lowers the pressure because the field cannot brute-force 150 builds.
    entry_pressure = math.log10(max(max_entries, 1)) * 4.2
    if single_entry:
        entry_pressure *= 0.25

    payout_pressure = 0.0
    if payout_rate < 0.18:
        payout_pressure += (0.18 - payout_rate) * 90
    elif payout_rate > 0.22:
        payout_pressure -= min(8.0, (payout_rate - 0.22) * 55)

    field_pressure = math.log10(max(contest_size, 100)) * 8.0 + entry_pressure + payout_pressure
    normalized_strength = max(1.0, min(99.0, rank_strength - field_pressure + 30.0))
    projected_rank_ratio = max(0.0008, min(0.985, 1.0 - (normalized_strength / 112.0)))
    projected_rank = max(1, min(contest_size, round(contest_size * projected_rank_ratio)))

    ceiling_rank_ratio = max(0.00005, min(0.85, projected_rank_ratio * (0.34 if focus == "big_field_gpp" else 0.42) - (top_1_probability / 1000.0) - (top_0_1_probability / 600.0)))
    ceiling_rank = max(1, min(contest_size, round(contest_size * ceiling_rank_ratio)))

    # Make probabilities contest-aware.
    # More paid spots helps min-cash probability. Multi-entry fields make top-end outcomes harder.
    payout_adjustment = max(0.55, min(1.55, payout_rate / 0.20))
    entry_adjustment = 1.0 + (0.08 if single_entry else 0.0) - min(0.30, math.log10(max(max_entries, 1)) * 0.055)
    cash_probability = max(0.5, min(99.0, cash_probability * payout_adjustment))
    top_10_probability = max(0.1, min(85.0, top_10_probability * entry_adjustment))
    top_1_probability = max(0.01, min(50.0, top_1_probability * entry_adjustment))
    top_0_1_probability = max(0.001, min(15.0, top_0_1_probability * entry_adjustment))

    payout_model = estimate_expected_payout_from_probabilities(
        contest=contest,
        projected_rank=projected_rank,
        ceiling_rank=ceiling_rank,
        cash_probability=cash_probability,
        top_10_probability=top_10_probability,
        top_1_probability=top_1_probability,
        top_0_1_probability=top_0_1_probability,
    )
    expected_payout = safe_float(payout_model.get("expected_payout", 0), 0)
    projected_payout = safe_float(payout_model.get("projected_payout", 0), 0)
    ceiling_payout = safe_float(payout_model.get("ceiling_payout", 0), 0)
    expected_value = round(expected_payout - entry_fee, 2)
    roi_percent = round((expected_value / entry_fee) * 100, 1) if entry_fee > 0 else 0
    max_entry_expected_value = round(expected_value * max_entries, 2)
    max_entry_roi_percent = round((max_entry_expected_value / total_entry_cost) * 100, 1) if total_entry_cost > 0 else roi_percent

    tournament_rating = recommendation
    if focus == "big_field_gpp" and top_0_1_probability >= 5:
        tournament_rating = "Nuclear Upside"
    elif focus == "single_entry_gpp" and single_entry_edge_score >= 86:
        tournament_rating = "SE Winner Profile"
    elif focus == "cash_h2h" and cash_probability >= 75:
        tournament_rating = "Cash Lockbox"

    simulation = {
        "simulator_focus": focus,
        "simulator_focus_label": simulator_focus_label(focus),
        "contest_focus_score": round(focus_score, 1),
        "cash_safety_score": round(cash_safety_score, 1),
        "single_entry_edge_score": round(single_entry_edge_score, 1),
        "big_gpp_ceiling_score": round(big_gpp_ceiling_score, 1),
        "projected_rank": projected_rank,
        "ceiling_rank": ceiling_rank,
        "cash_cutoff_rank": paid_spots,
        "cash_probability": round(cash_probability, 1),
        "top_0_1_probability": round(top_0_1_probability, 2),
        "top_1_probability": round(top_1_probability, 1),
        "top_1_percent_probability": round(top_1_probability, 1),
        "top_10_probability": round(top_10_probability, 1),
        "simulated_floor": simulated_floor,
        "simulated_ceiling": simulated_ceiling,
        "roi_percent": roi_percent,
        "estimated_roi_percent": roi_percent,
        "expected_value": expected_value,
        "expected_payout": round(expected_payout, 2),
        "projected_payout": round(projected_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "min_cash_payout": payout_model.get("min_cash_payout", 0),
        "top_10_rank_payout": payout_model.get("top_10_rank_payout", 0),
        "top_1_rank_payout": payout_model.get("top_1_rank_payout", 0),
        "top_0_1_rank_payout": payout_model.get("top_0_1_rank_payout", 0),
        "max_entry_expected_value": max_entry_expected_value,
        "max_entry_roi_percent": max_entry_roi_percent,
        "buy_in_per_entry": round(entry_fee, 2),
        "max_entries": max_entries,
        "single_entry": single_entry,
        "total_entry_cost": round(total_entry_cost, 2),
        "paid_positions": paid_spots,
        "payout_rate": round(payout_rate, 4),
        "best_stack_team": stack_team,
        "best_stack_size": stack_size,
        "average_ownership": round(ownership, 2),
        "recommendation": recommendation,
        "tournament_rating": tournament_rating,
        "raw_projection": round(raw_projection, 2),
        "boosted_projection": round(projection, 2),
        "lineup_quality_score": round(quality_score, 1),
        "win_probability": round(win_probability, 1),
        "lineup_quality_label": quality_label,
        "lineup_quality_breakdown": breakdown,
        "lineup_iq_score": round(quality_score, 1),
        "lineup_iq_label": quality_label,
        "lineup_iq": {
            "projection": breakdown.get("projection_score", 0),
            "ceiling": breakdown.get("ceiling_score", 0),
            "leverage": breakdown.get("leverage_score", 0),
            "stack_strength": breakdown.get("stack_score", 0),
            "core": breakdown.get("core_score", 0),
            "salary": breakdown.get("salary_score", 0),
            "safety": breakdown.get("safety_score", 0),
            "fade_penalty": breakdown.get("fade_penalty", 0),
            "bad_chalk_penalty": breakdown.get("bad_chalk_penalty", 0),
        },
        "stack_score": breakdown.get("stack_score", 0),
        "leverage_score": breakdown.get("leverage_score", 0),
        "ceiling_score": breakdown.get("ceiling_score", 0),
        "safety_score": breakdown.get("safety_score", 0),
    }

    return {
        "lineup_number": lineup_number,
        "lineup": lineup_data,
        "simulation": simulation,
    }


def simulate_contest_payload(request: ContestSimulationRequest):
    lineups = request.lineups or []

    if lineups:
        normalized_lineups = []
        for item in lineups:
            if isinstance(item, dict) and "lineup" in item:
                normalized_lineups.append(item)
        lineups = normalized_lineups

    if not lineups:
        lineups, error = build_fast_simulator_portfolio(request)
        if error:
            return {"success": False, "error": error, "results": [], "simulations": []}

    results = [simulate_single_lineup(lineup, request, index + 1) for index, lineup in enumerate(lineups)]
    results.sort(key=lambda item: (item["simulation"].get("contest_focus_score", 0), item["simulation"].get("roi_percent", 0), item["simulation"].get("top_1_probability", 0)), reverse=True)

    if not results:
        return {"success": False, "error": "No lineups available for simulation.", "results": [], "simulations": []}

    contest = normalize_contest_request(request)
    rois = [safe_float(item["simulation"].get("roi_percent", 0)) for item in results]
    cash_probs = [safe_float(item["simulation"].get("cash_probability", 0)) for item in results]
    evs = [safe_float(item["simulation"].get("expected_value", 0)) for item in results]
    expected_payouts = [safe_float(item["simulation"].get("expected_payout", 0)) for item in results]
    quality_scores = [safe_float(item["simulation"].get("lineup_quality_score", 0)) for item in results]
    win_probs = [safe_float(item["simulation"].get("win_probability", 0)) for item in results]
    focus_scores = [safe_float(item["simulation"].get("contest_focus_score", 0)) for item in results]
    top_point_one = [safe_float(item["simulation"].get("top_0_1_probability", 0)) for item in results]
    top_ones = [safe_float(item["simulation"].get("top_1_probability", 0)) for item in results]
    best = results[0]["simulation"]

    summary = {
        "lineup_count": len(results),
        "average_roi_percent": round(sum(rois) / len(rois), 1),
        "average_cash_probability": round(sum(cash_probs) / len(cash_probs), 1),
        "average_lineup_quality": round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0,
        "average_win_probability": round(sum(win_probs) / len(win_probs), 1) if win_probs else 0,
        "best_lineup_quality": round(max(quality_scores), 1) if quality_scores else 0,
        "best_win_probability": round(max(win_probs), 1) if win_probs else 0,
        "average_focus_score": round(sum(focus_scores) / len(focus_scores), 1) if focus_scores else 0,
        "best_focus_score": round(max(focus_scores), 1) if focus_scores else 0,
        "best_top_0_1_probability": round(max(top_point_one), 2) if top_point_one else 0,
        "best_top_1_probability": round(max(top_ones), 1) if top_ones else 0,
        "simulator_focus": best.get("simulator_focus", simulator_focus_from_request(request, contest["contest_size"])),
        "simulator_focus_label": best.get("simulator_focus_label", simulator_focus_label(simulator_focus_from_request(request, contest["contest_size"]))),
        "estimated_total_ev": round(sum(evs), 2),
        "average_expected_payout": round(sum(expected_payouts) / len(expected_payouts), 2) if expected_payouts else 0,
        "best_expected_payout": round(max(expected_payouts), 2) if expected_payouts else 0,
        "best_projected_payout": best.get("projected_payout", 0),
        "best_ceiling_payout": best.get("ceiling_payout", 0),
        "best_recommendation": best.get("recommendation", "Playable"),
        "best_roi_percent": best.get("roi_percent", 0),
    }

    return {
        "success": True,
        "contest_type": request.contest_type,
        "contest": contest,
        "summary": summary,
        "results": results,
        "simulations": [item["simulation"] for item in results],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }



@app.get("/data-engine/status")
def data_engine_status():
    players = add_values(load_players())
    active_players = [p for p in players if bool(p.get("active", True))]
    review_players = [p for p in active_players if p.get("auto_active_recommendation") == "review"]
    inactive_recommended = [p for p in active_players if p.get("auto_active_recommendation") == "inactive"]

    return {
        "success": True,
        "version": DATA_ENGINE_VERSION,
        "sources": DATA_ENGINE_SOURCES,
        "player_count": len(players),
        "active_player_count": len(active_players),
        "review_count": len(review_players),
        "inactive_recommendation_count": len(inactive_recommended),
        "fields_added": [
            "starter_status",
            "injury_status",
            "lineup_spot",
            "avg_at_bats",
            "projected_innings",
            "pull_risk",
            "park_factor",
            "weather_risk",
            "batter_vs_pitcher",
            "trend_score",
            "data_engine_boost",
            "auto_active_recommendation",
        ],
        "note": "Currently uses deterministic MVP estimates unless paid/odds/weather API keys are connected.",
    }


@app.post("/data-engine/enrich-slate")
def enrich_active_slate(request: AdminPasswordRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}

    enriched_players, cleanup_stats = apply_auto_slate_cleanup(load_players(), respect_manual_overrides=True)
    save_active_slate(enriched_players)

    review_count = len([p for p in enriched_players if p.get("auto_active_recommendation") == "review"])
    inactive_recommendation_count = len([p for p in enriched_players if p.get("auto_active_recommendation") == "inactive"])

    return {
        "success": True,
        "message": "Slate enriched and auto-cleaned with MLB Data Engine fields.",
        "player_count": len(enriched_players),
        "active_player_count": cleanup_stats["active_count"],
        "inactive_player_count": cleanup_stats["inactive_count"],
        "cleanup_stats": cleanup_stats,
        "review_count": review_count,
        "inactive_recommendation_count": inactive_recommendation_count,
        "version": DATA_ENGINE_VERSION,
    }


@app.get("/data-engine/player/{player_name}")
def data_engine_player(player_name: str):
    target = player_name.strip().lower()
    players = add_values(load_players())

    for player in players:
        if str(player.get("name", "")).strip().lower() == target:
            return {
                "success": True,
                "player": player,
                "data_engine": {
                    "starter_status": player.get("starter_status"),
                    "injury_status": player.get("injury_status"),
                    "lineup_spot": player.get("lineup_spot"),
                    "avg_at_bats": player.get("avg_at_bats"),
                    "projected_innings": player.get("projected_innings"),
                    "pull_risk": player.get("pull_risk"),
                    "park_factor": player.get("park_factor"),
                    "weather_risk": player.get("weather_risk"),
                    "batter_vs_pitcher": player.get("batter_vs_pitcher"),
                    "trend_score": player.get("trend_score"),
                    "data_engine_boost": player.get("data_engine_boost"),
                    "data_engine_reasons": player.get("data_engine_reasons"),
                    "auto_active_recommendation": player.get("auto_active_recommendation"),
                    "source_notes": player.get("source_notes"),
                },
            }

    return {"success": False, "error": "Player not found."}


def normalize_email(email):
    return str(email or "").strip().lower()


def hash_password(password):
    return hashlib.sha256(str(password or "").encode("utf-8")).hexdigest()


def make_auth_token(email, password_hash):
    raw = f"{normalize_email(email)}:{password_hash}:dfs_edge_mlb_local_auth"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_users():
    if not USERS_PATH.exists():
        return {}
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_users(users):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def role_for_email(email, requested_role="free"):
    email = normalize_email(email)
    if email == ADMIN_EMAIL:
        return "admin"
    role = str(requested_role or "free").lower().strip()
    if role in ["free", "pro"]:
        return role
    return "free"


def user_public_payload(user):
    role = user.get("role", "free")
    return {
        "email": user.get("email", ""),
        "role": role,
        "is_admin": role == "admin",
        "is_pro": role in ["pro", "admin"],
        "subscription_status": "active" if role in ["pro", "admin"] else user.get("subscription_status", "free"),
        "pro_requested": bool(user.get("pro_requested", False)),
        "saved_lineup_count": len(user.get("saved_lineups", [])),
    }


def ensure_admin_user():
    users = load_users()
    email = ADMIN_EMAIL
    password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
    existing = users.get(email, {})

    # Local MVP rule: admin email is always admin.
    # If no admin exists yet, create it with DEFAULT_ADMIN_PASSWORD.
    # If it already exists, keep its existing password unless it has no password hash.
    if existing.get("password_hash"):
        password_hash = existing["password_hash"]

    users[email] = {
        "email": email,
        "password_hash": password_hash,
        "token": make_auth_token(email, password_hash),
        "role": "admin",
        "subscription_status": "active",
        "pro_requested": False,
        "saved_lineups": existing.get("saved_lineups", []) if isinstance(existing.get("saved_lineups", []), list) else [],
        "created_at": existing.get("created_at", datetime.utcnow().isoformat() + "Z"),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    save_users(users)


def find_user_by_token(token):
    users = load_users()
    for email, user in users.items():
        if user.get("token") == token:
            return email, user, users
    return "", None, users


@app.post("/auth/register")
def register_user(request: RegisterRequest):
    email = normalize_email(request.email)
    password = str(request.password or "")

    if not email or "@" not in email:
        return {"success": False, "error": "Enter a valid email address."}
    if len(password) < 6:
        return {"success": False, "error": "Password must be at least 6 characters."}

    users = load_users()
    if email in users:
        return {"success": False, "error": "An account already exists for this email. Log in instead."}

    password_hash = hash_password(password)
    role = role_for_email(email)
    token = make_auth_token(email, password_hash)
    user = {
        "email": email,
        "password_hash": password_hash,
        "token": token,
        "role": role,
        "subscription_status": "active" if role in ["pro", "admin"] else "free",
        "pro_requested": False,
        "saved_lineups": [],
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    users[email] = user
    save_users(users)

    return {"success": True, "token": token, "user": user_public_payload(user)}


@app.post("/auth/login")
def login_user(request: LoginRequest):
    email = normalize_email(request.email)
    password_hash = hash_password(request.password)
    users = load_users()

    # Make sure the admin account always exists before login attempts.
    if email == ADMIN_EMAIL and email not in users:
        ensure_admin_user()
        users = load_users()

    user = users.get(email)
    if not user or user.get("password_hash") != password_hash:
        return {"success": False, "error": "Invalid email or password."}

    user["role"] = role_for_email(email, user.get("role", "free"))
    user["token"] = make_auth_token(email, user.get("password_hash", password_hash))
    user["updated_at"] = datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)

    return {"success": True, "token": user["token"], "user": user_public_payload(user)}


@app.post("/auth/me")
def auth_me(request: AuthTokenRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Session expired. Please log in again."}
    user["role"] = role_for_email(email, user.get("role", "free"))
    users[email] = user
    save_users(users)
    return {"success": True, "user": user_public_payload(user)}


@app.post("/auth/logout")
def logout_user(request: AuthTokenRequest):
    return {"success": True, "message": "Logged out."}



@app.post("/subscription/status")
def subscription_status(request: AuthTokenRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Log in to view subscription status."}

    user["role"] = role_for_email(email, user.get("role", "free"))
    if user["role"] in ["pro", "admin"]:
        user["subscription_status"] = "active"
        user["pro_requested"] = False
    else:
        user["subscription_status"] = user.get("subscription_status", "free")
    users[email] = user
    save_users(users)

    return {
        "success": True,
        "user": user_public_payload(user),
        "plan": {
            "free": {
                "price": 0,
                "lineups": 1,
                "features": ["1 basic lineup", "basic player pool", "local saves"],
            },
            "pro": {
                "price": 19.99,
                "billing": "monthly",
                "billing_provider": "pending_google_play",
                "features": [
                    "5 / 10 / 20 lineups",
                    "AI Picks + Auto Lineup Builder",
                    "Contest-specific simulator",
                    "Ownership drift + Vegas movement",
                    "Late swap + lineup fixer",
                    "DraftKings CSV export",
                ],
            },
        },
        "message": "Google Play subscriptions are not connected yet. MVP Pro access is role-based until launch.",
    }


@app.post("/subscription/request-pro")
def request_pro_subscription(request: AuthTokenRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Log in before requesting Pro access."}

    user["role"] = role_for_email(email, user.get("role", "free"))
    if user["role"] in ["pro", "admin"]:
        user["subscription_status"] = "active"
        users[email] = user
        save_users(users)
        return {"success": True, "message": "Pro access is already active.", "user": user_public_payload(user)}

    user["subscription_status"] = "pending_manual_approval"
    user["pro_requested"] = True
    user["pro_requested_at"] = datetime.utcnow().isoformat() + "Z"
    user["updated_at"] = datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)

    return {
        "success": True,
        "message": "Pro request submitted. Until Google Play Billing is connected, the admin can approve this account manually.",
        "user": user_public_payload(user),
    }


@app.post("/admin/set-user-role")
def set_user_role(request: UpdateUserRoleRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}

    email = normalize_email(request.email)
    role = str(request.role or "free").lower().strip()
    if role not in ["free", "pro", "admin"]:
        return {"success": False, "error": "Role must be free, pro, or admin."}

    users = load_users()
    user = users.get(email)
    if not user:
        return {"success": False, "error": "User not found. They need to create an account first."}

    user["role"] = role_for_email(email, role)
    user["subscription_status"] = "active" if user["role"] in ["pro", "admin"] else "free"
    user["pro_requested"] = False if user["role"] in ["pro", "admin"] else bool(user.get("pro_requested", False))
    user["updated_at"] = datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)
    return {"success": True, "message": f"{email} is now {user['role']}.", "user": user_public_payload(user)}


@app.post("/user/save-lineup")
def save_user_lineup(request: SaveLineupRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Log in before saving lineups."}

    session = dict(request.session or {})
    if not session:
        return {"success": False, "error": "No lineup session was provided."}

    session["saved_by"] = email
    session["server_saved_at"] = datetime.utcnow().isoformat() + "Z"
    saved = user.get("saved_lineups", [])
    if not isinstance(saved, list):
        saved = []
    user["saved_lineups"] = [session] + saved[:49]
    user["updated_at"] = datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)
    return {"success": True, "message": "Lineup saved to your account.", "saved_lineups": user["saved_lineups"], "saved_lineup_count": len(user["saved_lineups"])}


@app.post("/user/saved-lineups")
def get_user_saved_lineups(request: AuthTokenRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Log in to load saved lineups.", "saved_lineups": []}
    saved = user.get("saved_lineups", [])
    if not isinstance(saved, list):
        saved = []
    return {"success": True, "saved_lineups": saved, "saved_lineup_count": len(saved)}


@app.post("/user/clear-saved-lineups")
def clear_user_saved_lineups(request: AuthTokenRequest):
    email, user, users = find_user_by_token(request.token)
    if not user:
        return {"success": False, "error": "Log in to clear saved lineups."}
    user["saved_lineups"] = []
    user["updated_at"] = datetime.utcnow().isoformat() + "Z"
    users[email] = user
    save_users(users)
    return {"success": True, "message": "Saved lineups cleared.", "saved_lineups": []}




def compact_ai_player(player):
    return {
        "name": player.get("name", ""),
        "position": player.get("position", ""),
        "team": player.get("team", ""),
        "opponent": player.get("opponent", ""),
        "salary": player.get("salary", 0),
        "projection": player.get("projection", 0),
        "ownership": player.get("ownership", 0),
        "leverage_score": player.get("leverage_score", 0),
        "chalk_score": player.get("chalk_score", 0),
        "core_play_score": player.get("core_play_score", 0),
        "core_play_label": player.get("core_play_label", "Neutral"),
        "core_play_tier": player.get("core_play_tier", "neutral"),
        "market_signal": player.get("market_signal", "Neutral"),
        "trend_score": player.get("trend_score", 50),
        "team_total": player.get("team_total", 4.2),
        "vegas_boost": player.get("vegas_boost", 0),
        "market_boost": player.get("market_boost", 0),
        "data_engine_boost": player.get("data_engine_boost", 0),
        "ai_pick_score": player.get("ai_pick_score", 0),
        "ai_pick_label": player.get("ai_pick_label", "Watch"),
        "ai_reasons": player.get("ai_reasons", []),
    }


def ai_pick_profile_for_player(player):
    projection = safe_float(player.get("projection", 0), 0)
    leverage = safe_float(player.get("leverage_score", 50), 50)
    core = safe_float(player.get("core_play_score", 50), 50)
    chalk = safe_float(player.get("chalk_score", 0), 0)
    ownership = safe_float(player.get("ownership", 0), 0)
    trend = safe_float(player.get("trend_score", 50), 50)
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    vegas_boost = safe_float(player.get("vegas_boost", 0), 0)
    market_boost = safe_float(player.get("market_boost", 0), 0)
    active = bool(player.get("active", True))
    position = normalize_position(player.get("position", ""))

    score = 0.0
    reasons = []

    if not active:
        return {
            "ai_pick_score": 0,
            "ai_pick_label": "Inactive / Do Not Use",
            "ai_pick_tier": "inactive",
            "ai_reasons": ["Marked inactive by slate cleanup or data engine"],
        }

    score += min(35, projection * (1.15 if position == "P" else 1.9))
    score += leverage * 0.28
    score += core * 0.22
    score += trend * 0.12
    score += max(0, team_total - 4.0) * 5.0
    score += vegas_boost * 2.2
    score += market_boost * 1.8
    score -= chalk * 0.12

    if projection >= (18 if position == "P" else 9):
        reasons.append("Strong projection for position")
    if leverage >= 65:
        reasons.append("Excellent leverage versus projected ownership")
    if ownership <= 10 and projection >= (14 if position == "P" else 7):
        reasons.append("Low-owned upside path")
    if team_total >= 4.8 and position != "P":
        reasons.append("Positive team scoring environment")
    if trend >= 70:
        reasons.append("Trend score is rising")
    if vegas_boost > 0:
        reasons.append("Vegas environment adds upside")
    if str(player.get("core_play_tier", "")).lower() == "bad_chalk":
        reasons.append("Warning: possible bad chalk")
    if str(player.get("market_signal", "")).lower().find("leverage") >= 0:
        reasons.append("Market signal shows leverage opening")

    score = round(max(0, min(100, score)), 1)
    if score >= 82:
        label, tier = "AI Core Play", "core"
    elif score >= 70:
        label, tier = "Strong AI Play", "strong"
    elif score >= 58:
        label, tier = "Tournament Watch", "watch"
    elif score >= 45:
        label, tier = "Thin / Neutral", "neutral"
    else:
        label, tier = "AI Fade", "fade"

    return {
        "ai_pick_score": score,
        "ai_pick_label": label,
        "ai_pick_tier": tier,
        "ai_reasons": reasons[:5] or ["Balanced profile with no major signal"],
    }


def ai_picks_summary():
    players = [p for p in add_values(load_players()) if bool(p.get("active", True))]
    enriched = []
    for player in players:
        clean = dict(player)
        clean.update(ai_pick_profile_for_player(clean))
        enriched.append(clean)

    hitters = [p for p in enriched if p.get("position") != "P"]
    pitchers = [p for p in enriched if p.get("position") == "P"]

    team_map = {}
    for p in hitters:
        team = p.get("team", "UNK")
        item = team_map.setdefault(team, {
            "team": team,
            "players": 0,
            "avg_ai_score": 0,
            "avg_projection": 0,
            "avg_leverage": 0,
            "team_total": safe_float(p.get("team_total", 4.2), 4.2),
            "stack_score": 0,
        })
        item["players"] += 1
        item["avg_ai_score"] += safe_float(p.get("ai_pick_score", 0), 0)
        item["avg_projection"] += safe_float(p.get("projection", 0), 0)
        item["avg_leverage"] += safe_float(p.get("leverage_score", 50), 50)

    stacks = []
    for item in team_map.values():
        count = max(1, item["players"])
        item["avg_ai_score"] = round(item["avg_ai_score"] / count, 1)
        item["avg_projection"] = round(item["avg_projection"] / count, 2)
        item["avg_leverage"] = round(item["avg_leverage"] / count, 1)
        item["stack_score"] = round(item["avg_ai_score"] * 0.55 + item["avg_leverage"] * 0.18 + item["team_total"] * 6.0 + min(item["players"], 6) * 2.0, 1)
        stacks.append(item)

    top_core = sorted(enriched, key=lambda p: safe_float(p.get("ai_pick_score", 0), 0), reverse=True)[:12]
    leverage = sorted(enriched, key=lambda p: (safe_float(p.get("leverage_score", 0), 0), safe_float(p.get("projection", 0), 0)), reverse=True)[:12]
    fades = sorted([p for p in enriched if str(p.get("ai_pick_tier", "")).lower() == "fade" or str(p.get("core_play_tier", "")).lower() in ["fade", "bad_chalk"]], key=lambda p: (safe_float(p.get("chalk_score", 0), 0), safe_float(p.get("ownership", 0), 0)), reverse=True)[:12]
    pitcher_pool = sorted(pitchers, key=lambda p: safe_float(p.get("ai_pick_score", 0), 0), reverse=True)[:8]
    stack_pool = sorted(stacks, key=lambda s: s.get("stack_score", 0), reverse=True)[:8]

    return {
        "success": True,
        "version": "ai_picks_auto_builder_mvp_v1",
        "player_count": len(enriched),
        "top_core_plays": [compact_ai_player(p) for p in top_core],
        "best_leverage_plays": [compact_ai_player(p) for p in leverage],
        "fades": [compact_ai_player(p) for p in fades],
        "top_pitchers": [compact_ai_player(p) for p in pitcher_pool],
        "best_stacks": stack_pool,
        "best_stack": stack_pool[0] if stack_pool else {},
        "provider_note": "MVP AI layer uses your current slate, ownership, leverage, Vegas movement, and Data Engine fields. Real APIs can be plugged into the same fields later.",
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def apply_auto_builder_strategy(request: AutoLineupBuilderRequest):
    focus = str(request.contest_focus or "big_gpp").lower()
    style = str(request.build_style or "balanced").lower()

    if focus in ["cash", "h2h", "double_up"]:
        request.mode = "cash"
        request.count = 1
        request.strategy_mode = "cash_double_up"
        request.stack_type = "auto"
        request.min_salary = max(request.min_salary, 48500)
        request.randomness = 0
        request.max_players_per_team = min(max(request.max_players_per_team, 4), 5)
        request.force_team_stack = False
        request.avoid_pitcher_vs_hitter = True
        request.max_exposure = 100
        request.max_same_players = 9
    elif focus in ["single_entry", "single_entry_gpp", "small_gpp"]:
        request.mode = "gpp"
        request.count = request.count if request.count in [1, 5] else 1
        request.strategy_mode = "small_field_single_entry"
        request.stack_type = "4-3"
        request.min_salary = max(request.min_salary, 48000)
        request.randomness = max(request.randomness, 12)
        request.max_players_per_team = min(max(request.max_players_per_team, 4), 5)
        request.force_team_stack = True
        request.avoid_pitcher_vs_hitter = True
        request.max_exposure = min(max(request.max_exposure, 50), 80)
        request.max_same_players = min(max(request.max_same_players, 6), 8)
    else:
        request.mode = "gpp"
        request.count = request.count if request.count in [5, 10, 20] else 20
        request.strategy_mode = "large_field_gpp" if request.count < 20 else "twenty_max"
        request.stack_type = "5-2" if style in ["aggressive", "nuclear"] else "4-3"
        request.min_salary = max(request.min_salary, 46500)
        request.randomness = max(request.randomness, 35 if style != "nuclear" else 60)
        request.max_players_per_team = min(max(request.max_players_per_team, 5), 6)
        request.force_team_stack = True
        request.avoid_pitcher_vs_hitter = True
        request.max_exposure = min(max(request.max_exposure, 35), 60)
        request.max_same_players = min(max(request.max_same_players, 4), 7)

    request.force_qb_stack = request.force_team_stack
    request.force_bring_back = request.avoid_pitcher_vs_hitter
    return request


def auto_builder_notes(request, lineups):
    picks = ai_picks_summary()
    best_stack = picks.get("best_stack", {})
    notes = [
        f"Contest focus: {request.contest_focus}",
        f"Build style: {request.build_style}",
        f"Strategy: {request.strategy_mode}",
        f"Stack type: {request.stack_type}",
    ]
    if best_stack:
        notes.append(f"Best stack signal: {best_stack.get('team')} score {best_stack.get('stack_score')}")
    if lineups:
        avg_win = round(sum(safe_float(l.get("win_probability", 0), 0) for l in lineups) / len(lineups), 1)
        avg_quality = round(sum(safe_float(l.get("lineup_quality_score", 0), 0) for l in lineups) / len(lineups), 1)
        notes.append(f"Average win strength: {avg_win}%")
        notes.append(f"Average lineup quality: {avg_quality}/100")
    return notes


@app.get("/ai-picks/status")
def ai_picks_status():
    return ai_picks_summary()


@app.post("/ai-lineup-builder/build")
def ai_lineup_builder(request: AutoLineupBuilderRequest):
    tuned = apply_auto_builder_strategy(request)
    selected, error, trim_report, checked = build_fast_multi_lineups_for_pro(tuned, tuned.count)
    if error:
        return {"success": False, "error": error, "lineups": [], "exposures": []}
    if not selected:
        return {"success": False, "error": "AI builder could not find valid lineups. Try clearing locks/excludes or lowering the salary floor.", "lineups": [], "exposures": []}

    selected.sort(key=lambda item: (
        safe_float(item.get("win_probability", 0), 0),
        safe_float(item.get("lineup_quality_score", 0), 0),
        safe_float(item.get("optimizer_score", 0), 0),
    ), reverse=True)

    return {
        "success": True,
        "mode": tuned.mode,
        "contest_focus": tuned.contest_focus,
        "build_style": tuned.build_style,
        "strategy_mode": tuned.strategy_mode,
        "stack_type": tuned.stack_type,
        "requested_count": tuned.count,
        "returned_count": len(selected),
        "lineups": selected,
        "exposures": calculate_exposures(selected),
        "ai_picks": ai_picks_summary(),
        "ai_builder_notes": auto_builder_notes(tuned, selected),
        "trim_report": trim_report,
        "combinations_checked": checked,
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

@app.get("/")
def root():
    return {
        "app": "DFS Edge MLB API",
        "status": "running",
        "sport": "MLB",
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "slate_source": current_slate_source(),
        "default_lineups": 1,
        "speed_boost": "enabled",
        "features": [
            "robust_dk_csv_upload",
            "projection_boosts",
            "ownership_estimates",
            "lineup_explain",
            "draftkings_export",
            "contest_simulator",
            "slate_cleanup_mode",
            "mlb_data_engine_layer",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "backend": "DFS Edge MLB",
        "port": 8010,
    }


@app.get("/slate-status")
def slate_status():
    players = add_values(load_players())
    active_count = len([p for p in players if bool(p.get("active", True))])
    inactive_count = len(players) - active_count
    return {
        "slate_source": current_slate_source(),
        "player_count": len(players),
        "active_player_count": active_count,
        "inactive_player_count": inactive_count,
        "has_imported_slate": ACTIVE_SLATE_PATH.exists(),
        "speed_boost": "enabled",
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "pool_limits": POOL_LIMITS,
        "auto_cleanup_enabled": True,
        "auto_cleanup_position_limits": AUTO_CLEANUP_POSITION_LIMITS,
    }


@app.post("/admin/upload-dk-csv")
async def upload_dk_csv(
    admin_password: str = Form(...),
    file: UploadFile = File(...),
):
    if admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}

    if not file.filename.lower().endswith(".csv"):
        return {"success": False, "error": "Please upload a CSV file."}

    raw = await file.read()
    csv_text = raw.decode("utf-8-sig", errors="replace")
    players = convert_dk_csv_to_players(csv_text)

    if len(players) < 10:
        return {
            "success": False,
            "error": "CSV imported, but not enough valid MLB players were found.",
            "player_count": len(players),
        }

    cleaned_players, cleanup_stats = apply_auto_slate_cleanup(players, respect_manual_overrides=False)
    save_active_slate(cleaned_players)

    return {
        "success": True,
        "message": "DraftKings MLB CSV uploaded, enriched, and auto-cleaned successfully.",
        "player_count": len(cleaned_players),
        "active_player_count": cleanup_stats["active_count"],
        "inactive_player_count": cleanup_stats["inactive_count"],
        "cleanup_stats": cleanup_stats,
        "ownership": "Estimated ownership applied when CSV ownership was missing.",
        "auto_cleanup": "Auto cleanup applied safely. Risky players are reviewed, not hard-removed unless invalid/out.",
    }


@app.post("/admin/use-sample")
def use_sample_slate(request: AdminPasswordRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}
    if ACTIVE_SLATE_PATH.exists():
        ACTIVE_SLATE_PATH.unlink()
    ensure_sample_players_file()
    players = load_players()
    return {
        "success": True,
        "message": "MLB sample slate loaded successfully.",
        "slate_source": current_slate_source(),
        "player_count": len(players),
    }


@app.post("/admin/clear-slate")
def clear_imported_slate(admin_password: str = Form(...)):
    if admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}
    if ACTIVE_SLATE_PATH.exists():
        ACTIVE_SLATE_PATH.unlink()
    ensure_sample_players_file()
    return {
        "success": True,
        "message": "Imported slate cleared. App is now using MLB sample players.",
    }


@app.post("/admin/update-player")
def update_player(request: UpdatePlayerRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}
    if request.projection < 0:
        return {"success": False, "error": "Projection cannot be negative."}
    if request.ownership < 0 or request.ownership > 100:
        return {"success": False, "error": "Ownership must be between 0 and 100."}

    players = load_players()
    for player in players:
        if player["name"] == request.player_name:
            player["projection"] = round(request.projection, 2)
            player["ownership"] = round(request.ownership, 2)
            player["value"] = player_value(player)
            save_active_slate(players)
            return {
                "success": True,
                "message": f"{request.player_name} updated successfully.",
                "player": player,
            }

    return {"success": False, "error": "Player not found."}


@app.post("/admin/update-player-status")
def update_player_status(request: UpdatePlayerStatusRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}

    players = load_players()
    target_name = request.player_name.strip()

    for player in players:
        if player.get("name") == target_name:
            player["active"] = bool(request.active)
            player["manual_status_override"] = True
            player["inactive_reason"] = "" if request.active else (request.inactive_reason or "manual_cleanup")
            player["auto_cleanup_reason"] = "manual_override"
            save_active_slate(players)
            return {
                "success": True,
                "message": f"{target_name} marked {'active' if request.active else 'inactive'}.",
                "player": player,
            }

    return {"success": False, "error": "Player not found."}


@app.get("/players")
def get_players():
    players = add_values(load_players())
    slot_order = {"P": 0, "C": 1, "1B": 2, "2B": 3, "3B": 4, "SS": 5, "OF": 6}
    players.sort(key=lambda p: (slot_order.get(p["position"], 99), -p["projection"]))
    return {
        "slate_source": current_slate_source(),
        "sport": "MLB",
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "players": players,
    }


@app.get("/value-plays")
def get_value_plays():
    players = [p for p in add_values(load_players()) if bool(p.get("active", True))]
    players.sort(key=lambda p: p["value"], reverse=True)
    return {
        "slate_source": current_slate_source(),
        "sport": "MLB",
        "value_plays": players[:8],
    }


@app.post("/optimize")
def optimize_lineup(request: OptimizeRequest):
    all_lineups, error, trim_report, checked = build_all_lineups(
        mode=request.mode,
        locked_players=request.locked_players,
        excluded_players=request.excluded_players,
        min_salary=request.min_salary,
        max_players_per_team=request.max_players_per_team,
        force_qb_stack=request.force_qb_stack,
        force_bring_back=request.force_bring_back,
        force_team_stack=request.force_team_stack,
        avoid_pitcher_vs_hitter=request.avoid_pitcher_vs_hitter,
        randomness=request.randomness,
    )

    if error:
        return {"error": error}
    if not all_lineups:
        return {"error": "No valid MLB lineup found with your current locks and excludes."}

    result = all_lineups[0]
    result["trim_report"] = trim_report
    result["combinations_checked"] = checked
    result["salary_cap"] = SALARY_CAP
    result["roster_slots"] = ROSTER_SLOTS
    return result


@app.post("/optimize-multiple")
def optimize_multiple_lineups(request: MultiOptimizeRequest):
    count = request.count if request.count in [1, 5, 10, 20] else 1

    # Always use the fast builder for this endpoint.
    # This fixes Pro mode when count is 1 and prevents full DraftKings CSV slates from timing out.
    selected, error, trim_report, checked = build_fast_multi_lineups_for_pro(request, count)

    if error:
        return {"error": error, "lineups": [], "exposures": []}

    if not selected:
        return {"error": "No valid MLB lineups found with your current locks and excludes.", "lineups": [], "exposures": []}

    return {
        "mode": request.mode,
        "requested_count": count,
        "returned_count": len(selected),
        "slate_source": current_slate_source(),
        "sport": "MLB",
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "speed_boost": "enabled",
        "trim_report": trim_report,
        "combinations_checked": checked,
        "lineups": selected,
        "exposures": calculate_exposures(selected),
        "player_min_exposure": normalize_exposure_limits(request.player_min_exposure),
        "player_max_exposure": normalize_exposure_limits(request.player_max_exposure),
    }

@app.post("/export-lineups-csv")
def export_lineups_csv(request: MultiOptimizeRequest):
    count = request.count if request.count in [1, 5, 10, 20] else 1
    max_exposure = min(max(request.max_exposure, 20), 100)
    max_same_players = min(max(request.max_same_players, 3), 9)

    # Use the same fast builder for export so Pro exports do not timeout on large MLB CSV slates.
    selected, error, trim_report, checked = build_fast_multi_lineups_for_pro(request, count)

    if error:
        return {"success": False, "error": error, "csv": ""}
    if not selected:
        return {"success": False, "error": "No valid MLB lineups found with your current locks and excludes.", "csv": ""}

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return {
        "success": True,
        "filename": f"dfs_edge_mlb_dk_lineups_{count}_{stamp}.csv",
        "csv": build_export_csv(selected),
        "lineup_count": len(selected),
        "sport": "MLB",
        "salary_cap": SALARY_CAP,
        "roster_slots": ROSTER_SLOTS,
        "min_salary": min(max(request.min_salary, 0), SALARY_CAP),
        "max_players_per_team": min(max(request.max_players_per_team, 1), 8),
        "force_team_stack": request.force_team_stack or request.force_qb_stack,
        "avoid_pitcher_vs_hitter": request.avoid_pitcher_vs_hitter,
        "randomness": min(max(request.randomness, 0), 100),
        "player_min_exposure": normalize_exposure_limits(request.player_min_exposure),
        "player_max_exposure": normalize_exposure_limits(request.player_max_exposure),
    }




def extract_lineup_players(payload):
    if not isinstance(payload, dict):
        return []
    raw_players = payload.get("lineup", [])
    if isinstance(raw_players, list):
        return raw_players
    return []


def current_player_lookup():
    lookup = {}
    for player in add_values(load_players()):
        name = str(player.get("name", "")).strip()
        if name:
            lookup[name] = player
    return lookup


def lineup_late_swap_alerts(lineup_data):
    players = extract_lineup_players(lineup_data)
    lookup = current_player_lookup()
    alerts = []
    inactive = []
    missing = []

    for player in players:
        name = str(player.get("name", "")).strip()
        current = lookup.get(name)
        if not current:
            missing.append(name)
            continue
        if current.get("active") is False:
            inactive.append({
                "name": name,
                "reason": current.get("inactive_reason", "inactive_or_not_starting"),
            })

    if inactive:
        alerts.append({
            "severity": "high",
            "type": "inactive_player",
            "title": "Inactive / not-starting player detected",
            "message": f"{len(inactive)} player(s) in this lineup are inactive, not starting, or marked risky by slate cleanup.",
            "players": inactive,
            "action": "late_swap_recommended",
        })

    if missing:
        alerts.append({
            "severity": "medium",
            "type": "missing_player",
            "title": "Player not found in current slate",
            "message": "One or more players from this lineup are not in the current uploaded slate.",
            "players": missing,
            "action": "verify_slate",
        })

    if pitcher_vs_hitter_conflict(players):
        alerts.append({
            "severity": "medium",
            "type": "pitcher_conflict",
            "title": "Pitcher vs hitter conflict",
            "message": "This lineup includes a pitcher facing one of your hitters.",
            "players": [],
            "action": "review_correlation",
        })

    total_salary = sum(safe_int(p.get("salary", 0)) for p in players)
    if total_salary > SALARY_CAP:
        alerts.append({
            "severity": "high",
            "type": "salary_cap",
            "title": "Salary cap exceeded",
            "message": f"Lineup salary is ${total_salary}, which is over the ${SALARY_CAP} DraftKings cap.",
            "players": [],
            "action": "repair_required",
        })

    return alerts


def build_late_swap_repair(request: LateSwapRequest):
    original_players = extract_lineup_players(request.lineup)
    lookup = current_player_lookup()
    started = set(request.started_players or [])
    excluded = set(request.excluded_players or [])

    active_original_names = []
    inactive_names = []

    for player in original_players:
        name = str(player.get("name", "")).strip()
        if not name:
            continue
        current = lookup.get(name)
        if current and current.get("active") is not False:
            active_original_names.append(name)
        else:
            inactive_names.append(name)
            excluded.add(name)

    # Preserve started players first, then preserve as many currently active original players as possible.
    repair_lock_order = []
    for name in list(started) + active_original_names + list(request.locked_players or []):
        if name and name not in repair_lock_order:
            repair_lock_order.append(name)

    # Try stricter locks first, then relax until the optimizer can produce a clean repaired lineup.
    lock_attempts = [
        repair_lock_order,
        [name for name in repair_lock_order if name in started],
        list(request.locked_players or []),
        [],
    ]

    last_error = None
    for locked_names in lock_attempts:
        multi_request = MultiOptimizeRequest(
            mode=request.mode,
            count=1,
            max_exposure=100,
            max_same_players=9,
            locked_players=locked_names,
            excluded_players=list(excluded),
            min_salary=request.min_salary,
            max_players_per_team=request.max_players_per_team,
            force_qb_stack=request.force_qb_stack,
            force_bring_back=request.force_bring_back,
            force_team_stack=request.force_team_stack,
            avoid_pitcher_vs_hitter=request.avoid_pitcher_vs_hitter,
            randomness=request.randomness,
            player_min_exposure={},
            player_max_exposure={},
        )
        selected, error, trim_report, checked = build_fast_multi_lineups_for_pro(multi_request, 1)
        if selected:
            fixed = selected[0]
            fixed["late_swap_repair"] = {
                "success": True,
                "preserved_players": [p.get("name") for p in fixed.get("lineup", []) if p.get("name") in active_original_names],
                "locked_started_players": list(started),
                "removed_players": inactive_names,
                "lock_attempt_used": locked_names,
                "combinations_checked": checked,
                "trim_report": trim_report,
            }
            fixed["late_swap_alerts"] = lineup_late_swap_alerts(fixed)
            return fixed, None
        last_error = error

    return None, last_error or "Could not repair this lineup. Try clearing locks, lowering min salary, or re-uploading the latest DraftKings CSV."





def load_market_state():
    if MARKET_STATE_PATH.exists():
        try:
            with open(MARKET_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            if isinstance(state, dict):
                return state
        except Exception:
            pass
    return {
        "version": "ownership_drift_vegas_movement_mvp_v1",
        "updated_at": "",
        "players": {},
        "teams": {},
    }


def save_market_state(state):
    with open(MARKET_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def market_player_key(player):
    return f"{str(player.get('name', '')).strip().lower()}|{normalize_team(player.get('team', ''))}|{normalize_position(player.get('position', ''))}"


def deterministic_market_drift(player, salt, spread=6):
    bucket = stable_bucket_for_player(player, salt=salt, modulo=(spread * 2 + 1))
    return bucket - spread


def market_movement_profile(player, state=None):
    """
    MVP market model.
    Uses saved snapshots when available; otherwise creates deterministic prior values
    so the UI can show ownership drift and Vegas movement before paid APIs are connected.
    Later this function becomes the integration point for real ownership feeds and odds APIs.
    """
    state = state or load_market_state()
    player_key = market_player_key(player)
    team_key = normalize_team(player.get("team", ""))

    current_ownership = round(safe_float(player.get("ownership", 0), 0), 1)
    current_team_total = round(safe_float(player.get("team_total", estimated_team_total(team_key)), estimated_team_total(team_key)), 1)

    prior_player = (state.get("players") or {}).get(player_key, {})
    prior_team = (state.get("teams") or {}).get(team_key, {})

    if prior_player:
        previous_ownership = round(safe_float(prior_player.get("ownership", current_ownership), current_ownership), 1)
    else:
        simulated_delta = deterministic_market_drift(player, "ownership_prior", spread=5) * 0.7
        previous_ownership = round(max(0.5, min(45.0, current_ownership - simulated_delta)), 1)

    if prior_team:
        previous_team_total = round(safe_float(prior_team.get("team_total", current_team_total), current_team_total), 1)
    else:
        simulated_total_delta = deterministic_market_drift(player, "team_total_prior", spread=4) * 0.1
        previous_team_total = round(max(2.5, min(7.5, current_team_total - simulated_total_delta)), 1)

    ownership_delta = round(current_ownership - previous_ownership, 1)
    team_total_delta = round(current_team_total - previous_team_total, 1)

    leverage_score = safe_float(player.get("leverage_score", 0), 0)
    trend_score = safe_float(player.get("trend_score", 50), 50)
    projection = safe_float(player.get("projection", 0), 0)
    position = normalize_position(player.get("position", ""))

    signal = "Neutral"
    signal_type = "neutral"
    market_boost = 0.0
    notes = []

    if ownership_delta >= 6 and leverage_score < 45:
        signal = "📈 Chalk Rising"
        signal_type = "chalk_rising"
        market_boost -= 0.55
        notes.append("Ownership rising faster than leverage")
    elif ownership_delta <= -4 and projection >= 6 and position != "P":
        signal = "🚀 Leverage Opening"
        signal_type = "leverage_opening"
        market_boost += 0.55
        notes.append("Ownership falling while projection remains usable")
    elif team_total_delta >= 0.4 and position != "P":
        signal = "🔥 Vegas Up"
        signal_type = "vegas_up"
        market_boost += 0.65
        notes.append("Team total moving up")
    elif team_total_delta <= -0.4 and position != "P":
        signal = "⚠️ Vegas Down"
        signal_type = "vegas_down"
        market_boost -= 0.45
        notes.append("Team total moving down")
    elif ownership_delta >= 4 and leverage_score >= 60:
        signal = "✅ Sharp Steam"
        signal_type = "sharp_steam"
        market_boost += 0.30
        notes.append("Ownership rising with strong leverage")
    elif trend_score >= 74 and ownership_delta <= 2:
        signal = "💎 Underowned Trend"
        signal_type = "underowned_trend"
        market_boost += 0.45
        notes.append("Trend score strong without heavy ownership rise")

    if position == "P" and team_total_delta <= -0.3:
        # Pitchers benefit when opponent/game environment weakens.
        market_boost += 0.20

    return {
        "previous_ownership": previous_ownership,
        "ownership_delta": ownership_delta,
        "ownership_drift_label": "Rising" if ownership_delta > 1.5 else ("Falling" if ownership_delta < -1.5 else "Stable"),
        "previous_team_total": previous_team_total,
        "team_total_delta": team_total_delta,
        "vegas_movement_label": "Up" if team_total_delta > 0.15 else ("Down" if team_total_delta < -0.15 else "Flat"),
        "market_signal": signal,
        "market_signal_type": signal_type,
        "market_boost": round(market_boost, 2),
        "market_notes": notes,
    }


def snapshot_market_state(players):
    clean_players = add_values(players)
    state = {
        "version": "ownership_drift_vegas_movement_mvp_v1",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "players": {},
        "teams": {},
    }
    for player in clean_players:
        key = market_player_key(player)
        team = normalize_team(player.get("team", ""))
        state["players"][key] = {
            "name": player.get("name", ""),
            "team": team,
            "position": player.get("position", ""),
            "ownership": round(safe_float(player.get("ownership", 0), 0), 1),
            "projection": round(safe_float(player.get("projection", 0), 0), 2),
        }
        if team:
            state["teams"][team] = {
                "team_total": round(safe_float(player.get("team_total", estimated_team_total(team)), estimated_team_total(team)), 1),
            }
    save_market_state(state)
    return state


def market_intelligence_summary(persist_snapshot=False):
    players = add_values(load_players())
    if persist_snapshot:
        previous_state = load_market_state()
        # players already contain movement vs previous_state; now store current values for future drift.
        state_to_save = {
            "version": "ownership_drift_vegas_movement_mvp_v1",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "players": {},
            "teams": {},
        }
        for player in players:
            state_to_save["players"][market_player_key(player)] = {
                "name": player.get("name", ""),
                "team": player.get("team", ""),
                "position": player.get("position", ""),
                "ownership": round(safe_float(player.get("ownership", 0), 0), 1),
                "projection": round(safe_float(player.get("projection", 0), 0), 2),
            }
            team = normalize_team(player.get("team", ""))
            if team:
                state_to_save["teams"][team] = {"team_total": round(safe_float(player.get("team_total", estimated_team_total(team)), estimated_team_total(team)), 1)}
        save_market_state(state_to_save)

    rising = [p for p in players if safe_float(p.get("ownership_delta", 0), 0) >= 4]
    falling = [p for p in players if safe_float(p.get("ownership_delta", 0), 0) <= -3]
    vegas_up = [p for p in players if safe_float(p.get("team_total_delta", 0), 0) >= 0.3 and p.get("position") != "P"]
    vegas_down = [p for p in players if safe_float(p.get("team_total_delta", 0), 0) <= -0.3 and p.get("position") != "P"]
    sharp = [p for p in players if str(p.get("market_signal_type", "")) in ["sharp_steam", "vegas_up", "leverage_opening", "underowned_trend"]]
    bad_chalk = [p for p in players if str(p.get("market_signal_type", "")) == "chalk_rising"]

    def compact_player(p):
        return {
            "name": p.get("name", ""),
            "position": p.get("position", ""),
            "team": p.get("team", ""),
            "projection": p.get("projection", 0),
            "ownership": p.get("ownership", 0),
            "previous_ownership": p.get("previous_ownership", 0),
            "ownership_delta": p.get("ownership_delta", 0),
            "team_total": p.get("team_total", 0),
            "previous_team_total": p.get("previous_team_total", 0),
            "team_total_delta": p.get("team_total_delta", 0),
            "leverage_score": p.get("leverage_score", 0),
            "market_signal": p.get("market_signal", "Neutral"),
            "market_boost": p.get("market_boost", 0),
        }

    top_signals = sorted(players, key=lambda p: (abs(safe_float(p.get("ownership_delta", 0), 0)) + abs(safe_float(p.get("team_total_delta", 0), 0)) * 7 + abs(safe_float(p.get("market_boost", 0), 0)) * 4), reverse=True)[:12]

    return {
        "success": True,
        "version": "ownership_drift_vegas_movement_mvp_v1",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "player_count": len(players),
        "ownership_rising_count": len(rising),
        "ownership_falling_count": len(falling),
        "vegas_up_count": len(vegas_up),
        "vegas_down_count": len(vegas_down),
        "sharp_signal_count": len(sharp),
        "bad_chalk_count": len(bad_chalk),
        "top_signals": [compact_player(p) for p in top_signals],
        "sharp_plays": [compact_player(p) for p in sorted(sharp, key=lambda p: safe_float(p.get("market_boost", 0), 0), reverse=True)[:10]],
        "bad_chalk": [compact_player(p) for p in sorted(bad_chalk, key=lambda p: safe_float(p.get("ownership_delta", 0), 0), reverse=True)[:10]],
        "provider_mode": "MVP simulated/API-ready",
        "provider_note": "Connect ownership projections and odds APIs here. Current version tracks snapshots and deterministic movement when no provider is configured.",
    }

def player_live_status(player):
    """
    API-ready real-time slate intelligence layer.
    MVP uses current Data Engine fields and active status.
    Later: plug in SportsDataIO/Sportradar/odds/weather responses here.
    """
    active = bool(player.get("active", True))
    injury_status = str(player.get("injury_status", "active") or "active").lower()
    starter_status = str(player.get("starter_status", "projected") or "projected").lower()
    weather_risk = str(player.get("weather_risk", "low") or "low").lower()
    pull_risk = str(player.get("pull_risk", "medium") or "medium").lower()
    auto_recommendation = str(player.get("auto_active_recommendation", "active") or "active").lower()

    risk_points = 0
    tags = []

    if not active:
        risk_points += 55
        tags.append("inactive")
    if injury_status in ["il", "out", "injured"]:
        risk_points += 45
        tags.append("injury_out")
    elif injury_status in ["day_to_day", "questionable"]:
        risk_points += 18
        tags.append("day_to_day")
    if starter_status in ["not_starting", "bench", "bench_risk"]:
        risk_points += 34
        tags.append("not_starting")
    elif starter_status in ["projected", "unknown"]:
        risk_points += 8
        tags.append("unconfirmed")
    if weather_risk == "high":
        risk_points += 22
        tags.append("weather_high")
    elif weather_risk == "medium":
        risk_points += 10
        tags.append("weather_medium")
    if pull_risk == "high":
        risk_points += 12
        tags.append("pull_risk")
    if auto_recommendation in ["inactive", "review", "bench_risk"]:
        risk_points += 12
        tags.append("data_engine_review")

    risk_points = max(0, min(100, risk_points))

    if risk_points >= 70:
        status = "critical"
        label = "Swap Required"
    elif risk_points >= 40:
        status = "warning"
        label = "High Risk"
    elif risk_points >= 18:
        status = "watch"
        label = "Monitor"
    else:
        status = "clean"
        label = "Clean"

    return {
        "name": player.get("name", ""),
        "team": player.get("team", ""),
        "position": player.get("position", ""),
        "status": status,
        "label": label,
        "risk_score": risk_points,
        "tags": tags,
        "active": active,
        "starter_status": starter_status,
        "injury_status": injury_status,
        "weather_risk": weather_risk,
        "pull_risk": pull_risk,
        "recommended_action": "swap" if risk_points >= 70 else ("review" if risk_points >= 18 else "hold"),
    }


def calculate_lineup_health_profile(lineup_data):
    players = extract_lineup_players(lineup_data)
    lookup = current_player_lookup()
    statuses = []
    total_risk = 0
    critical = 0
    warnings = 0
    watch = 0

    for player in players:
        name = str(player.get("name", "")).strip()
        current = lookup.get(name, player)
        live = player_live_status(current)
        statuses.append(live)
        total_risk += safe_int(live.get("risk_score", 0), 0)
        if live["status"] == "critical":
            critical += 1
        elif live["status"] == "warning":
            warnings += 1
        elif live["status"] == "watch":
            watch += 1

    average_risk = round(total_risk / len(statuses), 1) if statuses else 0
    health_score = max(0, min(100, round(100 - average_risk - critical * 18 - warnings * 8 - watch * 2, 1)))

    if critical > 0:
        label = "Broken / Swap Required"
        action = "fix_lineup"
    elif warnings > 0:
        label = "High-Risk Watch"
        action = "review_lineup"
    elif watch > 0:
        label = "Monitor News"
        action = "monitor"
    else:
        label = "Clean"
        action = "hold"

    return {
        "health_score": health_score,
        "health_label": label,
        "recommended_action": action,
        "critical_count": critical,
        "warning_count": warnings,
        "watch_count": watch,
        "average_risk": average_risk,
        "player_statuses": statuses,
    }


def slate_intelligence_summary():
    players = add_values(load_players())
    statuses = [player_live_status(p) for p in players]
    active_count = len([p for p in players if bool(p.get("active", True))])
    inactive_count = len(players) - active_count
    critical = len([s for s in statuses if s["status"] == "critical"])
    warnings = len([s for s in statuses if s["status"] == "warning"])
    watch = len([s for s in statuses if s["status"] == "watch"])
    weather_high = len([s for s in statuses if "weather_high" in s.get("tags", [])])
    injury_flags = len([s for s in statuses if "injury_out" in s.get("tags", []) or "day_to_day" in s.get("tags", [])])
    not_starting = len([s for s in statuses if "not_starting" in s.get("tags", [])])

    slate_health = max(0, min(100, round(100 - (critical * 0.9) - (warnings * 0.45) - (watch * 0.12), 1)))

    if critical > 0:
        label = "Late Swap Required"
    elif warnings > 0:
        label = "Monitor Closely"
    elif watch > 0:
        label = "News Watch"
    else:
        label = "Slate Clean"

    top_alerts = sorted(statuses, key=lambda item: item.get("risk_score", 0), reverse=True)[:12]

    return {
        "success": True,
        "version": "real_time_slate_intelligence_mvp_v1",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "slate_source": current_slate_source(),
        "player_count": len(players),
        "active_player_count": active_count,
        "inactive_player_count": inactive_count,
        "slate_health_score": slate_health,
        "slate_health_label": label,
        "critical_count": critical,
        "warning_count": warnings,
        "watch_count": watch,
        "weather_high_count": weather_high,
        "injury_flag_count": injury_flags,
        "not_starting_count": not_starting,
        "top_alerts": top_alerts,
        "data_source_mode": "MVP simulated/API-ready",
        "provider_note": "Plug SportsDataIO/Sportradar/Odds/OpenWeather into player_live_status() to replace MVP estimates.",
    }



@app.get("/market-intelligence/status")
def market_intelligence_status():
    return market_intelligence_summary(persist_snapshot=False)


@app.post("/market-intelligence/refresh")
def market_intelligence_refresh(request: AdminPasswordRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}
    summary = market_intelligence_summary(persist_snapshot=True)
    summary["message"] = "Ownership drift and Vegas movement refreshed. Current market snapshot saved for future comparison."
    return summary

@app.get("/slate-intelligence/status")
def slate_intelligence_status():
    return slate_intelligence_summary()


@app.post("/slate-intelligence/refresh")
def slate_intelligence_refresh(request: AdminPasswordRequest):
    if request.admin_password != ADMIN_PASSWORD:
        return {"success": False, "error": "Invalid admin password."}

    enriched_players, cleanup_stats = apply_auto_slate_cleanup(load_players(), respect_manual_overrides=True)
    save_active_slate(enriched_players)
    summary = slate_intelligence_summary()
    summary["cleanup_stats"] = cleanup_stats
    summary["message"] = "Real-time slate intelligence refreshed using the current API-ready Data Engine layer."
    return summary


@app.post("/slate-intelligence/lineup-health")
def slate_intelligence_lineup_health(request: LineupAlertsRequest):
    results = []
    for index, lineup in enumerate(request.lineups or []):
        health = calculate_lineup_health_profile(lineup)
        alerts = lineup_late_swap_alerts(lineup)
        results.append({
            "lineup_number": index + 1,
            "lineup_health": health,
            "alerts": alerts,
        })
    return {
        "success": True,
        "results": results,
        "lineup_count": len(results),
        "needs_repair_count": len([r for r in results if r["lineup_health"].get("recommended_action") == "fix_lineup"]),
    }

@app.post("/lineup-alerts")
def lineup_alerts(request: LineupAlertsRequest):
    results = []
    for index, lineup in enumerate(request.lineups or []):
        results.append({
            "lineup_number": index + 1,
            "alerts": lineup_late_swap_alerts(lineup),
        })
    return {
        "success": True,
        "results": results,
        "alert_count": sum(len(item["alerts"]) for item in results),
    }


@app.post("/late-swap/fix")
def late_swap_fix(request: LateSwapRequest):
    fixed, error = build_late_swap_repair(request)
    if error:
        return {"success": False, "error": error, "fixed_lineup": None}
    return {
        "success": True,
        "message": "Late swap repair created a clean lineup using the current active slate.",
        "fixed_lineup": fixed,
        "alerts": fixed.get("late_swap_alerts", []),
    }


@app.post("/lineup-fixer")
def lineup_fixer(request: LateSwapRequest):
    return late_swap_fix(request)

@app.post("/simulate-contest")
def simulate_contest(request: ContestSimulationRequest):
    return simulate_contest_payload(request)


@app.post("/contest-simulator")
def contest_simulator(request: ContestSimulationRequest):
    return simulate_contest_payload(request)


@app.post("/simulate")
def simulate(request: ContestSimulationRequest):
    return simulate_contest_payload(request)
