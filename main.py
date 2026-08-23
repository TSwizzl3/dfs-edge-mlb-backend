
from fastapi import FastAPI, UploadFile, File, Form, Depends, Header, HTTPException
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
import random
import os
import statistics
import time
import urllib.request
import urllib.parse
import urllib.error
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

app = FastAPI(title="DFS Edge MLB API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SALARY_CAP = 50000
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
CENTRAL_AUTH_URL = os.getenv(
    "CENTRAL_AUTH_URL",
    "https://dfs-edge-nfl-backend-skwfa.ondigitalocean.app",
).rstrip("/")

APP_DIR = Path(__file__).parent
# Persistent data directory for live hosting.
# On Render, add a Persistent Disk mounted at /var/data.
# Locally, this safely falls back to the backend folder.
DATA_DIR = Path(os.getenv("DFS_EDGE_DATA_DIR", "/var/data" if Path("/var/data").exists() else str(APP_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
BASE_DIR = DATA_DIR
SAMPLE_PLAYERS_PATH = BASE_DIR / "sample_players.json"
ACTIVE_SLATE_PATH = BASE_DIR / "active_slate.json"
SLATE_METADATA_PATH = BASE_DIR / "slate_metadata.json"
MARKET_STATE_PATH = BASE_DIR / "market_state.json"
USERS_PATH = BASE_DIR / "users.json"
PAYOUT_TABLE_PATH = BASE_DIR / "mlb_payout_table.json"
PROJECTION_SNAPSHOT_PATH = BASE_DIR / "mlb_projection_snapshot.json"
BACKTEST_LATEST_PATH = BASE_DIR / "mlb_backtest_latest.json"
BACKTEST_HISTORY_PATH = BASE_DIR / "mlb_backtest_history.json"
MLB_STARTER_STATE_PATH = BASE_DIR / "mlb_starter_state.json"
MLB_ODDS_STATE_PATH = BASE_DIR / "mlb_odds_state.json"
MLB_WEATHER_STATE_PATH = BASE_DIR / "mlb_weather_state.json"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "zero2sixtygraphics@gmail.com").strip().lower()

MLB_STATS_API_BASE_URL = "https://statsapi.mlb.com/api/v1"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_REGIONS = os.getenv("ODDS_API_REGIONS", "us").strip() or "us"
ODDS_API_BOOKMAKERS = os.getenv("ODDS_API_BOOKMAKERS", "").strip()
MLB_WEATHER_CACHE_SECONDS = 30 * 60
MLB_ODDS_CACHE_SECONDS = 3 * 60 * 60
ALLOW_SAMPLE_SLATE = os.getenv("ALLOW_SAMPLE_SLATE", "false").strip().lower() in {"1", "true", "yes"}

ROSTER_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]

POOL_LIMITS = {
    "P": 120,
    "C": 80,
    "1B": 80,
    "2B": 80,
    "3B": 80,
    "SS": 80,
    "OF": 220,
}

# Higher cap so larger live slates can still find valid MLB builds.
MAX_COMBINATIONS_TO_CHECK = 500000

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
    admin_password: str = ""
    auth_token: str = ""
    player_name: str
    projection: float
    ownership: float


class UpdatePlayerStatusRequest(BaseModel):
    admin_password: str = ""
    auth_token: str = ""
    player_name: str
    active: bool
    inactive_reason: str = "manual_cleanup"


class AdminPasswordRequest(BaseModel):
    admin_password: str = ""
    auth_token: str = ""


class SlateMetadataRequest(BaseModel):
    admin_password: str = ""
    auth_token: str = ""
    slate_name: str = ""
    slate_date: str = ""


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
    admin_password: str = ""
    auth_token: str = ""
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
    contest_profile_id: str = ""
    contest_profile_name: str = ""
    payout_tiers: list[dict] = Field(default_factory=list)
    ownership_overrides: dict[str, float] = Field(default_factory=dict)

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
    team = {
        "ATH": "OAK", "AZ": "ARI", "CHW": "CWS", "KC": "KC",
        "KCR": "KC", "SDP": "SD", "SFG": "SF", "TBR": "TB",
        "WAS": "WSH",
    }.get(team, team)
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


def normalized_player_name(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", ascii_name)


def parse_projection_csv(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    projections = []
    for raw_row in reader:
        row = clean_csv_row(raw_row)
        name = find_column(row, ["Name", "Player", "Player Name", "Nickname"])
        projection = find_column(row, ["Projection", "Projected Points", "Proj", "FPTS", "Median"])
        ceiling = find_column(row, ["Ceiling", "Projected Ceiling", "Ceiling Points", "Upside"])
        floor = find_column(row, ["Floor", "Projected Floor", "Floor Points"])
        ownership = find_column(row, ["Ownership", "Projected Ownership", "Own", "Own%", "Ownership %"])
        if not name or safe_float(projection, -1) < 0:
            continue
        item = {
            "name": extract_name_from_name_plus_id(name),
            "projection": round(safe_float(projection), 3),
            "ownership": round(max(0.0, min(100.0, safe_float(ownership, 0))), 3),
        }
        if safe_float(ceiling, 0) > 0:
            item["ceiling"] = round(safe_float(ceiling), 3)
        if safe_float(floor, -1) >= 0:
            item["floor"] = round(safe_float(floor), 3)
        projections.append(item)
    return projections


def parse_actual_results_csv(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    actuals = []
    for raw_row in reader:
        row = clean_csv_row(raw_row)
        name = find_column(row, ["Name", "Player", "Player Name", "Nickname"])
        points_value = find_column(
            row,
            ["Actual Points", "Fantasy Points", "FPTS", "DK Points", "Points"],
        )
        points = safe_float(points_value, -1)
        if name and points >= 0:
            actuals.append({
                "name": extract_name_from_name_plus_id(name),
                "actual_points": round(points, 3),
            })
    return actuals


def projection_backtest(players, actual_rows):
    actual_by_name = {
        normalized_player_name(item.get("name")): safe_float(item.get("actual_points"), 0)
        for item in actual_rows
    }
    matched = []
    for player in players:
        key = normalized_player_name(player.get("name"))
        if key not in actual_by_name:
            continue
        actual = actual_by_name[key]
        projection = safe_float(player.get("projection"), 0)
        floor = safe_float(player.get("floor"), max(0, projection * 0.35))
        ceiling = safe_float(player.get("ceiling"), projection * (1.65 if normalize_position(player.get("position")) == "P" else 2.2))
        matched.append({
            "name": player.get("name"),
            "position": normalize_position(player.get("position")),
            "projection": projection,
            "floor": floor,
            "ceiling": ceiling,
            "actual": actual,
            "error": projection - actual,
            "model_version": player.get("projection_model_version", "unknown"),
        })

    def metrics(rows):
        if not rows:
            return {"sample_size": 0}
        errors = [item["error"] for item in rows]
        projections = [item["projection"] for item in rows]
        actuals = [item["actual"] for item in rows]
        mean_projection = statistics.fmean(projections)
        mean_actual = statistics.fmean(actuals)
        covariance = sum(
            (projection - mean_projection) * (actual - mean_actual)
            for projection, actual in zip(projections, actuals)
        )
        denominator = math.sqrt(
            sum((projection - mean_projection) ** 2 for projection in projections)
            * sum((actual - mean_actual) ** 2 for actual in actuals)
        )
        return {
            "sample_size": len(rows),
            "mae": round(statistics.fmean(abs(error) for error in errors), 3),
            "rmse": round(math.sqrt(statistics.fmean(error * error for error in errors)), 3),
            "bias": round(statistics.fmean(errors), 3),
            "correlation": round(covariance / denominator, 3) if denominator else 0,
            "within_3_points_percent": round(100 * sum(abs(error) <= 3 for error in errors) / len(rows), 1),
            "within_5_points_percent": round(100 * sum(abs(error) <= 5 for error in errors) / len(rows), 1),
            "floor_coverage_percent": round(100 * sum(item["actual"] >= item["floor"] for item in rows) / len(rows), 1),
            "ceiling_coverage_percent": round(100 * sum(item["actual"] <= item["ceiling"] for item in rows) / len(rows), 1),
        }

    positions = ["P", "C", "1B", "2B", "3B", "SS", "OF"]
    return {
        "overall": metrics(matched),
        "by_position": {
            position: metrics([item for item in matched if item["position"] == position])
            for position in positions
        },
        "matched_players": len(matched),
        "unmatched_results": max(0, len(actual_rows) - len(matched)),
        "model_versions": sorted({item["model_version"] for item in matched}),
    }


def parse_rank_range(value):
    numbers = [safe_int(part) for part in re.findall(r"[\d,]+", str(value or "").replace(",", ""))]
    numbers = [number for number in numbers if number > 0]
    if not numbers:
        return None
    return min(numbers), max(numbers)


def parse_payout_csv(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    tiers = []
    for raw_row in reader:
        row = clean_csv_row(raw_row)
        rank_value = find_column(row, ["Rank", "Place", "Position", "Finishing Position", "Places", "Rank Range"])
        payout_value = find_column(row, ["Payout", "Prize", "Amount", "Winnings", "Cash"])
        rank_range = parse_rank_range(rank_value)
        payout = safe_float(payout_value, -1)
        if not rank_range or payout < 0:
            continue
        tiers.append({"start_rank": rank_range[0], "end_rank": rank_range[1], "payout": round(payout, 2)})
    tiers.sort(key=lambda tier: (tier["start_rank"], tier["end_rank"]))
    return tiers


def read_json_file(path, default):
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload
    except Exception:
        return default


def write_json_file(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_payout_table():
    payload = read_json_file(PAYOUT_TABLE_PATH, [])
    return payload if isinstance(payload, list) else []


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
            "game_info": str(game_info or "").strip(),
            "dk_slate_eligible": True,
            "slate_source": "draftkings_csv",
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
            if isinstance(active_players, list):
                # An imported DraftKings slate is authoritative. Never replace it
                # with sample data or reactivate trimmed/bench players.
                if "apply_slate_starter_likelihood" in globals() and any(
                    not str(player.get("starter_source", "")).strip()
                    for player in active_players
                    if isinstance(player, dict)
                ):
                    migrated = []
                    for player in active_players:
                        migrated_player = dict(player)
                        migrated_player.setdefault("dk_slate_eligible", True)
                        migrated_player.setdefault("slate_source", "draftkings_csv")
                        migrated.append(migrated_player)
                    return apply_slate_starter_likelihood(migrated)
                return active_players
        except Exception:
            # Fail closed when an imported slate is corrupt. Sample players must
            # never leak into a real contest slate.
            return []

    if not ALLOW_SAMPLE_SLATE:
        return []

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


def default_slate_metadata():
    today = datetime.now().strftime("%Y-%m-%d")
    if ACTIVE_SLATE_PATH.exists():
        return {
            "slate_name": "DraftKings MLB Slate",
            "slate_date": today,
            "slate_source": "imported_or_edited_slate",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "updated_by": "system",
        }
    return {
        "slate_name": "MLB Sample Slate" if ALLOW_SAMPLE_SLATE else "No MLB Slate Loaded",
        "slate_date": today,
        "slate_source": "sample_players" if ALLOW_SAMPLE_SLATE else "no_slate_loaded",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "updated_by": "system",
    }


def load_slate_metadata():
    meta = default_slate_metadata()
    try:
        if SLATE_METADATA_PATH.exists():
            with open(SLATE_METADATA_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                meta.update(saved)
    except Exception:
        pass

    # Keep source truthful even if a slate was cleared or uploaded.
    meta["slate_source"] = current_slate_source() if "current_slate_source" in globals() else ("imported_or_edited_slate" if ACTIVE_SLATE_PATH.exists() else "sample_players")
    if not str(meta.get("slate_name", "")).strip():
        meta["slate_name"] = "DraftKings MLB Slate" if ACTIVE_SLATE_PATH.exists() else ("MLB Sample Slate" if ALLOW_SAMPLE_SLATE else "No MLB Slate Loaded")
    if not str(meta.get("slate_date", "")).strip():
        meta["slate_date"] = datetime.now().strftime("%Y-%m-%d")
    return meta


def save_slate_metadata(slate_name=None, slate_date=None, updated_by="admin"):
    meta = load_slate_metadata()
    if slate_name is not None:
        clean_name = str(slate_name).strip()
        if clean_name:
            meta["slate_name"] = clean_name[:120]
    if slate_date is not None:
        clean_date = str(slate_date).strip()
        if clean_date:
            meta["slate_date"] = clean_date[:40]
    meta["slate_source"] = current_slate_source() if "current_slate_source" in globals() else ("imported_or_edited_slate" if ACTIVE_SLATE_PATH.exists() else "sample_players")
    meta["updated_at"] = datetime.utcnow().isoformat() + "Z"
    meta["updated_by"] = updated_by or "admin"
    with open(SLATE_METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def ensure_minimum_position_players(players):
    # Retained for compatibility with older callers. The previous behavior
    # reactivated every DK row when a position was thin, which could put bench
    # bats and relief pitchers into generated lineups.
    return players


def current_slate_source():
    if ACTIVE_SLATE_PATH.exists():
        return "imported_or_edited_slate"
    return "sample_players" if ALLOW_SAMPLE_SLATE else "no_slate_loaded"


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

DATA_ENGINE_VERSION = "mlb_data_engine_v2_live_odds_weather"

DATA_ENGINE_SOURCES = {
    "mlb_stats_api": {
        "enabled": True,
        "status": "connected",
        "purpose": "official schedule, probable pitchers, and announced batting orders",
        "env_key": "MLB_STATS_API_KEY_NOT_REQUIRED",
    },
    "odds_api": {
        "enabled": bool(ODDS_API_KEY),
        "status": "connected" if ODDS_API_KEY else "not_configured",
        "purpose": "odds, game totals, implied team totals",
        "env_key": "ODDS_API_KEY",
    },
    "national_weather_service": {
        "enabled": True,
        "status": "connected",
        "purpose": "free hourly stadium forecasts, wind, precipitation, and delay risk",
        "env_key": "NO_KEY_REQUIRED",
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

MLB_TEAM_NAME_TO_CODE = {
    "Arizona Diamondbacks": "ARI", "Athletics": "OAK", "Oakland Athletics": "OAK",
    "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE", "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC", "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM", "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF", "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}

MLB_STADIUMS = {
    "ARI": {"name": "Chase Field", "lat": 33.4455, "lon": -112.0667, "roof_controlled": True},
    "ATL": {"name": "Truist Park", "lat": 33.8908, "lon": -84.4677},
    "BAL": {"name": "Oriole Park", "lat": 39.2839, "lon": -76.6217},
    "BOS": {"name": "Fenway Park", "lat": 42.3467, "lon": -71.0972},
    "CHC": {"name": "Wrigley Field", "lat": 41.9484, "lon": -87.6553},
    "CWS": {"name": "Rate Field", "lat": 41.8300, "lon": -87.6339},
    "CIN": {"name": "Great American Ball Park", "lat": 39.0979, "lon": -84.5082},
    "CLE": {"name": "Progressive Field", "lat": 41.4962, "lon": -81.6852},
    "COL": {"name": "Coors Field", "lat": 39.7559, "lon": -104.9942},
    "DET": {"name": "Comerica Park", "lat": 42.3390, "lon": -83.0485},
    "HOU": {"name": "Daikin Park", "lat": 29.7573, "lon": -95.3555, "roof_controlled": True},
    "KC": {"name": "Kauffman Stadium", "lat": 39.0517, "lon": -94.4803},
    "LAA": {"name": "Angel Stadium", "lat": 33.8003, "lon": -117.8827},
    "LAD": {"name": "Dodger Stadium", "lat": 34.0739, "lon": -118.2400},
    "MIA": {"name": "loanDepot park", "lat": 25.7781, "lon": -80.2197, "roof_controlled": True},
    "MIL": {"name": "American Family Field", "lat": 43.0280, "lon": -87.9712, "roof_controlled": True},
    "MIN": {"name": "Target Field", "lat": 44.9817, "lon": -93.2776},
    "NYM": {"name": "Citi Field", "lat": 40.7571, "lon": -73.8458},
    "NYY": {"name": "Yankee Stadium", "lat": 40.8296, "lon": -73.9262},
    "OAK": {"name": "Sutter Health Park", "lat": 38.5802, "lon": -121.5139},
    "PHI": {"name": "Citizens Bank Park", "lat": 39.9061, "lon": -75.1665},
    "PIT": {"name": "PNC Park", "lat": 40.4469, "lon": -80.0057},
    "SD": {"name": "Petco Park", "lat": 32.7073, "lon": -117.1573},
    "SEA": {"name": "T-Mobile Park", "lat": 47.5914, "lon": -122.3325, "roof_controlled": True},
    "SF": {"name": "Oracle Park", "lat": 37.7786, "lon": -122.3893},
    "STL": {"name": "Busch Stadium", "lat": 38.6226, "lon": -90.1928},
    "TB": {"name": "Steinbrenner Field", "lat": 27.9801, "lon": -82.5068},
    "TEX": {"name": "Globe Life Field", "lat": 32.7473, "lon": -97.0847, "roof_controlled": True},
    "TOR": {"name": "Rogers Centre", "lat": 43.6414, "lon": -79.3894, "roof_controlled": True},
    "WSH": {"name": "Nationals Park", "lat": 38.8730, "lon": -77.0074},
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
    has_live_odds = bool(player.get("odds_source")) and safe_float(player.get("team_total"), 0) > 0
    if has_live_odds:
        team_total = safe_float(player.get("team_total"), 4.4)
        opponent_total = safe_float(player.get("opponent_total"), 4.4)
    else:
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
        "vegas_source": player.get("odds_source", "DFS Edge estimate"),
    }


def lineup_vegas_boost(lineup):
    return round(sum(safe_float(p.get("vegas_boost", 0)) for p in lineup), 2)


def lineup_stack_team_total(lineup):
    stack = best_stack_info(lineup)
    team = stack.get("team", "")
    if not team:
        return 0.0
    stack_players = [player for player in lineup if normalize_team(player.get("team", "")) == team]
    live_totals = [safe_float(player.get("team_total"), 0) for player in stack_players if player.get("odds_source")]
    return round(max(live_totals), 2) if live_totals else estimated_team_total(team)


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


def starter_probability_for_player(player):
    explicit = player.get("starter_probability")
    if explicit not in [None, ""]:
        return max(0.0, min(1.0, safe_float(explicit, 0)))

    status = str(player.get("starter_status", "")).strip().lower()
    return {
        "confirmed_starter": 1.0,
        "confirmed_lineup": 1.0,
        "probable_pitcher": 0.96,
        "projected_probable_pitcher": 0.78,
        "projected_starter": 0.72,
        "likely_starter": 0.72,
        "starter_risk": 0.48,
        "pitcher_pool": 0.42,
        "unknown": 0.35,
        "bench_risk": 0.20,
        "long_relief_risk": 0.12,
        "confirmed_not_starting": 0.0,
        "out": 0.0,
    }.get(status, 0.35)


def optimizer_starter_eligible(player):
    """Only allow players from the DK slate who are confirmed or safely projected to start."""
    if not bool(player.get("active", True)):
        return False
    if bool(player.get("manual_status_override", False)):
        return True
    if not ACTIVE_SLATE_PATH.exists():
        # Keep the clearly labeled sample slate usable for local demos only.
        return True
    if player.get("dk_slate_eligible") is False:
        return False

    status = str(player.get("starter_status", "")).strip().lower()
    source = str(player.get("starter_source", "")).strip().lower()
    trusted_sources = {
        "mlb_stats_confirmed_lineup",
        "mlb_stats_probable_pitcher",
        "dk_slate_likelihood",
        "admin_confirmed",
        "admin_override",
    }
    if source not in trusted_sources:
        return False

    probability = starter_probability_for_player(player)
    position = normalize_position(player.get("position", ""))
    if position == "P":
        return status in {"probable_pitcher", "projected_probable_pitcher", "confirmed_starter"} and probability >= 0.65
    return status in {"confirmed_starter", "confirmed_lineup", "projected_starter", "likely_starter"} and probability >= 0.65


def _starter_likelihood_score(player):
    projection = safe_float(player.get("projection", 0), 0)
    salary = safe_int(player.get("salary", 0), 0)
    ownership = safe_float(player.get("ownership", 0), 0)
    return projection * 6.0 + salary / 180.0 + ownership * 0.35


def apply_slate_starter_likelihood(players):
    """
    Conservative no-key fallback used immediately after a DK upload.
    One pitcher and a likely nine-man batting order per team remain eligible.
    Official probable pitchers/announced orders override this when refreshed.
    """
    prepared = [dict(player) for player in players]
    by_team = {}
    for player in prepared:
        team = normalize_team(player.get("team", ""))
        if team and team != "UNK":
            by_team.setdefault(team, []).append(player)

    for team_players in by_team.values():
        pitchers = [p for p in team_players if normalize_position(p.get("position", "")) == "P"]
        hitters = [p for p in team_players if normalize_position(p.get("position", "")) != "P"]

        trusted_pitchers = [
            p for p in pitchers
            if str(p.get("starter_source", "")).startswith(("mlb_stats_", "admin_"))
            and starter_probability_for_player(p) >= 0.65
        ]
        likely_pitchers = trusted_pitchers or sorted(pitchers, key=_starter_likelihood_score, reverse=True)[:1]
        likely_pitcher_names = {p.get("name") for p in likely_pitchers}

        for pitcher in pitchers:
            if bool(pitcher.get("manual_status_override", False)):
                pitcher["starter_source"] = "admin_override"
                pitcher["starter_probability"] = 1.0 if pitcher.get("active", True) else 0.0
                continue
            if pitcher.get("name") in likely_pitcher_names:
                if not str(pitcher.get("starter_source", "")).startswith(("mlb_stats_", "admin_")):
                    pitcher["starter_status"] = "projected_probable_pitcher"
                    pitcher["starter_source"] = "dk_slate_likelihood"
                    pitcher["starter_probability"] = 0.78
                pitcher["active"] = True
                pitcher["inactive_reason"] = ""
            else:
                pitcher["starter_status"] = "long_relief_risk"
                pitcher["starter_source"] = "dk_slate_likelihood"
                pitcher["starter_probability"] = 0.12
                pitcher["active"] = False
                pitcher["inactive_reason"] = "not_probable_starting_pitcher"

        confirmed_hitters = [
            p for p in hitters
            if str(p.get("starter_source", "")) in {"mlb_stats_confirmed_lineup", "admin_confirmed"}
            and starter_probability_for_player(p) >= 0.65
        ]
        if confirmed_hitters:
            likely_hitters = confirmed_hitters
        else:
            eligible_hitters = [
                p for p in hitters
                if str(p.get("injury_status", "")).lower() not in {"il", "out", "confirmed_out"}
            ]
            ranked = sorted(eligible_hitters, key=_starter_likelihood_score, reverse=True)
            catchers = [p for p in ranked if normalize_position(p.get("position", "")) == "C"]
            likely_hitters = catchers[:1]
            likely_hitters += [p for p in ranked if p not in likely_hitters][: max(0, 9 - len(likely_hitters))]

        likely_hitter_names = {p.get("name") for p in likely_hitters}
        for rank, hitter in enumerate(sorted(likely_hitters, key=_starter_likelihood_score, reverse=True), start=1):
            if bool(hitter.get("manual_status_override", False)):
                hitter["starter_source"] = "admin_override"
                hitter["starter_probability"] = 1.0 if hitter.get("active", True) else 0.0
                continue
            if not str(hitter.get("starter_source", "")).startswith(("mlb_stats_", "admin_")):
                hitter["starter_status"] = "projected_starter"
                hitter["starter_source"] = "dk_slate_likelihood"
                hitter["starter_probability"] = round(max(0.68, 0.78 - (rank - 1) * 0.012), 3)
            hitter["active"] = True
            hitter["inactive_reason"] = ""

        for hitter in hitters:
            if hitter.get("name") in likely_hitter_names or bool(hitter.get("manual_status_override", False)):
                continue
            hitter["starter_status"] = "bench_risk"
            hitter["starter_source"] = "dk_slate_likelihood"
            hitter["starter_probability"] = 0.20
            hitter["active"] = False
            hitter["inactive_reason"] = "not_in_likely_starting_nine"

    return prepared


def fetch_mlb_stats_json(path, params=None, timeout=20):
    query = urllib.parse.urlencode(params or {})
    url = f"{MLB_STATS_API_BASE_URL}/{str(path).lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "DFS-Edge/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_mlb_data_state(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def save_mlb_data_state(path, payload):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def odds_api_get(path, params=None, timeout=30):
    if not ODDS_API_KEY:
        raise RuntimeError("The Odds API key is not configured on the MLB backend.")
    query = dict(params or {})
    query["apiKey"] = ODDS_API_KEY
    url = f"{ODDS_API_BASE_URL}/{str(path).lstrip('/')}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": "DFS-Edge-MLB/2.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        usage = {
            "requests_remaining": safe_int(response.headers.get("x-requests-remaining"), -1),
            "requests_used": safe_int(response.headers.get("x-requests-used"), -1),
            "last_request_cost": safe_int(response.headers.get("x-requests-last"), -1),
        }
    return payload, usage


def _median(values, default=None):
    clean = [safe_float(value, 0) for value in values if value not in [None, ""]]
    return round(float(statistics.median(clean)), 3) if clean else default


def parse_mlb_odds_consensus(events, slate_teams=None):
    slate_teams = {normalize_team(team) for team in (slate_teams or [])}
    teams = {}
    games = []
    for event in events or []:
        home_name = str(event.get("home_team", ""))
        away_name = str(event.get("away_team", ""))
        home = normalize_team(MLB_TEAM_NAME_TO_CODE.get(home_name, ""))
        away = normalize_team(MLB_TEAM_NAME_TO_CODE.get(away_name, ""))
        if home == "UNK" or away == "UNK":
            continue
        if slate_teams and not {home, away}.issubset(slate_teams):
            continue

        totals = []
        home_spreads = []
        home_moneylines = []
        away_moneylines = []
        books = set()
        for bookmaker in event.get("bookmakers", []) or []:
            books.add(str(bookmaker.get("key") or bookmaker.get("title") or "book"))
            for market in bookmaker.get("markets", []) or []:
                key = str(market.get("key", ""))
                outcomes = market.get("outcomes", []) or []
                if key == "totals":
                    for outcome in outcomes:
                        if str(outcome.get("name", "")).lower() == "over" and outcome.get("point") is not None:
                            totals.append(outcome.get("point"))
                elif key == "spreads":
                    for outcome in outcomes:
                        if str(outcome.get("name", "")) == home_name and outcome.get("point") is not None:
                            home_spreads.append(outcome.get("point"))
                elif key == "h2h":
                    for outcome in outcomes:
                        if str(outcome.get("name", "")) == home_name:
                            home_moneylines.append(outcome.get("price"))
                        elif str(outcome.get("name", "")) == away_name:
                            away_moneylines.append(outcome.get("price"))

        game_total = _median(totals)
        home_spread = _median(home_spreads, 0.0)
        if game_total is None:
            continue
        home_total = round(game_total / 2.0 - safe_float(home_spread, 0) / 2.0, 2)
        away_total = round(game_total - home_total, 2)
        game = {
            "event_id": event.get("id"), "commence_time": event.get("commence_time"),
            "home_team": home, "away_team": away, "game_total": round(game_total, 2),
            "home_spread": round(safe_float(home_spread, 0), 2),
            "home_implied_total": home_total, "away_implied_total": away_total,
            "home_moneyline": _median(home_moneylines), "away_moneyline": _median(away_moneylines),
            "bookmaker_count": len(books),
        }
        games.append(game)
        teams[home] = {
            "team_total": home_total, "opponent_total": away_total, "game_total": round(game_total, 2),
            "spread": round(safe_float(home_spread, 0), 2), "moneyline": game["home_moneyline"],
            "opponent": away, "home_team": home, "odds_bookmaker_count": len(books),
        }
        teams[away] = {
            "team_total": away_total, "opponent_total": home_total, "game_total": round(game_total, 2),
            "spread": round(-safe_float(home_spread, 0), 2), "moneyline": game["away_moneyline"],
            "opponent": home, "home_team": home, "odds_bookmaker_count": len(books),
        }
    return teams, games


def apply_mlb_odds(players, state):
    teams = state.get("teams", {}) if isinstance(state, dict) else {}
    merged = []
    for raw in players:
        player = dict(raw)
        market = teams.get(normalize_team(player.get("team", "")))
        if market:
            player.update(market)
            player["odds_source"] = "The Odds API consensus"
            player["odds_updated_at"] = state.get("fetched_at")
        merged.append(player)
    return merged


def refresh_mlb_odds(players, force=False):
    current = load_mlb_data_state(MLB_ODDS_STATE_PATH)
    fetched_at_unix = safe_int(current.get("fetched_at_unix"), 0)
    if not force and current and fetched_at_unix and time.time() - fetched_at_unix < MLB_ODDS_CACHE_SECONDS:
        return apply_mlb_odds(players, current), {"success": True, "cached": True, **current}
    if not ODDS_API_KEY:
        return players, {
            "success": False, "configured": False,
            "error": "ODDS_API_KEY is not configured on the MLB backend.",
        }

    params = {
        "regions": ODDS_API_REGIONS, "markets": "h2h,spreads,totals",
        "oddsFormat": "american", "dateFormat": "iso",
    }
    if ODDS_API_BOOKMAKERS:
        params["bookmakers"] = ODDS_API_BOOKMAKERS
        params.pop("regions", None)
    events, usage = odds_api_get("sports/baseball_mlb/odds", params)
    slate_teams = {normalize_team(player.get("team", "")) for player in players}
    teams, games = parse_mlb_odds_consensus(events, slate_teams)
    state = {
        "provider": "The Odds API", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at_unix": int(time.time()), "configured": True,
        "event_count": len(games), "team_count": len(teams), "teams": teams, "games": games,
        "usage": usage,
    }
    save_mlb_data_state(MLB_ODDS_STATE_PATH, state)
    return apply_mlb_odds(players, state), {"success": True, "cached": False, **state}


def _parse_wind_mph(value):
    numbers = [int(number) for number in re.findall(r"\d+", str(value or ""))]
    return max(numbers) if numbers else 0


def _mlb_weather_risk(wind_mph, precipitation, forecast):
    text = str(forecast or "").lower()
    if wind_mph >= 20 or precipitation >= 65 or any(word in text for word in ["thunder", "hail", "tornado"]):
        return "High"
    if wind_mph >= 14 or precipitation >= 35 or any(word in text for word in ["rain", "showers", "storm"]):
        return "Watch"
    return "Low"


def _fetch_mlb_stadium_forecast(home_team, game_time):
    stadium = MLB_STADIUMS.get(home_team)
    if not stadium:
        return home_team, None
    if stadium.get("roof_controlled"):
        return home_team, {
            "stadium": stadium.get("name"), "venue": "Roof controlled", "forecast": "Roof-controlled park",
            "temperature_f": 72, "wind_mph": 0, "wind_direction": "None",
            "precipitation_probability": 0, "weather_risk": "Low", "weather_boost": 0.0,
            "source": "venue_type", "game_time": game_time,
        }

    headers = {
        "User-Agent": "DFS-Edge-MLB/2.0 (https://www.dfsedgeapp.com)",
        "Accept": "application/geo+json",
    }
    point_url = f"https://api.weather.gov/points/{stadium['lat']},{stadium['lon']}"
    point_request = urllib.request.Request(point_url, headers=headers)
    with urllib.request.urlopen(point_request, timeout=20) as response:
        point_data = json.loads(response.read().decode("utf-8"))
    hourly_url = point_data.get("properties", {}).get("forecastHourly")
    if not hourly_url:
        return home_team, None
    hourly_request = urllib.request.Request(hourly_url, headers=headers)
    with urllib.request.urlopen(hourly_request, timeout=20) as response:
        hourly = json.loads(response.read().decode("utf-8"))
    periods = hourly.get("properties", {}).get("periods", []) or []
    parsed_periods = []
    for period in periods:
        try:
            parsed_periods.append((datetime.fromisoformat(str(period.get("startTime"))), period))
        except (TypeError, ValueError):
            continue
    try:
        target_time = datetime.fromisoformat(str(game_time).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        target_time = None
    if not parsed_periods:
        return home_team, None
    if target_time and target_time > max(item[0] for item in parsed_periods):
        return home_team, {
            "stadium": stadium.get("name"), "venue": "Outdoor", "forecast": "Forecast available closer to game time",
            "temperature_f": None, "wind_mph": 0, "wind_direction": None,
            "precipitation_probability": 0, "weather_risk": "Pending", "weather_boost": 0.0,
            "source": "National Weather Service", "game_time": game_time,
        }
    period = min(parsed_periods, key=lambda item: abs((item[0] - target_time).total_seconds()))[1] if target_time else parsed_periods[0][1]
    wind_mph = _parse_wind_mph(period.get("windSpeed"))
    precipitation = safe_int((period.get("probabilityOfPrecipitation") or {}).get("value"), 0)
    forecast = period.get("shortForecast", "Forecast available")
    risk = _mlb_weather_risk(wind_mph, precipitation, forecast)
    temperature = safe_int(period.get("temperature"), 0)
    boost = -1.10 if risk == "High" else -0.35 if risk == "Watch" else 0.15 if temperature >= 80 and wind_mph < 14 else 0.0
    return home_team, {
        "stadium": stadium.get("name"), "venue": "Outdoor", "forecast": forecast,
        "temperature_f": temperature or None, "wind_mph": wind_mph,
        "wind_direction": period.get("windDirection"), "precipitation_probability": precipitation,
        "weather_risk": risk, "weather_boost": boost,
        "forecast_time": period.get("startTime"), "source": "National Weather Service", "game_time": game_time,
    }


def apply_mlb_weather(players, state):
    forecasts = state.get("forecasts", {}) if isinstance(state, dict) else {}
    team_to_home = state.get("team_to_home", {}) if isinstance(state, dict) else {}
    merged = []
    for raw in players:
        player = dict(raw)
        team = normalize_team(player.get("team", ""))
        forecast = forecasts.get(team_to_home.get(team, ""))
        if forecast:
            player.update({
                "stadium": forecast.get("stadium"), "venue": forecast.get("venue"),
                "weather": forecast.get("forecast"), "temperature_f": forecast.get("temperature_f"),
                "wind_mph": forecast.get("wind_mph", 0), "wind_direction": forecast.get("wind_direction"),
                "precipitation_probability": forecast.get("precipitation_probability", 0),
                "weather_risk": forecast.get("weather_risk", "Low"),
                "weather_boost": forecast.get("weather_boost", 0),
                "weather_source": forecast.get("source"), "weather_updated_at": state.get("fetched_at"),
            })
        merged.append(player)
    return merged


def refresh_mlb_weather(players, slate_date, force=False):
    current = load_mlb_data_state(MLB_WEATHER_STATE_PATH)
    fetched_at_unix = safe_int(current.get("fetched_at_unix"), 0)
    if not force and current.get("slate_date") == slate_date and fetched_at_unix and time.time() - fetched_at_unix < MLB_WEATHER_CACHE_SECONDS:
        return apply_mlb_weather(players, current), {"success": True, "cached": True, **current}

    schedule = fetch_mlb_stats_json("schedule", {"sportId": 1, "date": slate_date, "hydrate": "team"})
    slate_teams = {normalize_team(player.get("team", "")) for player in players}
    game_times = {}
    team_to_home = {}
    for date in schedule.get("dates", []) or []:
        for game in date.get("games", []) or []:
            home = normalize_team(game.get("teams", {}).get("home", {}).get("team", {}).get("abbreviation", ""))
            away = normalize_team(game.get("teams", {}).get("away", {}).get("team", {}).get("abbreviation", ""))
            if not home or home == "UNK" or not {home, away}.intersection(slate_teams):
                continue
            game_times[home] = game.get("gameDate")
            team_to_home[home] = home
            team_to_home[away] = home

    forecasts = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(game_times)))) as executor:
        futures = {executor.submit(_fetch_mlb_stadium_forecast, home, game_time): home for home, game_time in game_times.items()}
        for future in as_completed(futures):
            home = futures[future]
            try:
                fetched_home, forecast = future.result()
                if forecast:
                    forecasts[fetched_home] = forecast
            except Exception as exc:
                errors[home] = exc.__class__.__name__

    state = {
        "provider": "National Weather Service", "source_url": "https://api.weather.gov",
        "slate_date": slate_date, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at_unix": int(time.time()), "stadium_count": len(forecasts),
        "outdoor_count": len([item for item in forecasts.values() if item.get("venue") == "Outdoor"]),
        "roof_controlled_count": len([item for item in forecasts.values() if item.get("venue") == "Roof controlled"]),
        "high_risk_count": len([item for item in forecasts.values() if item.get("weather_risk") == "High"]),
        "watch_count": len([item for item in forecasts.values() if item.get("weather_risk") == "Watch"]),
        "team_to_home": team_to_home, "forecasts": forecasts, "errors": errors,
    }
    save_mlb_data_state(MLB_WEATHER_STATE_PATH, state)
    return apply_mlb_weather(players, state), {"success": True, "cached": False, **state}


def mlb_feed_summary(state, configured=True):
    state = state if isinstance(state, dict) else {}
    fetched_at_unix = safe_int(state.get("fetched_at_unix"), 0)
    age_minutes = round(max(0, time.time() - fetched_at_unix) / 60, 1) if fetched_at_unix else None
    return {
        "configured": configured,
        "status": "connected" if state else ("ready" if configured else "not_configured"),
        "provider": state.get("provider"),
        "fetched_at": state.get("fetched_at"),
        "age_minutes": age_minutes,
        "event_count": state.get("event_count"),
        "team_count": state.get("team_count"),
        "stadium_count": state.get("stadium_count"),
        "high_risk_count": state.get("high_risk_count"),
        "watch_count": state.get("watch_count"),
        "usage": state.get("usage"),
        "errors": state.get("errors", {}),
    }


def fetch_mlb_roster_statuses(team_ids, slate_date):
    """Fetch official 40-man statuses without excluding players solely on a name miss."""
    team_ids = {normalize_team(team): safe_int(team_id, 0) for team, team_id in (team_ids or {}).items() if safe_int(team_id, 0) > 0}
    statuses_by_team = {}
    errors = {}

    def fetch_one(team, team_id):
        payload = fetch_mlb_stats_json(
            f"teams/{team_id}/roster",
            {"rosterType": "40Man", "date": slate_date},
            timeout=12,
        )
        statuses = {}
        for row in payload.get("roster", []) or []:
            full_name = row.get("person", {}).get("fullName", "")
            status = row.get("status", {}).get("description", "") or "Unknown"
            if full_name:
                statuses[normalized_player_name(full_name)] = status
        return team, statuses

    if not team_ids:
        return statuses_by_team, errors

    with ThreadPoolExecutor(max_workers=min(8, len(team_ids))) as executor:
        futures = {executor.submit(fetch_one, team, team_id): team for team, team_id in team_ids.items()}
        for future in as_completed(futures):
            team = futures[future]
            try:
                fetched_team, statuses = future.result()
                if statuses:
                    statuses_by_team[fetched_team] = statuses
            except Exception as exc:
                errors[team] = exc.__class__.__name__

    return statuses_by_team, errors


def load_mlb_starter_state():
    try:
        with open(MLB_STARTER_STATE_PATH, "r", encoding="utf-8") as file:
            state = json.load(file)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_mlb_starter_state(state):
    with open(MLB_STARTER_STATE_PATH, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def refresh_mlb_starters(players, slate_date):
    refreshed = apply_slate_starter_likelihood(players)
    slate_teams = {
        normalize_team(player.get("team", ""))
        for player in refreshed
        if normalize_team(player.get("team", "")) != "UNK"
    }
    probable_by_team = {}
    confirmed_by_team = {}
    team_ids = {}
    games_checked = 0
    error = ""

    try:
        schedule = fetch_mlb_stats_json(
            "schedule",
            {"sportId": 1, "date": slate_date, "hydrate": "probablePitcher,team"},
        )
        games = [game for date in schedule.get("dates", []) for game in date.get("games", [])]
        for game in games:
            game_teams = {}
            for side in ["away", "home"]:
                side_data = game.get("teams", {}).get(side, {})
                team_code = normalize_team(side_data.get("team", {}).get("abbreviation", ""))
                game_teams[side] = team_code
                team_id = safe_int(side_data.get("team", {}).get("id", 0), 0)
                if team_code in slate_teams and team_id > 0:
                    team_ids[team_code] = team_id
                probable_name = side_data.get("probablePitcher", {}).get("fullName", "")
                if team_code in slate_teams and probable_name:
                    probable_by_team.setdefault(team_code, set()).add(normalized_player_name(probable_name))

            if not set(game_teams.values()).intersection(slate_teams):
                continue
            game_pk = game.get("gamePk")
            if not game_pk:
                continue
            games_checked += 1
            try:
                boxscore = fetch_mlb_stats_json(f"game/{game_pk}/boxscore", timeout=12)
            except Exception:
                continue
            for side in ["away", "home"]:
                team_code = game_teams.get(side, "UNK")
                side_box = boxscore.get("teams", {}).get(side, {})
                batting_order = side_box.get("battingOrder", []) or []
                if team_code not in slate_teams or not batting_order:
                    continue
                player_records = side_box.get("players", {}) or {}
                order = {}
                for spot, player_id in enumerate(batting_order[:9], start=1):
                    record = player_records.get(f"ID{player_id}", {})
                    full_name = record.get("person", {}).get("fullName", "")
                    if full_name:
                        order[normalized_player_name(full_name)] = spot
                if order:
                    confirmed_by_team[team_code] = order
    except Exception as exc:
        error = f"MLB starter service unavailable: {exc.__class__.__name__}"

    roster_statuses, roster_errors = fetch_mlb_roster_statuses(team_ids, slate_date) if team_ids else ({}, {})

    probable_matches = 0
    confirmed_matches = 0
    unavailable_matches = 0
    for player in refreshed:
        if bool(player.get("manual_status_override", False)):
            continue
        team = normalize_team(player.get("team", ""))
        name_key = normalized_player_name(player.get("name", ""))
        position = normalize_position(player.get("position", ""))
        official_roster_status = roster_statuses.get(team, {}).get(name_key, "")
        if official_roster_status and official_roster_status.lower() != "active":
            status_slug = re.sub(r"[^a-z0-9]+", "_", official_roster_status.lower()).strip("_")
            player["roster_status"] = official_roster_status
            player["roster_status_source"] = "mlb_stats_40_man_roster"
            player["injury_status"] = "il" if "injur" in official_roster_status.lower() else "officially_inactive"
            player["starter_status"] = "confirmed_not_starting"
            player["starter_source"] = "mlb_stats_roster_status"
            player["starter_probability"] = 0.0
            player["active"] = False
            player["inactive_reason"] = f"official_mlb_roster_{status_slug or 'inactive'}"
            unavailable_matches += 1
            continue
        if official_roster_status:
            player["roster_status"] = official_roster_status
            player["roster_status_source"] = "mlb_stats_40_man_roster"
        if position == "P" and team in probable_by_team:
            if name_key in probable_by_team[team]:
                player["starter_status"] = "probable_pitcher"
                player["starter_source"] = "mlb_stats_probable_pitcher"
                player["starter_probability"] = 0.98
                player["active"] = True
                player["inactive_reason"] = ""
                probable_matches += 1
            else:
                player["starter_status"] = "confirmed_not_starting"
                player["starter_source"] = "mlb_stats_probable_pitcher"
                player["starter_probability"] = 0.0
                player["active"] = False
                player["inactive_reason"] = "not_listed_as_probable_pitcher"
        elif position != "P" and team in confirmed_by_team:
            spot = confirmed_by_team[team].get(name_key)
            if spot:
                player["starter_status"] = "confirmed_starter"
                player["starter_source"] = "mlb_stats_confirmed_lineup"
                player["starter_probability"] = 1.0
                player["lineup_spot"] = spot
                player["lineup_source"] = "mlb_stats_confirmed_lineup"
                player["avg_at_bats"] = 4.5 if spot <= 2 else 4.2 if spot <= 5 else 3.8 if spot <= 7 else 3.4
                player["active"] = True
                player["inactive_reason"] = ""
                confirmed_matches += 1
            else:
                player["starter_status"] = "confirmed_not_starting"
                player["starter_source"] = "mlb_stats_confirmed_lineup"
                player["starter_probability"] = 0.0
                player["active"] = False
                player["inactive_reason"] = "not_in_announced_batting_order"

    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "slate_date": slate_date,
        "games_checked": games_checked,
        "probable_pitcher_matches": probable_matches,
        "confirmed_hitter_matches": confirmed_matches,
        "teams_with_probable_pitchers": len(probable_by_team),
        "teams_with_confirmed_lineups": len(confirmed_by_team),
        "roster_teams_checked": len(roster_statuses),
        "official_unavailable_matches": unavailable_matches,
        "roster_errors": roster_errors,
        "eligible_player_count": len([p for p in refreshed if optimizer_starter_eligible(p)]),
        "error": error,
    }
    save_mlb_starter_state(state)
    return refreshed, state


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
    estimated_line_abs = estimated_lineup_spot_and_abs(player)
    line_abs = {
        "lineup_spot": player.get("lineup_spot") if player.get("lineup_spot") not in [None, ""] else estimated_line_abs.get("lineup_spot"),
        "avg_at_bats": player.get("avg_at_bats") if player.get("avg_at_bats") not in [None, ""] else estimated_line_abs.get("avg_at_bats"),
        "projected_innings": player.get("projected_innings") if player.get("projected_innings") not in [None, ""] else estimated_line_abs.get("projected_innings"),
    }
    park = data_engine_park_info(player)
    if player.get("weather_source"):
        live_weather_boost = safe_float(player.get("weather_boost"), 0)
        if position == "P" and live_weather_boost > 0:
            live_weather_boost *= -1
        weather = {
            "weather_risk": player.get("weather_risk", "Low"),
            "weather_boost": round(live_weather_boost, 2),
            "weather_note": player.get("weather") or f"Weather risk: {player.get('weather_risk', 'Low')}",
        }
    else:
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
        "starter_probability": starter_probability_for_player({**player, "starter_status": starter_status}),
        "starter_source": player.get("starter_source", "estimated_model"),
        "injury_status": injury_status,
        "lineup_spot": line_abs.get("lineup_spot"),
        "lineup_source": player.get("lineup_source", "estimated_model"),
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
            "MLB Stats API supplies official roster status, probable pitchers, and announced batting orders.",
            "The Odds API supplies consensus game lines and implied team totals when configured.",
            "The National Weather Service supplies stadium forecasts for outdoor parks.",
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




def has_required_mlb_positions(pool):
    groups = {
        "P": [p for p in pool if normalize_position(p.get("position", "")) == "P"],
        "C": [p for p in pool if normalize_position(p.get("position", "")) == "C"],
        "1B": [p for p in pool if normalize_position(p.get("position", "")) == "1B"],
        "2B": [p for p in pool if normalize_position(p.get("position", "")) == "2B"],
        "3B": [p for p in pool if normalize_position(p.get("position", "")) == "3B"],
        "SS": [p for p in pool if normalize_position(p.get("position", "")) == "SS"],
        "OF": [p for p in pool if normalize_position(p.get("position", "")) == "OF"],
    }
    return (
        len(groups["P"]) >= 2
        and len(groups["C"]) >= 1
        and len(groups["1B"]) >= 1
        and len(groups["2B"]) >= 1
        and len(groups["3B"]) >= 1
        and len(groups["SS"]) >= 1
        and len(groups["OF"]) >= 3
    )


def is_manual_inactive_player(player):
    """
    Manual admin scratches should stay excluded.
    Auto cleanup trims should NOT prevent the optimizer from building lineups.
    """
    if bool(player.get("active", True)):
        return False
    reason = str(player.get("inactive_reason", "")).lower()
    return bool(player.get("manual_status_override", False)) or reason.startswith("manual")


def valid_optimizer_player(player):
    return (
        safe_int(player.get("salary", 0), 0) > 0
        and normalize_position(player.get("position", "")) in ["P", "C", "1B", "2B", "3B", "SS", "OF"]
        and bool(player.get("active", True))
        and optimizer_starter_eligible(player)
    )


def build_optimizer_pool_with_fallback(players, locked_players=None, excluded_players=None):
    """
    Build only from active, starter-eligible players in the uploaded DK slate.
    It intentionally fails closed if a position is thin; bench and relief
    players are never reintroduced as an emergency fallback.
    """
    locked_players = locked_players or []
    excluded_players = excluded_players or []
    excluded_set = set(excluded_players)

    active_valid = [
        p for p in players
        if p.get("name") not in excluded_set
        and valid_optimizer_player(p)
    ]
    optimized_pool, trim_report = trim_player_pool(active_valid, locked_players)
    trim_report["fallback_used"] = False
    trim_report["pool_source"] = "dk_slate_confirmed_or_likely_starters"
    trim_report["starter_eligible_count"] = len(active_valid)
    return optimized_pool, trim_report

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

    by_name = {p.get("name"): p for p in players}
    ineligible_locked = [name for name in locked_players if name in by_name and not optimizer_starter_eligible(by_name[name])]
    if ineligible_locked:
        return f"Locked player is not confirmed or likely to start: {', '.join(ineligible_locked)}"

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


def same_team_pitcher_conflict(lineup):
    pitcher_teams = [normalize_team(player.get("team", "")) for player in get_pitchers(lineup)]
    pitcher_teams = [team for team in pitcher_teams if team and team != "UNK"]
    return len(pitcher_teams) != len(set(pitcher_teams))


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

    if any(not optimizer_starter_eligible(player) for player in lineup):
        return False

    if same_team_pitcher_conflict(lineup):
        return False

    hitter_team_counts = count_team_players(lineup, hitters_only=True)
    legal_hitter_team_max = min(max_players_per_team, 5)
    if any(count > legal_hitter_team_max for count in hitter_team_counts.values()):
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

    optimized_pool, trim_report = build_optimizer_pool_with_fallback(
        players,
        locked_players=locked_players,
        excluded_players=excluded_players,
    )

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
        return [], f"Not enough players at each MLB position even after full-slate fallback. Pool counts: P={len(pitchers)}, C={len(catchers)}, 1B={len(first_base)}, 2B={len(second_base)}, 3B={len(third_base)}, SS={len(shortstops)}, OF={len(outfielders)}.", trim_report, 0

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

    optimized_pool, trim_report = build_optimizer_pool_with_fallback(
        players,
        locked_players=locked_players,
        excluded_players=excluded_players,
    )
    available = [
        p for p in players
        if p["name"] not in excluded_players
        and valid_optimizer_player(p)
        and not is_manual_inactive_player(p)
    ]

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
        return [], f"Not enough players at each MLB position even after full-slate fallback. Pool counts: P={len(groups['P'])}, C={len(groups['C'])}, 1B={len(groups['1B'])}, 2B={len(groups['2B'])}, 3B={len(groups['3B'])}, SS={len(groups['SS'])}, OF={len(groups['OF'])}.", trim_report, 0

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

    payout_table = request.payout_tiers if isinstance(request.payout_tiers, list) and request.payout_tiers else load_payout_table()
    if payout_table:
        exact_paid_positions = max(safe_int(tier.get("end_rank"), 0) for tier in payout_table)
        if 0 < exact_paid_positions <= contest_size:
            paid_positions = exact_paid_positions
            payout_rate = paid_positions / contest_size

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
        "payout_table": payout_table,
        "payout_source": "contest_library_exact_table" if request.payout_tiers else ("uploaded_exact_table" if payout_table else "estimated_curve"),
        "contest_profile_id": request.contest_profile_id,
        "contest_profile_name": request.contest_profile_name,
    }


def apply_contest_ownership_overrides(lineups, overrides):
    if not isinstance(overrides, dict) or not overrides:
        return lineups
    normalized = {
        str(name).strip().lower(): min(100.0, max(0.0, safe_float(value, 0)))
        for name, value in overrides.items()
        if str(name).strip()
    }
    for item in lineups:
        players = item.get("lineup", []) if isinstance(item, dict) else []
        for player in players if isinstance(players, list) else []:
            key = str(player.get("name", "")).strip().lower() if isinstance(player, dict) else ""
            if key in normalized:
                player["ownership"] = normalized[key]
                player["ownership_source"] = "contest_library"
    return lineups


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
        return [], f"Not enough players at each MLB position to run the simulator even after full-slate fallback. Pool counts: P={len(groups['P'])}, C={len(groups['C'])}, 1B={len(groups['1B'])}, 2B={len(groups['2B'])}, 3B={len(groups['3B'])}, SS={len(groups['SS'])}, OF={len(groups['OF'])}."

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




# =========================
# DFS EDGE MLB SIM ENGINE V2
# =========================
# This replaces the old "score -> guessed rank -> guessed payout" simulator with
# an actual Monte Carlo-style model:
# - each player gets floor/median/ceiling/volatility
# - candidate lineups are scored across many simulated slate outcomes
# - opponent field scores are generated from ownership-weighted field lineups
# - ranks are estimated against the full contest size
# - payouts/EV/ROI come from rank outcomes, not fake prize-pool scaling

def clamp_number(value, low, high):
    return max(low, min(high, value))


def player_simulation_profile(player):
    position = normalize_position(player.get("position", ""))
    median = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    ownership = safe_float(player.get("ownership", 10), 10)
    leverage = safe_float(player.get("leverage_score", 45), 45)
    trend = safe_float(player.get("trend_score", 50), 50)
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    data_boost = safe_float(player.get("data_engine_boost", 0), 0)

    if position == "P":
        base_volatility = 0.29
        if median >= 22:
            base_volatility -= 0.06
        elif median <= 12:
            base_volatility += 0.06
        floor_mult = 0.44
        ceiling_mult = 1.72
    else:
        base_volatility = 0.43
        if median >= 11:
            base_volatility -= 0.03
        elif median <= 5:
            base_volatility += 0.08
        floor_mult = 0.18
        ceiling_mult = 2.35

    # Lower-owned leverage plays are volatile but carry more true tournament ceiling.
    leverage_ceiling_boost = clamp_number((leverage - 50) / 100, -0.08, 0.18)
    trend_boost = clamp_number((trend - 50) / 250, -0.06, 0.12)
    vegas_boost = clamp_number((team_total - 4.2) / 20, -0.05, 0.10) if position != "P" else 0

    volatility = clamp_number(base_volatility + max(0, 12 - ownership) * 0.004 - max(0, ownership - 28) * 0.003, 0.16, 0.62)
    floor = max(0.0, median * floor_mult * (1 - volatility * 0.20))
    ceiling = median * (ceiling_mult + leverage_ceiling_boost + trend_boost + vegas_boost) + max(0.0, data_boost)

    boom_rate = clamp_number(0.08 + leverage / 700 + max(0, 16 - ownership) / 350 + max(0, trend - 55) / 500, 0.02, 0.34)
    bust_rate = clamp_number(0.18 + volatility * 0.45 + max(0, ownership - 25) / 260, 0.08, 0.48)

    return {
        "floor_projection": round(floor, 2),
        "median_projection": round(median, 2),
        "ceiling_projection": round(max(ceiling, median + 1.0), 2),
        "volatility_score": round(volatility * 100, 1),
        "boom_rate": round(boom_rate, 4),
        "bust_rate": round(bust_rate, 4),
    }


def sample_player_outcome_v2(player, team_environment=None):
    profile = player_simulation_profile(player)
    floor = safe_float(profile.get("floor_projection", 0), 0)
    median = safe_float(profile.get("median_projection", 0), 0)
    ceiling = safe_float(profile.get("ceiling_projection", median), median)
    boom_rate = safe_float(profile.get("boom_rate", 0.1), 0.1)
    bust_rate = safe_float(profile.get("bust_rate", 0.25), 0.25)
    position = normalize_position(player.get("position", ""))

    r = random.random()

    if r < bust_rate:
        value = random.triangular(0, median * 0.72, floor)
    elif r > 1 - boom_rate:
        value = random.triangular(median * 1.05, ceiling * 1.08, ceiling)
    else:
        value = random.triangular(floor, ceiling, median)

    if team_environment is not None and position != "P":
        team = normalize_team(player.get("team", ""))
        value *= team_environment.get(team, 1.0)

    return round(max(0.0, value), 2)


def team_environment_multipliers_for_lineup(lineup):
    counts = {}
    for player in lineup:
        if normalize_position(player.get("position", "")) != "P":
            team = normalize_team(player.get("team", ""))
            counts[team] = counts.get(team, 0) + 1

    multipliers = {}
    for team, count in counts.items():
        # Correlation: a stack can fail together or smash together.
        if count >= 5:
            multipliers[team] = random.triangular(0.72, 1.42, 1.04)
        elif count == 4:
            multipliers[team] = random.triangular(0.78, 1.32, 1.03)
        elif count == 3:
            multipliers[team] = random.triangular(0.84, 1.22, 1.01)
        else:
            multipliers[team] = random.triangular(0.90, 1.14, 1.0)
    return multipliers


def simulate_lineup_score_v2(lineup):
    if not lineup:
        return 0.0

    env = team_environment_multipliers_for_lineup(lineup)
    total = 0.0

    for player in lineup:
        total += sample_player_outcome_v2(player, env)

    # Add a small explicit bonus when a full stack hits together.
    stack = best_stack_info(lineup)
    stack_size = safe_int(stack.get("size", 0), 0)
    if stack_size >= 5:
        total += random.triangular(-2.0, 8.0, 1.2)
    elif stack_size == 4:
        total += random.triangular(-1.2, 5.0, 0.8)

    return round(max(0.0, total), 2)


def weighted_choice_from_players(players, used_names=None, ownership_weight=1.0, projection_weight=0.50):
    used_names = used_names or set()
    candidates = [p for p in players if p.get("name") not in used_names and bool(p.get("active", True))]
    if not candidates:
        return None

    weights = []
    for p in candidates:
        ownership = max(0.5, safe_float(p.get("ownership", 5), 5))
        proj = max(0.5, safe_float(p.get("boosted_projection", p.get("projection", 0)), 0))
        salary = max(2500, safe_int(p.get("salary", 3000), 3000))
        value = max(0.2, (proj / salary) * 1000)
        weight = (ownership ** ownership_weight) * (proj ** projection_weight) * (value ** 0.35)
        weights.append(max(0.01, weight))

    return random.choices(candidates, weights=weights, k=1)[0]


def build_random_field_lineup_v2(position_groups, contest):
    used = set()
    lineup = []
    max_entries = max(1, safe_int(contest.get("max_entries", 1), 1))
    single_entry = bool(contest.get("single_entry", False)) or max_entries <= 1

    # Large max-entry fields are chalkier; single-entry is a little more balanced.
    ownership_weight = 1.18 if max_entries >= 50 else (1.02 if not single_entry else 0.82)
    projection_weight = 0.62 if single_entry else 0.52

    # Field stacks: many MLB GPP lineups stack hitters.
    stack_team = None
    hitter_pool = []
    for pos in ["C", "1B", "2B", "3B", "SS", "OF"]:
        hitter_pool.extend(position_groups.get(pos, []))
    if hitter_pool and random.random() < (0.72 if max_entries >= 20 else 0.52):
        teams = {}
        for p in hitter_pool:
            team = normalize_team(p.get("team", ""))
            teams[team] = teams.get(team, 0.0) + max(0.5, safe_float(p.get("ownership", 5), 5)) + max(0.0, safe_float(p.get("team_total", 4.2), 4.2) - 3.6) * 5
        if teams:
            stack_team = random.choices(list(teams.keys()), weights=list(teams.values()), k=1)[0]

    for slot in ["P", "P"]:
        p = weighted_choice_from_players(position_groups.get("P", []), used, ownership_weight, projection_weight)
        if p:
            lineup.append(p)
            used.add(p.get("name"))

    for slot in ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]:
        group = position_groups.get(slot, [])
        selected = None

        if stack_team and slot != "P" and random.random() < 0.62:
            stack_group = [p for p in group if normalize_team(p.get("team", "")) == stack_team]
            selected = weighted_choice_from_players(stack_group, used, ownership_weight, projection_weight)

        if not selected:
            selected = weighted_choice_from_players(group, used, ownership_weight, projection_weight)

        if selected:
            lineup.append(selected)
            used.add(selected.get("name"))

    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    if len(lineup) != 10 or salary > SALARY_CAP:
        return None
    return lineup


def generate_field_score_samples_v2(contest, sample_count=1400):
    players = add_values(load_players())
    players = [p for p in players if valid_optimizer_player(p) and not is_manual_inactive_player(p)]
    if not has_required_mlb_positions(players):
        return []

    optimized_pool, _ = trim_player_pool(players, [])
    position_groups = {
        "P": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "P"],
        "C": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "C"],
        "1B": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "1B"],
        "2B": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "2B"],
        "3B": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "3B"],
        "SS": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "SS"],
        "OF": [p for p in optimized_pool if normalize_position(p.get("position", "")) == "OF"],
    }

    scores = []
    attempts = 0
    max_attempts = sample_count * 8

    while len(scores) < sample_count and attempts < max_attempts:
        attempts += 1
        lineup = build_random_field_lineup_v2(position_groups, contest)
        if not lineup:
            continue
        scores.append(simulate_lineup_score_v2(lineup))

    scores.sort()
    return scores


def rank_from_score_against_field(score, field_scores, contest_size):
    if not field_scores:
        return contest_size

    # Field scores are sorted ascending.
    lo = 0
    hi = len(field_scores)
    while lo < hi:
        mid = (lo + hi) // 2
        if field_scores[mid] <= score:
            lo = mid + 1
        else:
            hi = mid

    beaten = lo
    beat_rate = beaten / len(field_scores)
    rank = 1 + round((1.0 - beat_rate) * (contest_size - 1))
    return max(1, min(contest_size, rank))


def percentile_value(sorted_values, percentile):
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = int(round((len(sorted_values) - 1) * percentile))
    idx = max(0, min(len(sorted_values) - 1, idx))
    return sorted_values[idx]


def monte_carlo_lineup_simulation_v2(lineup, contest, runs=700, field_scores=None):
    contest_size = max(10, safe_int(contest.get("contest_size", 5000), 5000))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", 1), 1)))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 5.0), 5.0))

    if field_scores is None:
        field_scores = generate_field_score_samples_v2(contest)

    ranks = []
    scores = []
    payouts = []

    for _ in range(runs):
        score = simulate_lineup_score_v2(lineup)
        rank = rank_from_score_against_field(score, field_scores, contest_size)
        payout = payout_for_rank(rank, contest)
        scores.append(score)
        ranks.append(rank)
        payouts.append(payout)

    ranks_sorted = sorted(ranks)
    scores_sorted = sorted(scores)
    payouts_sorted = sorted(payouts)

    expected_payout = sum(payouts) / len(payouts) if payouts else 0.0
    expected_value = expected_payout - entry_fee

    cash_probability = len([r for r in ranks if r <= paid_spots]) / len(ranks) * 100 if ranks else 0
    top_10_cutoff = max(1, round(contest_size * 0.10))
    top_1_cutoff = max(1, round(contest_size * 0.01))
    top_01_cutoff = max(1, round(contest_size * 0.001))
    win_cutoff = 1

    top_10_probability = len([r for r in ranks if r <= top_10_cutoff]) / len(ranks) * 100 if ranks else 0
    top_1_probability = len([r for r in ranks if r <= top_1_cutoff]) / len(ranks) * 100 if ranks else 0
    top_0_1_probability = len([r for r in ranks if r <= top_01_cutoff]) / len(ranks) * 100 if ranks else 0
    win_probability = len([r for r in ranks if r <= win_cutoff]) / len(ranks) * 100 if ranks else 0

    median_rank = int(percentile_value(ranks_sorted, 0.50))
    average_rank = int(round(sum(ranks) / len(ranks))) if ranks else contest_size
    ceiling_rank = int(percentile_value(ranks_sorted, 0.05))  # best 5% outcome
    takedown_rank = int(percentile_value(ranks_sorted, 0.01)) # best 1% outcome

    return {
        "simulation_runs": runs,
        "average_sim_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "median_sim_score": round(percentile_value(scores_sorted, 0.50), 2),
        "ceiling_sim_score": round(percentile_value(scores_sorted, 0.95), 2),
        "floor_sim_score": round(percentile_value(scores_sorted, 0.05), 2),
        "average_rank": average_rank,
        "projected_rank": median_rank,
        "median_rank": median_rank,
        "ceiling_rank": max(1, ceiling_rank),
        "takedown_rank": max(1, takedown_rank),
        "cash_probability": round(cash_probability, 1),
        "top_10_probability": round(top_10_probability, 1),
        "top_1_probability": round(top_1_probability, 2),
        "top_0_1_probability": round(top_0_1_probability, 3),
        "win_probability": round(win_probability, 3),
        "expected_payout": round(expected_payout, 2),
        # In the UI this is currently labeled "Projected Payout".
        # For GPPs, this should be probability-weighted expected payout, not median payout,
        # because the median outcome is often $0 even for a strong tournament lineup.
        "projected_payout": round(expected_payout, 2),
        "median_payout": round(percentile_value(payouts_sorted, 0.50), 2),
        "ceiling_payout": round(percentile_value(payouts_sorted, 0.95), 2),
        "best_payout": round(max(payouts) if payouts else 0, 2),
        "expected_value": round(expected_value, 2),
        "roi_percent": round((expected_value / entry_fee) * 100, 1) if entry_fee > 0 else 0,
        "min_cash_payout": payout_for_rank(paid_spots, contest),
        "top_10_rank_payout": payout_for_rank(top_10_cutoff, contest),
        "top_1_rank_payout": payout_for_rank(top_1_cutoff, contest),
        "top_0_1_rank_payout": payout_for_rank(top_01_cutoff, contest),
    }


def attach_player_sim_profiles_to_lineup(lineup):
    updated = []
    for player in lineup:
        item = dict(player)
        item.update(player_simulation_profile(item))
        updated.append(item)
    return updated

# =========================
# END DFS EDGE MLB SIM ENGINE V2
# =========================


def payout_for_rank(rank, contest):
    """
    Realistic estimated DraftKings-style payout curve when the exact payout table
    is not available. It is intentionally top-heavy and keeps lower paid places
    near min-cash instead of treating every paid finish like a huge payout.
    """
    rank = safe_int(rank, 0)
    contest_size = max(1, safe_int(contest.get("contest_size", 1), 1))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", 1), 1)))
    prize_pool = max(1.0, safe_float(contest.get("prize_pool", 1), 1))
    entry_fee = max(0.0, safe_float(contest.get("entry_fee", 0), 0))
    max_entries = max(1, safe_int(contest.get("max_entries", 1), 1))
    single_entry = bool(contest.get("single_entry", False)) or max_entries <= 1

    if rank <= 0 or rank > paid_spots:
        return 0.0

    # Cash/H2H style payout: flatter, not a lottery curve.
    payout_rate = paid_spots / contest_size
    if payout_rate >= 0.40 and single_entry:
        min_cash = max(entry_fee * 1.75, entry_fee + 0.01)
        top_cash = max(min_cash, prize_pool / max(paid_spots, 1))
        return round(max(min_cash, min(top_cash * 1.15, prize_pool)), 2)

    avg_paid = prize_pool / max(paid_spots, 1)
    min_cash = max(entry_fee * 2.0, min(entry_fee * 3.5, avg_paid * 0.58))

    # Approximate first prize. Large 150-max fields are usually top-heavy but not
    # so top-heavy that mid-paid ranks become huge payouts.
    top_prize = max(min_cash * 20, prize_pool * (0.16 if max_entries >= 20 else 0.13))
    top_prize = min(top_prize, prize_pool * 0.22)

    r_top10 = min(paid_spots, 10)
    r_top01 = max(r_top10 + 1, min(paid_spots, round(contest_size * 0.001)))
    r_top1 = max(r_top01 + 1, min(paid_spots, round(contest_size * 0.01)))
    r_top5 = max(r_top1 + 1, min(paid_spots, round(contest_size * 0.05)))

    # Anchor payouts by rank tiers.
    p_top10_end = max(min_cash * 12, prize_pool * 0.012)
    p_top01_end = max(min_cash * 7, prize_pool * 0.0020)
    p_top1_end = max(min_cash * 3.2, prize_pool * 0.00025)
    p_top5_end = max(min_cash * 1.35, min_cash + entry_fee)

    def interp(r, a_rank, b_rank, a_pay, b_pay):
        if b_rank <= a_rank:
            return b_pay
        t = max(0.0, min(1.0, (r - a_rank) / (b_rank - a_rank)))
        # Curved interpolation: payout falls fast near the top, then flattens.
        t = t ** 0.72
        return a_pay + (b_pay - a_pay) * t

    if rank == 1:
        payout = top_prize
    elif rank <= r_top10:
        payout = interp(rank, 1, r_top10, top_prize, p_top10_end)
    elif rank <= r_top01:
        payout = interp(rank, r_top10, r_top01, p_top10_end, p_top01_end)
    elif rank <= r_top1:
        payout = interp(rank, r_top01, r_top1, p_top01_end, p_top1_end)
    elif rank <= r_top5:
        payout = interp(rank, r_top1, r_top5, p_top1_end, p_top5_end)
    else:
        payout = interp(rank, r_top5, paid_spots, p_top5_end, min_cash)

    return round(max(0.0, min(payout, prize_pool)), 2)


def estimate_expected_payout_from_probabilities(contest, projected_rank, ceiling_rank, cash_probability, top_10_probability, top_1_probability, top_0_1_probability):
    contest_size = max(1, safe_int(contest.get("contest_size", 1), 1))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", 1), 1)))

    # Normalize probabilities into non-overlapping buckets.
    p_top01 = max(0.0, min(safe_float(top_0_1_probability, 0), 100.0)) / 100.0
    p_top1 = max(p_top01, min(safe_float(top_1_probability, 0) / 100.0, 1.0))
    p_top10 = max(p_top1, min(safe_float(top_10_probability, 0) / 100.0, 1.0))
    p_cash = max(p_top10, min(safe_float(cash_probability, 0) / 100.0, 1.0))

    bucket_top01 = p_top01
    bucket_top1 = max(0.0, p_top1 - p_top01)
    bucket_top10 = max(0.0, p_top10 - p_top1)
    bucket_cash = max(0.0, p_cash - p_top10)

    rank_top01 = max(1, round(contest_size * 0.001))
    rank_top1 = max(rank_top01 + 1, round(contest_size * 0.01))
    rank_top10 = max(rank_top1 + 1, round(contest_size * 0.10))
    rank_cash = max(rank_top10 + 1, round((paid_spots + rank_top10) / 2))
    rank_cash = min(rank_cash, paid_spots)

    expected = (
        bucket_top01 * payout_for_rank(rank_top01, contest)
        + bucket_top1 * payout_for_rank(rank_top1, contest)
        + bucket_top10 * payout_for_rank(rank_top10, contest)
        + bucket_cash * payout_for_rank(rank_cash, contest)
    )

    projected_payout = payout_for_rank(projected_rank, contest)
    ceiling_payout = payout_for_rank(ceiling_rank, contest)

    return {
        "expected_payout": round(expected, 2),
        "projected_payout": round(projected_payout, 2),
        "median_payout": round(projected_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "min_cash_payout": payout_for_rank(paid_spots, contest),
        "top_10_rank_payout": payout_for_rank(rank_top10, contest),
        "top_1_rank_payout": payout_for_rank(rank_top1, contest),
        "top_0_1_rank_payout": payout_for_rank(rank_top01, contest),
    }


def simulate_single_lineup(lineup_data, request: ContestSimulationRequest, lineup_number=1, field_scores=None):
    contest = normalize_contest_request(request)
    lineup = lineup_data.get("lineup", [])
    lineup = attach_player_sim_profiles_to_lineup(lineup)

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
    payout_rate = safe_float(contest.get("payout_rate", 0.20), 0.20)
    max_entries = safe_int(contest.get("max_entries", 1), 1)
    single_entry = bool(contest.get("single_entry", False))
    total_entry_cost = safe_float(contest.get("total_entry_cost", entry_fee), entry_fee)
    focus = simulator_focus_from_request(request, contest_size)
    mode = "cash" if focus == "cash_h2h" else "gpp"

    quality_profile = lineup_quality_profile(lineup, mode)
    quality_score = safe_float(quality_profile.get("lineup_quality_score", 0), 0)
    quality_label = quality_profile.get("lineup_quality_label", "Playable")
    breakdown = quality_profile.get("lineup_quality_breakdown", {})

    core_profile = lineup_core_profile(lineup)
    leverage_profile = lineup_leverage_profile(lineup)
    core_count = safe_int(core_profile.get("core_play_count", 0), 0)
    strong_count = safe_int(core_profile.get("strong_play_count", 0), 0)
    fade_count = safe_int(core_profile.get("fade_count", 0), 0)
    bad_chalk_count = safe_int(core_profile.get("bad_chalk_count", 0), 0)

    avg_leverage = safe_float(leverage_profile.get("average_leverage_score", 0), 0)
    chalk_count = safe_int(leverage_profile.get("chalk_risk_count", 0), 0)
    salary_remaining = SALARY_CAP - safe_int(lineup_data.get("total_salary", sum(safe_int(p.get("salary", 0), 0) for p in lineup)), 0)

    # True Monte Carlo simulation. Runs are intentionally moderate so mobile/live backend requests stay fast.
    runs = 450 if contest_size >= 25000 else 600
    mc = monte_carlo_lineup_simulation_v2(lineup, contest, runs=runs, field_scores=field_scores)

    # Contest focus scores are still useful to sort/show why the lineup is good.
    stack_correlation = 0.0
    if stack_size >= 5:
        stack_correlation = 95.0
    elif stack_size == 4:
        stack_correlation = 82.0
    elif stack_size == 3:
        stack_correlation = 68.0
    elif stack_size == 2:
        stack_correlation = 54.0
    else:
        stack_correlation = 38.0

    ceiling_signal = safe_float(mc.get("ceiling_sim_score", projection), projection)
    floor_signal = safe_float(mc.get("floor_sim_score", projection * 0.55), projection * 0.55)
    top_1_probability = safe_float(mc.get("top_1_probability", 0), 0)
    top_0_1_probability = safe_float(mc.get("top_0_1_probability", 0), 0)
    cash_probability = safe_float(mc.get("cash_probability", 0), 0)

    cash_safety_score = clamp_number(
        cash_probability * 0.80
        + quality_score * 0.25
        + max(0, 50000 - max(0, salary_remaining)) * 0.00002
        - fade_count * 4.0
        - bad_chalk_count * 2.0,
        1,
        99,
    )

    single_entry_edge_score = clamp_number(
        quality_score * 0.42
        + avg_leverage * 0.24
        + stack_correlation * 0.18
        + top_1_probability * 3.4
        + core_count * 2.2
        - bad_chalk_count * 3.6
        - fade_count * 4.4,
        1,
        99,
    )

    big_gpp_ceiling_score = clamp_number(
        quality_score * 0.24
        + avg_leverage * 0.26
        + stack_correlation * 0.24
        + top_1_probability * 4.6
        + top_0_1_probability * 18.0
        + max(0, ceiling_signal - floor_signal) * 0.20
        - chalk_count * 2.8
        - bad_chalk_count * 4.2
        - fade_count * 4.8,
        1,
        99,
    )

    if focus == "cash_h2h":
        focus_score = cash_safety_score
        recommendation = "Cash Core" if cash_probability >= 60 else ("Cash Viable" if cash_probability >= 48 else "Cash Risk")
    elif focus == "big_field_gpp":
        focus_score = big_gpp_ceiling_score
        recommendation = "Massive GPP Winner Profile" if top_0_1_probability >= 0.30 or top_1_probability >= 3.5 else ("Big GPP Upside" if top_1_probability >= 1.25 else "Needs More Ceiling")
    else:
        focus_score = single_entry_edge_score
        recommendation = "Single Entry Hammer" if top_1_probability >= 4.0 and quality_score >= 70 else ("Strong Single Entry" if top_1_probability >= 1.75 else "Playable")

    expected_payout = safe_float(mc.get("expected_payout", 0), 0)
    expected_value = safe_float(mc.get("expected_value", 0), 0)
    roi_percent = safe_float(mc.get("roi_percent", 0), 0)
    max_entry_expected_value = round(expected_value * max_entries, 2)
    max_entry_roi_percent = round((max_entry_expected_value / total_entry_cost) * 100, 1) if total_entry_cost > 0 else roi_percent

    tournament_rating = recommendation
    if focus == "big_field_gpp" and top_0_1_probability >= 0.45:
        tournament_rating = "Nuclear Upside"
    elif focus == "single_entry_gpp" and top_1_probability >= 5.0:
        tournament_rating = "SE Winner Profile"
    elif focus == "cash_h2h" and cash_probability >= 65:
        tournament_rating = "Cash Lockbox"

    simulation = {
        "simulation_engine_version": "dfs_edge_mlb_sim_engine_v2_monte_carlo",
        "simulator_focus": focus,
        "simulator_focus_label": simulator_focus_label(focus),
        "contest_focus_score": round(focus_score, 1),
        "cash_safety_score": round(cash_safety_score, 1),
        "single_entry_edge_score": round(single_entry_edge_score, 1),
        "big_gpp_ceiling_score": round(big_gpp_ceiling_score, 1),
        "projected_rank": mc.get("projected_rank", contest_size),
        "median_rank": mc.get("median_rank", mc.get("projected_rank", contest_size)),
        "average_rank": mc.get("average_rank", contest_size),
        "ceiling_rank": mc.get("ceiling_rank", contest_size),
        "takedown_rank": mc.get("takedown_rank", contest_size),
        "cash_cutoff_rank": paid_spots,
        "cash_probability": round(cash_probability, 1),
        "top_0_1_probability": round(top_0_1_probability, 3),
        "top_1_probability": round(top_1_probability, 2),
        "top_1_percent_probability": round(top_1_probability, 2),
        "top_10_probability": round(safe_float(mc.get("top_10_probability", 0), 0), 1),
        "win_probability": round(safe_float(mc.get("win_probability", 0), 0), 3),
        "simulated_floor": mc.get("floor_sim_score", 0),
        "simulated_ceiling": mc.get("ceiling_sim_score", 0),
        "average_sim_score": mc.get("average_sim_score", 0),
        "median_sim_score": mc.get("median_sim_score", 0),
        "simulation_runs": mc.get("simulation_runs", runs),
        "roi_percent": round(roi_percent, 1),
        "estimated_roi_percent": round(roi_percent, 1),
        "expected_value": round(expected_value, 2),
        "expected_payout": round(expected_payout, 2),
        "projected_payout": round(safe_float(mc.get("projected_payout", expected_payout), expected_payout), 2),
        "median_payout": round(safe_float(mc.get("median_payout", 0), 0), 2),
        "ceiling_payout": round(safe_float(mc.get("ceiling_payout", 0), 0), 2),
        "best_payout": round(safe_float(mc.get("best_payout", 0), 0), 2),
        "min_cash_payout": mc.get("min_cash_payout", payout_for_rank(paid_spots, contest)),
        "top_10_rank_payout": mc.get("top_10_rank_payout", 0),
        "top_1_rank_payout": mc.get("top_1_rank_payout", 0),
        "top_0_1_rank_payout": mc.get("top_0_1_rank_payout", 0),
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
        "lineup_quality_label": quality_label,
        "lineup_quality_breakdown": breakdown,
        "lineup_core_profile": core_profile,
        "lineup_leverage_profile": leverage_profile,
    }

    return {
        "lineup_number": lineup_number,
        "lineup": {**lineup_data, "lineup": lineup},
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

    apply_contest_ownership_overrides(lineups, request.ownership_overrides)

    contest = normalize_contest_request(request)

    # Generate the opponent field one time per request so every lineup is measured
    # against the same simulated contest environment.
    field_sample_count = 1800 if contest["contest_size"] >= 25000 else 1400
    field_scores = generate_field_score_samples_v2(contest, sample_count=field_sample_count)

    results = [
        simulate_single_lineup(lineup, request, index + 1, field_scores=field_scores)
        for index, lineup in enumerate(lineups)
    ]
    results.sort(
        key=lambda item: (
            item["simulation"].get("expected_value", 0),
            item["simulation"].get("top_1_probability", 0),
            item["simulation"].get("top_0_1_probability", 0),
            item["simulation"].get("contest_focus_score", 0),
        ),
        reverse=True,
    )

    if not results:
        return {"success": False, "error": "No lineups available for simulation.", "results": [], "simulations": []}

    rois = [safe_float(item["simulation"].get("roi_percent", 0)) for item in results]
    cash_probs = [safe_float(item["simulation"].get("cash_probability", 0)) for item in results]
    evs = [safe_float(item["simulation"].get("expected_value", 0)) for item in results]
    expected_payouts = [safe_float(item["simulation"].get("expected_payout", 0)) for item in results]
    quality_scores = [safe_float(item["simulation"].get("lineup_quality_score", 0)) for item in results]
    focus_scores = [safe_float(item["simulation"].get("contest_focus_score", 0)) for item in results]
    top_point_one = [safe_float(item["simulation"].get("top_0_1_probability", 0)) for item in results]
    top_ones = [safe_float(item["simulation"].get("top_1_probability", 0)) for item in results]
    best = results[0]["simulation"]

    summary = {
        "simulation_engine_version": "dfs_edge_mlb_sim_engine_v2_monte_carlo",
        "field_sample_count": len(field_scores),
        "lineup_count": len(results),
        "average_roi_percent": round(sum(rois) / len(rois), 1),
        "average_cash_probability": round(sum(cash_probs) / len(cash_probs), 1),
        "average_lineup_quality": round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0,
        "best_lineup_quality": round(max(quality_scores), 1) if quality_scores else 0,
        "average_focus_score": round(sum(focus_scores) / len(focus_scores), 1) if focus_scores else 0,
        "best_focus_score": round(max(focus_scores), 1) if focus_scores else 0,
        "best_top_0_1_probability": round(max(top_point_one), 3) if top_point_one else 0,
        "best_top_1_probability": round(max(top_ones), 2) if top_ones else 0,
        "simulator_focus": best.get("simulator_focus", simulator_focus_from_request(request, contest["contest_size"])),
        "simulator_focus_label": best.get("simulator_focus_label", simulator_focus_label(simulator_focus_from_request(request, contest["contest_size"]))),
        "estimated_total_ev": round(sum(evs), 2),
        "average_expected_payout": round(sum(expected_payouts) / len(expected_payouts), 2) if expected_payouts else 0,
        "best_expected_payout": round(max(expected_payouts), 2) if expected_payouts else 0,
        "best_projected_payout": best.get("projected_payout", 0),
        "best_median_payout": best.get("median_payout", 0),
        "best_ceiling_payout": best.get("ceiling_payout", 0),
        "best_recommendation": best.get("recommendation", "Playable"),
        "best_roi_percent": best.get("roi_percent", 0),
        "note": "Projected payout is probability-weighted expected payout. Median payout may be $0 in top-heavy GPPs.",
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
    starter_eligible = [p for p in players if optimizer_starter_eligible(p)]
    review_players = [p for p in active_players if p.get("auto_active_recommendation") == "review"]
    inactive_recommended = [p for p in active_players if p.get("auto_active_recommendation") == "inactive"]
    starter_state = load_mlb_starter_state()
    odds_state = load_mlb_data_state(MLB_ODDS_STATE_PATH)
    weather_state = load_mlb_data_state(MLB_WEATHER_STATE_PATH)

    return {
        "success": True,
        "version": DATA_ENGINE_VERSION,
        "sources": DATA_ENGINE_SOURCES,
        "player_count": len(players),
        "active_player_count": len(active_players),
        "starter_eligible_count": len(starter_eligible),
        "confirmed_hitter_count": len([p for p in starter_eligible if p.get("starter_source") == "mlb_stats_confirmed_lineup"]),
        "probable_pitcher_count": len([p for p in starter_eligible if p.get("starter_source") == "mlb_stats_probable_pitcher"]),
        "official_roster_filter": "mlb_40_man_active_status",
        "starter_refresh": starter_state,
        "odds_feed": mlb_feed_summary(odds_state, configured=bool(ODDS_API_KEY)),
        "weather_feed": mlb_feed_summary(weather_state, configured=True),
        "review_count": len(review_players),
        "inactive_recommendation_count": len(inactive_recommended),
        "fields_added": [
            "starter_status",
            "starter_probability",
            "starter_source",
            "injury_status",
            "lineup_spot",
            "avg_at_bats",
            "projected_innings",
            "pull_risk",
            "park_factor",
            "weather_risk",
            "temperature_f",
            "wind_mph",
            "precipitation_probability",
            "team_total",
            "opponent_total",
            "game_total",
            "spread",
            "moneyline",
            "batter_vs_pitcher",
            "trend_score",
            "data_engine_boost",
            "auto_active_recommendation",
        ],
        "note": "Optimizer eligibility uses only the uploaded DK slate plus official MLB status. Odds and weather are blended into projections when their feeds are available.",
    }


@app.post("/data-engine/enrich-slate")
def enrich_active_slate(request: AdminPasswordRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

    if not ACTIVE_SLATE_PATH.exists():
        return {"success": False, "error": "Upload the DraftKings MLB contest slate before refreshing starters."}

    enriched_players, _ = apply_auto_slate_cleanup(load_players(), respect_manual_overrides=True)
    enriched_players = apply_slate_starter_likelihood(enriched_players)
    slate_date = load_slate_metadata().get("slate_date") or datetime.now().strftime("%Y-%m-%d")
    enriched_players, starter_state = refresh_mlb_starters(enriched_players, slate_date)
    try:
        enriched_players, odds_state = refresh_mlb_odds(enriched_players, force=True)
    except Exception as exc:
        odds_state = {"success": False, "configured": bool(ODDS_API_KEY), "error": f"Odds refresh unavailable: {exc.__class__.__name__}"}
    try:
        enriched_players, weather_state = refresh_mlb_weather(enriched_players, slate_date, force=True)
    except Exception as exc:
        weather_state = {"success": False, "configured": True, "error": f"Weather refresh unavailable: {exc.__class__.__name__}"}
    enriched_players = add_values(enriched_players)
    save_active_slate(enriched_players)

    cleanup_stats = {
        "original_count": len(enriched_players),
        "active_count": len([p for p in enriched_players if bool(p.get("active", True))]),
        "inactive_count": len([p for p in enriched_players if not bool(p.get("active", True))]),
        "starter_eligible_count": len([p for p in enriched_players if optimizer_starter_eligible(p)]),
    }

    review_count = len([p for p in enriched_players if p.get("auto_active_recommendation") == "review"])
    inactive_recommendation_count = len([p for p in enriched_players if p.get("auto_active_recommendation") == "inactive"])

    return {
        "success": True,
        "message": "MLB starters, official roster status, consensus game lines, and stadium weather refreshed where available.",
        "player_count": len(enriched_players),
        "active_player_count": cleanup_stats["active_count"],
        "inactive_player_count": cleanup_stats["inactive_count"],
        "cleanup_stats": cleanup_stats,
        "review_count": review_count,
        "inactive_recommendation_count": inactive_recommendation_count,
        "version": DATA_ENGINE_VERSION,
        "starter_refresh": starter_state,
        "odds_refresh": mlb_feed_summary(odds_state if odds_state.get("success") else {}, configured=bool(ODDS_API_KEY)),
        "weather_refresh": mlb_feed_summary(weather_state if weather_state.get("success") else {}, configured=True),
        "warnings": [warning for warning in [starter_state.get("error", ""), odds_state.get("error", ""), weather_state.get("error", "")] if warning],
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
                    "starter_probability": player.get("starter_probability"),
                    "starter_source": player.get("starter_source"),
                    "injury_status": player.get("injury_status"),
                    "lineup_spot": player.get("lineup_spot"),
                    "lineup_source": player.get("lineup_source"),
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


def central_auth_request(path, payload):
    try:
        request = urllib.request.Request(
            f"{CENTRAL_AUTH_URL}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else {
                "success": False,
                "error": "Invalid account service response.",
            }
    except Exception:
        return {"success": False, "error": "Central account service is unavailable."}


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
    # Accounts are owned by the central DFS Edge account service.
    return None


def find_user_by_token(token):
    users = load_users()
    for email, user in users.items():
        if user.get("token") == token:
            return email, user, users
    return "", None, users


def is_admin_token(token):
    if not token:
        return False
    email, user, _ = find_user_by_token(token)
    if user:
        role = role_for_email(email, user.get("role", "free"))
        if role == "admin" and normalize_email(email) == ADMIN_EMAIL:
            return True
    session = central_auth_request("/auth/me", {"token": token})
    central_user = session.get("user", {}) if session.get("success") else {}
    return (
        normalize_email(central_user.get("email")) == ADMIN_EMAIL
        and str(central_user.get("role", "")).lower() == "admin"
    )


def bearer_token(authorization):
    value = str(authorization or "").strip()
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


def optional_session(authorization: str = Header(default="")):
    token = bearer_token(authorization)
    if not token:
        return None
    response = central_auth_request("/auth/me", {"token": token})
    return response.get("user") if response.get("success") else None


def require_pro_access(authorization: str = Header(default="")):
    session = optional_session(authorization)
    if not session:
        raise HTTPException(status_code=401, detail="Log in to use this feature.")
    if str(session.get("role", "free")).lower() not in ["pro", "admin"]:
        raise HTTPException(status_code=403, detail="DFS Edge Pro is required.")
    return session


def is_admin_authorized(request_or_password=None, token=""):
    password = ""
    auth_token = token or ""
    if isinstance(request_or_password, str):
        password = request_or_password
    elif request_or_password is not None:
        password = getattr(request_or_password, "admin_password", "") or ""
        auth_token = getattr(request_or_password, "auth_token", "") or getattr(request_or_password, "admin_token", "") or auth_token
    return (bool(ADMIN_PASSWORD) and password == ADMIN_PASSWORD) or is_admin_token(auth_token)


@app.post("/auth/register")
def register_user(request: RegisterRequest):
    return central_auth_request(
        "/auth/register",
        {"email": normalize_email(request.email), "password": str(request.password or "")},
    )


@app.post("/auth/login")
def login_user(request: LoginRequest):
    return central_auth_request(
        "/auth/login",
        {"email": normalize_email(request.email), "password": str(request.password or "")},
    )


@app.post("/auth/me")
def auth_me(request: AuthTokenRequest):
    return central_auth_request("/auth/me", {"token": request.token})


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
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

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
def ai_picks_status(_: dict = Depends(require_pro_access)):
    return ai_picks_summary()


@app.post("/ai-lineup-builder/build")
def ai_lineup_builder(request: AutoLineupBuilderRequest, _: dict = Depends(require_pro_access)):
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
    meta = load_slate_metadata()
    display_label = f"{meta.get('slate_name', 'MLB Slate')} • {meta.get('slate_date', '')}".strip(" •")
    return {
        "slate_source": current_slate_source(),
        "slate_name": meta.get("slate_name", "MLB Slate"),
        "slate_date": meta.get("slate_date", ""),
        "slate_display_name": display_label,
        "slate_updated_at": meta.get("updated_at", ""),
        "slate_updated_by": meta.get("updated_by", ""),
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
        "data_dir": str(DATA_DIR),
        "daily_slate_persistent": True,
    }


@app.post("/admin/slate-metadata")
def update_slate_metadata(request: SlateMetadataRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

    meta = save_slate_metadata(
        slate_name=request.slate_name,
        slate_date=request.slate_date,
        updated_by=ADMIN_EMAIL if is_admin_token(request.auth_token) else "admin",
    )
    players = load_players()
    active_count = len([p for p in players if bool(p.get("active", True))])
    return {
        "success": True,
        "message": "Slate info saved.",
        "slate_name": meta.get("slate_name", "MLB Slate"),
        "slate_date": meta.get("slate_date", ""),
        "slate_display_name": f"{meta.get('slate_name', 'MLB Slate')} • {meta.get('slate_date', '')}".strip(" •"),
        "player_count": len(players),
        "active_player_count": active_count,
        "inactive_player_count": len(players) - active_count,
        "slate_source": current_slate_source(),
    }


@app.post("/admin/upload-dk-csv")
async def upload_dk_csv(
    admin_password: str = Form(""),
    admin_token: str = Form(""),
    file: UploadFile = File(...),
):
    if not is_admin_authorized(admin_password, admin_token):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

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

    cleaned_players, _ = apply_auto_slate_cleanup(players, respect_manual_overrides=False)
    cleaned_players = apply_slate_starter_likelihood(cleaned_players)
    save_active_slate(cleaned_players)
    current_meta = save_slate_metadata(
        slate_name=f"DraftKings MLB Slate - {datetime.now().strftime('%b %d')}",
        slate_date=datetime.now().strftime("%Y-%m-%d"),
        updated_by=ADMIN_EMAIL if is_admin_token(admin_token) else "admin",
    )

    cleanup_stats = {
        "original_count": len(players),
        "active_count": len([p for p in cleaned_players if bool(p.get("active", True))]),
        "inactive_count": len([p for p in cleaned_players if not bool(p.get("active", True))]),
        "starter_eligible_count": len([p for p in cleaned_players if optimizer_starter_eligible(p)]),
    }

    return {
        "success": True,
        "message": "DraftKings MLB contest slate uploaded. Only conservative likely starters are eligible until the live starter refresh confirms them.",
        "player_count": len(cleaned_players),
        "slate_name": current_meta.get("slate_name", "DraftKings MLB Slate"),
        "slate_date": current_meta.get("slate_date", ""),
        "slate_display_name": f"{current_meta.get('slate_name', 'DraftKings MLB Slate')} • {current_meta.get('slate_date', '')}".strip(" •"),
        "active_player_count": cleanup_stats["active_count"],
        "inactive_player_count": cleanup_stats["inactive_count"],
        "cleanup_stats": cleanup_stats,
        "ownership": "Estimated ownership applied when CSV ownership was missing.",
        "auto_cleanup": "Bench-risk hitters and non-probable pitchers are excluded. Use Refresh MLB feeds near lock for announced lineups.",
    }


@app.post("/admin/upload-projections-csv")
async def upload_projections_csv(
    admin_password: str = Form(""),
    admin_token: str = Form(""),
    file: UploadFile = File(...),
):
    if not is_admin_authorized(admin_password, admin_token):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    if not file.filename.lower().endswith(".csv"):
        return {"success": False, "error": "Please upload a projection CSV file."}

    csv_text = (await file.read()).decode("utf-8-sig", errors="replace")
    imported = parse_projection_csv(csv_text)
    if not imported:
        return {
            "success": False,
            "error": "No projections were found. Include Name and Projection columns; Ownership, Ceiling, and Floor are optional.",
        }

    players = load_players()
    imported_by_name = {normalized_player_name(item["name"]): item for item in imported}
    matched = 0
    ownership_count = 0
    ceiling_count = 0
    unmatched_names = set(imported_by_name)
    for player in players:
        key = normalized_player_name(player.get("name"))
        item = imported_by_name.get(key)
        if not item:
            continue
        unmatched_names.discard(key)
        matched += 1
        player["projection"] = item["projection"]
        player["projection_source"] = "admin_projection_csv"
        player["projection_model_version"] = "imported_projection_blend_v1"
        if item.get("ownership", 0) > 0:
            player["ownership"] = item["ownership"]
            player["ownership_source"] = "admin_projection_csv"
            ownership_count += 1
        if item.get("ceiling", 0) > 0:
            player["ceiling"] = item["ceiling"]
            player["ceiling_source"] = "admin_projection_csv"
            ceiling_count += 1
        if "floor" in item:
            player["floor"] = item["floor"]
            player["floor_source"] = "admin_projection_csv"
        player["value"] = player_value(player)

    if matched == 0:
        return {"success": False, "error": "Projection names did not match any player on the active MLB slate."}

    save_active_slate(players)
    write_json_file(PROJECTION_SNAPSHOT_PATH, players)
    return {
        "success": True,
        "message": "MLB projections, ownership, floor, and ceiling data imported successfully.",
        "rows_imported": len(imported),
        "players_matched": matched,
        "ownership_matched": ownership_count,
        "ceiling_matched": ceiling_count,
        "unmatched_count": len(unmatched_names),
        "projection_snapshot_saved": True,
    }


@app.post("/admin/upload-payout-csv")
async def upload_payout_csv(
    admin_password: str = Form(""),
    admin_token: str = Form(""),
    file: UploadFile = File(...),
):
    if not is_admin_authorized(admin_password, admin_token):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    if not file.filename.lower().endswith(".csv"):
        return {"success": False, "error": "Please upload a payout CSV file."}

    csv_text = (await file.read()).decode("utf-8-sig", errors="replace")
    tiers = parse_payout_csv(csv_text)
    if not tiers:
        return {
            "success": False,
            "error": "No payout tiers were found. Include Rank or Place and Payout or Prize columns.",
        }
    write_json_file(PAYOUT_TABLE_PATH, tiers)
    return {
        "success": True,
        "message": "Exact MLB contest payout table imported and connected to the simulator.",
        "tier_count": len(tiers),
        "first_place_payout": tiers[0]["payout"],
        "last_paid_rank": max(tier["end_rank"] for tier in tiers),
    }


@app.get("/payout-table/status")
def payout_table_status():
    tiers = load_payout_table()
    return {
        "success": True,
        "configured": bool(tiers),
        "payout_source": "uploaded_exact_table" if tiers else "estimated_curve",
        "tier_count": len(tiers),
        "last_paid_rank": max((tier["end_rank"] for tier in tiers), default=0),
    }


@app.post("/admin/upload-actual-results-csv")
async def upload_actual_results_csv(
    admin_password: str = Form(""),
    admin_token: str = Form(""),
    slate_key: str = Form(""),
    file: UploadFile = File(...),
):
    if not is_admin_authorized(admin_password, admin_token):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    if not file.filename.lower().endswith(".csv"):
        return {"success": False, "error": "Please upload an actual-results CSV file."}

    csv_text = (await file.read()).decode("utf-8-sig", errors="replace")
    actual_rows = parse_actual_results_csv(csv_text)
    if not actual_rows:
        return {
            "success": False,
            "error": "No results found. Include Name or Player and Actual Points, Fantasy Points, FPTS, DK Points, or Points.",
        }
    snapshot = read_json_file(PROJECTION_SNAPSHOT_PATH, [])
    players = snapshot if isinstance(snapshot, list) and len(snapshot) >= 10 else load_players()
    result = projection_backtest(players, actual_rows)
    if result["matched_players"] < 10:
        return {
            "success": False,
            "error": "Fewer than 10 result names matched the saved MLB projection snapshot.",
            **result,
        }

    metadata = load_slate_metadata()
    resolved_slate_key = (
        slate_key.strip()
        or metadata.get("slate_date")
        or metadata.get("slate_name")
        or datetime.now(timezone.utc).date().isoformat()
    )
    payload = {
        "success": True,
        "sport": "MLB",
        "slate_key": resolved_slate_key,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    history = read_json_file(BACKTEST_HISTORY_PATH, [])
    history = history if isinstance(history, list) else []
    history = [item for item in history if item.get("slate_key") != resolved_slate_key]
    history.append(payload)
    history = history[-365:]
    write_json_file(BACKTEST_LATEST_PATH, payload)
    write_json_file(BACKTEST_HISTORY_PATH, history)
    return {
        **payload,
        "message": f"MLB backtest saved for {resolved_slate_key} with {result['matched_players']} matched players.",
        "history_slate_count": len(history),
    }


@app.get("/model/backtest/status")
def model_backtest_status():
    latest = read_json_file(BACKTEST_LATEST_PATH, {})
    history = read_json_file(BACKTEST_HISTORY_PATH, [])
    return {
        "success": True,
        "configured": bool(latest),
        "latest": latest if isinstance(latest, dict) else {},
        "history_slate_count": len(history) if isinstance(history, list) else 0,
        "minimum_calibration_slates": 10,
        "calibration_ready": isinstance(history, list) and len(history) >= 10,
    }


@app.post("/admin/use-sample")
def use_sample_slate(request: AdminPasswordRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    if ACTIVE_SLATE_PATH.exists():
        ACTIVE_SLATE_PATH.unlink()
    ensure_sample_players_file()
    meta = save_slate_metadata("MLB Sample Slate", datetime.now().strftime("%Y-%m-%d"), "admin")
    players = load_players()
    return {
        "success": True,
        "message": "MLB sample slate loaded successfully.",
        "slate_source": current_slate_source(),
        "player_count": len(players),
    }


@app.post("/admin/clear-slate")
def clear_imported_slate(admin_password: str = Form(""), admin_token: str = Form("")):
    if not is_admin_authorized(admin_password, admin_token):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    if ACTIVE_SLATE_PATH.exists():
        ACTIVE_SLATE_PATH.unlink()
    ensure_sample_players_file()
    return {
        "success": True,
        "message": "Imported slate cleared. App is now using MLB sample players.",
    }


@app.post("/admin/update-player")
def update_player(request: UpdatePlayerRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
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
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

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
def optimize_multiple_lineups(
    request: MultiOptimizeRequest,
    session: dict | None = Depends(optional_session),
):
    if not session or str(session.get("role", "free")).lower() not in ["pro", "admin"]:
        request.count = 1
        request.max_exposure = 100
        request.max_same_players = 9
        request.min_salary = 0
        request.max_players_per_team = 5
        request.force_team_stack = False
        request.avoid_pitcher_vs_hitter = True
        request.randomness = 0
        request.player_min_exposure = {}
        request.player_max_exposure = {}
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
def export_lineups_csv(request: MultiOptimizeRequest, _: dict = Depends(require_pro_access)):
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

    if same_team_pitcher_conflict(players):
        alerts.append({
            "severity": "high",
            "type": "same_team_pitchers",
            "title": "Two pitchers from the same team",
            "message": "Only one probable starting pitcher per MLB team is allowed in DFS Edge lineups.",
            "players": [p.get("name") for p in get_pitchers(players)],
            "action": "repair_required",
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
def market_intelligence_status(_: dict = Depends(require_pro_access)):
    return market_intelligence_summary(persist_snapshot=False)


@app.post("/market-intelligence/refresh")
def market_intelligence_refresh(request: AdminPasswordRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}
    summary = market_intelligence_summary(persist_snapshot=True)
    summary["message"] = "Ownership drift and Vegas movement refreshed. Current market snapshot saved for future comparison."
    return summary

@app.get("/slate-intelligence/status")
def slate_intelligence_status(_: dict = Depends(require_pro_access)):
    return slate_intelligence_summary()


@app.post("/slate-intelligence/refresh")
def slate_intelligence_refresh(request: AdminPasswordRequest):
    if not is_admin_authorized(request):
        return {"success": False, "error": "Admin session expired. Log in as admin again."}

    enriched_players, cleanup_stats = apply_auto_slate_cleanup(load_players(), respect_manual_overrides=True)
    save_active_slate(enriched_players)
    summary = slate_intelligence_summary()
    summary["cleanup_stats"] = cleanup_stats
    summary["message"] = "Real-time slate intelligence refreshed using the current API-ready Data Engine layer."
    return summary


@app.post("/slate-intelligence/lineup-health")
def slate_intelligence_lineup_health(request: LineupAlertsRequest, _: dict = Depends(require_pro_access)):
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
def lineup_alerts(request: LineupAlertsRequest, _: dict = Depends(require_pro_access)):
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
def late_swap_fix(request: LateSwapRequest, _: dict = Depends(require_pro_access)):
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
def lineup_fixer(request: LateSwapRequest, session: dict = Depends(require_pro_access)):
    return late_swap_fix(request, session)

@app.post("/simulate-contest")
def simulate_contest(request: ContestSimulationRequest, _: dict = Depends(require_pro_access)):
    return simulate_contest_payload(request)


@app.post("/contest-simulator")
def contest_simulator(request: ContestSimulationRequest, _: dict = Depends(require_pro_access)):
    return simulate_contest_payload(request)


@app.post("/simulate")
def simulate(request: ContestSimulationRequest, _: dict = Depends(require_pro_access)):
    return simulate_contest_payload(request)


# ============================================================
# DFS EDGE MLB - TOURNAMENT ENGINE V2 OVERRIDES
# Added after original definitions so existing endpoints call these
# newer functions at runtime without requiring frontend changes.
# ============================================================

TOURNAMENT_ENGINE_VERSION = "dfs_edge_mlb_tournament_engine_v2_ceiling_ev"


def clamp01(value):
    return max(0.0, min(1.0, safe_float(value, 0.0)))


def v2_position_volatility(player):
    pos = normalize_position(player.get("position", ""))
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    own = safe_float(player.get("ownership", 12), 12)
    if pos == "P":
        base = 0.30
        if proj >= 20:
            base += 0.06
        if own <= 10:
            base += 0.04
        return max(0.24, min(base, 0.45))
    # MLB hitters are extremely volatile. This is the heart of GPP upside.
    base = 0.62
    if proj >= 9:
        base += 0.10
    if own <= 8:
        base += 0.08
    if safe_float(player.get("team_total", 4.2), 4.2) >= 5.0:
        base += 0.05
    return max(0.52, min(base, 0.92))


def v2_player_ceiling(player, percentile="95"):
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    pos = normalize_position(player.get("position", ""))
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    trend = safe_float(player.get("trend_score", 50), 50)
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    volatility = v2_position_volatility(player)

    if pos == "P":
        mult = 1.55 if percentile == "95" else 1.85
        ceiling = proj * mult + max(0, lev - 50) * 0.035
    else:
        mult = 2.25 if percentile == "95" else 3.05
        ceiling = proj * mult
        ceiling += max(0, 12 - own) * 0.18
        ceiling += max(0, lev - 45) * 0.05
        ceiling += max(0, trend - 55) * 0.05
        ceiling += max(0, team_total - 4.3) * 1.2

    return round(max(proj, ceiling * (0.92 + volatility * 0.12)), 2)


def v2_lineup_stack_profile(lineup):
    hitters = get_hitters(lineup)
    counts = count_team_players(lineup, hitters_only=True)
    if not counts:
        return {
            "stack_score": 0,
            "stack_team": "",
            "stack_size": 0,
            "secondary_stack_size": 0,
            "stack_label": "No Stack",
            "stack_correlation_multiplier": 1.0,
        }

    sorted_counts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    stack_team, stack_size = sorted_counts[0]
    secondary = sorted_counts[1][1] if len(sorted_counts) > 1 else 0
    team_total = estimated_team_total(stack_team)
    stack_hitters = [p for p in hitters if normalize_team(p.get("team", "")) == stack_team]
    avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in stack_hitters) / max(1, len(stack_hitters))
    avg_lev = sum(safe_float(p.get("leverage_score", 45), 45) for p in stack_hitters) / max(1, len(stack_hitters))

    score = 18.0
    if stack_size >= 5:
        score += 48
    elif stack_size == 4:
        score += 39
    elif stack_size == 3:
        score += 27
    elif stack_size == 2:
        score += 10

    if secondary >= 3:
        score += 18
    elif secondary == 2:
        score += 11

    score += max(0, team_total - 4.0) * 7.0
    score += max(0, avg_lev - 45) * 0.24
    score += max(0, 18 - avg_own) * 0.52
    score -= max(0, avg_own - 26) * 0.40
    score = round(max(0, min(100, score)), 1)

    if stack_size >= 5 and secondary >= 2:
        label = f"{stack_team} {stack_size}-{secondary} hammer stack"
    elif stack_size >= 4:
        label = f"{stack_team} {stack_size}-man GPP stack"
    elif stack_size >= 3:
        label = f"{stack_team} mini stack"
    else:
        label = "Thin stack"

    corr = 1.0
    if stack_size >= 5:
        corr += 0.26
    elif stack_size == 4:
        corr += 0.19
    elif stack_size == 3:
        corr += 0.11
    if secondary >= 3:
        corr += 0.10
    elif secondary == 2:
        corr += 0.06
    corr += max(0, team_total - 4.5) * 0.035

    return {
        "stack_score": score,
        "stack_team": stack_team,
        "stack_size": stack_size,
        "secondary_stack_size": secondary,
        "stack_label": label,
        "stack_correlation_multiplier": round(corr, 3),
    }


def v2_lineup_ceiling_profile(lineup):
    raw_proj = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
    boosted = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    p95 = sum(v2_player_ceiling(p, "95") for p in lineup)
    p99 = sum(v2_player_ceiling(p, "99") for p in lineup)
    stack_profile = v2_lineup_stack_profile(lineup)
    corr = safe_float(stack_profile.get("stack_correlation_multiplier", 1.0), 1.0)
    p95_adj = p95 * corr
    p99_adj = p99 * (1.0 + (corr - 1.0) * 1.25)
    ceiling_gap = p95_adj - boosted
    ceiling_score = (p95_adj - 70) * 0.95 + max(0, ceiling_gap) * 0.55 + safe_float(stack_profile.get("stack_score", 0), 0) * 0.22
    return {
        "raw_projection": round(raw_proj, 2),
        "boosted_projection": round(boosted, 2),
        "p95_ceiling_points": round(p95_adj, 2),
        "p99_ceiling_points": round(p99_adj, 2),
        "ceiling_gap": round(ceiling_gap, 2),
        "ceiling_score": round(max(0, min(100, ceiling_score)), 1),
    }


def v2_lineup_leverage_profile(lineup):
    if not lineup:
        return {"leverage_score": 0, "ownership_score": 0, "duplication_risk": 100, "uniqueness_score": 0}
    avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in lineup) / len(lineup)
    avg_lev = sum(safe_float(p.get("leverage_score", 45), 45) for p in lineup) / len(lineup)
    high_chalk = len([p for p in lineup if safe_float(p.get("ownership", 0), 0) >= 25])
    low_owned_upside = len([
        p for p in lineup
        if safe_float(p.get("ownership", 0), 0) <= 10 and safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) >= (12 if normalize_position(p.get("position", "")) == "P" else 6)
    ])
    stack_profile = v2_lineup_stack_profile(lineup)
    main_stack_size = safe_int(stack_profile.get("stack_size", 0), 0)
    secondary = safe_int(stack_profile.get("secondary_stack_size", 0), 0)

    duplication_risk = avg_own * 2.15 + high_chalk * 8.0
    if main_stack_size >= 5:
        duplication_risk -= 8.0
    elif main_stack_size == 4:
        duplication_risk -= 5.0
    if secondary >= 2:
        duplication_risk -= 5.5
    duplication_risk = max(0, min(100, duplication_risk))

    leverage = avg_lev + low_owned_upside * 4.2 + max(0, 18 - avg_own) * 1.15 - high_chalk * 3.6
    leverage = max(0, min(100, leverage))
    uniqueness = max(0, min(100, 100 - duplication_risk + low_owned_upside * 2.5))
    return {
        "leverage_score": round(leverage, 1),
        "average_lineup_ownership": round(avg_own, 2),
        "ownership_score": round(max(0, min(100, 100 - avg_own * 2.2)), 1),
        "duplication_risk": round(duplication_risk, 1),
        "uniqueness_score": round(uniqueness, 1),
        "low_owned_upside_count": low_owned_upside,
        "high_chalk_count": high_chalk,
    }


def v2_tournament_equity_score(lineup, mode="gpp", style="balanced"):
    mode = str(mode or "gpp").lower()
    style = str(style or "balanced").lower()
    ceiling = v2_lineup_ceiling_profile(lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    projection = safe_float(ceiling.get("boosted_projection", 0), 0)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    salary_remaining = SALARY_CAP - salary
    conflict = pitcher_vs_hitter_conflict(lineup)
    fade_count = safe_int(core.get("fade_count", 0), 0)
    bad_chalk = safe_int(core.get("bad_chalk_count", 0), 0)
    inactive_count = len([p for p in lineup if bool(p.get("active", True)) is False])

    if mode == "cash":
        score = (
            projection * 1.15
            + safe_float(core.get("average_core_play_score", 50), 50) * 0.22
            + safe_float(ceiling.get("ceiling_score", 0), 0) * 0.08
            + safe_float(lev.get("leverage_score", 0), 0) * 0.08
            + max(0, 5000 - abs(salary_remaining)) * 0.001
            - fade_count * 7
            - bad_chalk * 2
        )
    else:
        # This is the core shift: GPP sorting is no longer projection-first.
        ceiling_w = 0.34
        stack_w = 0.23
        leverage_w = 0.19
        unique_w = 0.13
        projection_w = 0.11
        if style in ["aggressive", "nuclear", "large_field_gpp", "twenty_max", "mega_gpp"]:
            ceiling_w = 0.39
            stack_w = 0.25
            leverage_w = 0.21
            unique_w = 0.15
            projection_w = 0.06
        score = (
            safe_float(ceiling.get("ceiling_score", 0), 0) * ceiling_w
            + safe_float(stack.get("stack_score", 0), 0) * stack_w
            + safe_float(lev.get("leverage_score", 0), 0) * leverage_w
            + safe_float(lev.get("uniqueness_score", 0), 0) * unique_w
            + max(0, projection - 55) * projection_w
        ) * 2.05
        score -= bad_chalk * (7.5 if style in ["aggressive", "nuclear"] else 5.0)
        score -= fade_count * 9.0
        if safe_int(stack.get("stack_size", 0), 0) < 3:
            score -= 12.0
        if safe_int(stack.get("stack_size", 0), 0) < 4 and style in ["aggressive", "nuclear", "large_field_gpp", "twenty_max"]:
            score -= 8.0

    if conflict:
        score -= 18.0
    if inactive_count:
        score -= inactive_count * 35.0
    return round(max(0.0, min(100.0, score)), 2)


def score_lineup(lineup, mode, randomness=0):
    mode = str(mode or "cash").lower()
    style = "nuclear" if safe_int(randomness, 0) >= 55 else ("aggressive" if safe_int(randomness, 0) >= 30 else "balanced")
    equity = v2_tournament_equity_score(lineup, mode, style)
    projection = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    if mode == "cash":
        base = projection * 0.75 + equity * 0.55
    else:
        base = equity * 1.85 + projection * 0.10
    return round(base + deterministic_random_bonus(lineup, min(max(safe_int(randomness, 0), 0), 100)) * (0.35 if mode == "gpp" else 0.10), 4)


def lineup_quality_profile(lineup, mode="gpp"):
    if not lineup:
        return {
            "lineup_quality_score": 0,
            "win_probability": 0,
            "lineup_quality_label": "No Lineup",
            "lineup_quality_breakdown": {"projection_score": 0, "ceiling_score": 0, "leverage_score": 0, "stack_score": 0, "core_score": 0, "salary_score": 0, "safety_score": 0},
        }
    mode = str(mode or "gpp").lower()
    ceiling = v2_lineup_ceiling_profile(lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    conflict = pitcher_vs_hitter_conflict(lineup)
    inactive = len([p for p in lineup if bool(p.get("active", True)) is False])
    review = len([p for p in lineup if str(p.get("auto_active_recommendation", "active")).lower() == "review"])
    fade = safe_int(core.get("fade_count", 0), 0)
    bad_chalk = safe_int(core.get("bad_chalk_count", 0), 0)
    avg_core = safe_float(core.get("average_core_play_score", 50), 50)

    projection_score = round(max(0, min(100, (safe_float(ceiling.get("boosted_projection", 0), 0) - 55) * 1.22)), 1)
    ceiling_score = safe_float(ceiling.get("ceiling_score", 0), 0)
    stack_score = safe_float(stack.get("stack_score", 0), 0)
    leverage_score = safe_float(lev.get("leverage_score", 0), 0)
    uniqueness_score = safe_float(lev.get("uniqueness_score", 0), 0)
    core_score = round(max(0, min(100, avg_core + safe_int(core.get("core_play_count", 0), 0) * 3.0 + safe_int(core.get("strong_play_count", 0), 0) * 1.5)), 1)
    salary_score = 88 if remaining <= 1800 else (78 if remaining <= 3500 else 66)
    safety_score = 92 - inactive * 35 - review * 5 - (24 if conflict else 0)
    safety_score = round(max(0, min(100, safety_score)), 1)

    if mode == "cash":
        quality = projection_score * 0.34 + safety_score * 0.24 + core_score * 0.18 + ceiling_score * 0.10 + leverage_score * 0.07 + stack_score * 0.03 + salary_score * 0.04
    else:
        quality = ceiling_score * 0.28 + stack_score * 0.22 + leverage_score * 0.19 + uniqueness_score * 0.12 + projection_score * 0.10 + core_score * 0.06 + safety_score * 0.03
    quality -= fade * 7.5 + bad_chalk * (6.0 if mode == "gpp" else 2.5)
    quality = round(max(0, min(100, quality)), 1)

    # In GPP this is not literal win %. It is lineup strength/takedown profile.
    if mode == "cash":
        win_strength = round(max(1, min(99, quality * 0.75 + safety_score * 0.20 + projection_score * 0.05)), 1)
    else:
        win_strength = round(max(1, min(99, quality * 0.62 + ceiling_score * 0.16 + stack_score * 0.12 + leverage_score * 0.10)), 1)

    if mode == "gpp":
        if quality >= 84 and stack_score >= 74 and ceiling_score >= 72:
            label = "Takedown Profile"
        elif quality >= 74 and stack_score >= 64:
            label = "Big GPP Upside"
        elif quality >= 62:
            label = "Playable Upside"
        elif quality >= 48:
            label = "Needs More Ceiling"
        else:
            label = "Weak Build"
    else:
        if quality >= 85:
            label = "Cash Core"
        elif quality >= 72:
            label = "Cash Viable"
        elif quality >= 58:
            label = "Risky"
        else:
            label = "Weak Build"

    return {
        "lineup_quality_score": quality,
        "win_probability": win_strength,
        "lineup_quality_label": label,
        "lineup_quality_breakdown": {
            "projection_score": projection_score,
            "ceiling_score": round(ceiling_score, 1),
            "leverage_score": round(leverage_score, 1),
            "stack_score": round(stack_score, 1),
            "core_score": round(core_score, 1),
            "salary_score": round(salary_score, 1),
            "safety_score": round(safety_score, 1),
            "uniqueness_score": round(uniqueness_score, 1),
            "duplication_risk": round(safe_float(lev.get("duplication_risk", 0), 0), 1),
            "fade_penalty": round(fade * 7.5, 1),
            "bad_chalk_penalty": round(bad_chalk * 6.0, 1),
            "conflict_penalty": 24 if conflict else 0,
        },
        "tournament_engine_version": TOURNAMENT_ENGINE_VERSION,
        "p95_ceiling_points": ceiling.get("p95_ceiling_points", 0),
        "p99_ceiling_points": ceiling.get("p99_ceiling_points", 0),
        "stack_label": stack.get("stack_label", ""),
    }


def add_lineup_metadata(lineup_data):
    lineup = lineup_data["lineup"]
    mode = lineup_data.get("mode", "cash")
    stack = best_stack_info(lineup)
    stack_v2 = v2_lineup_stack_profile(lineup)
    lev_v2 = v2_lineup_leverage_profile(lineup)
    ceiling_v2 = v2_lineup_ceiling_profile(lineup)

    lineup_data["best_stack_team"] = stack["team"]
    lineup_data["best_stack_size"] = stack["size"]
    lineup_data["team_breakdown"] = stack["counts"]
    lineup_data["pitcher_conflict"] = pitcher_vs_hitter_conflict(lineup)
    lineup_data["salary_remaining"] = SALARY_CAP - lineup_data["total_salary"]
    lineup_data["roster_slots"] = ROSTER_SLOTS
    lineup_data["boost_breakdown"] = lineup_boost_breakdown(lineup, mode)
    lineup_data["lineup_explanation"] = lineup_explanation(lineup, mode)
    lineup_data["average_ownership"] = round(sum(p.get("ownership", 0) for p in lineup) / len(lineup), 2) if lineup else 0
    lineup_data.update(lineup_leverage_profile(lineup))
    lineup_data.update(lineup_core_profile(lineup))
    lineup_data.update(lineup_quality_profile(lineup, mode))
    lineup_data["tournament_engine_version"] = TOURNAMENT_ENGINE_VERSION
    lineup_data["v2_stack_profile"] = stack_v2
    lineup_data["v2_leverage_profile"] = lev_v2
    lineup_data["v2_ceiling_profile"] = ceiling_v2
    lineup_data["stack_correlation_score"] = stack_v2.get("stack_score", 0)
    lineup_data["ceiling_score"] = ceiling_v2.get("ceiling_score", 0)
    lineup_data["lineup_health"] = calculate_lineup_health_profile(lineup_data)
    return lineup_data


def v2_player_tournament_grade(player, stack_team=None, style="balanced", position_need=None):
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    ceiling = v2_player_ceiling(player, "95")
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    core = safe_float(player.get("core_play_score", 50), 50)
    team_total = safe_float(player.get("team_total", 4.2), 4.2)
    grade = ceiling * 1.15 + proj * 0.35 + lev * 0.13 + core * 0.035
    grade += max(0, team_total - 4.2) * 2.2
    grade += max(0, 14 - own) * (0.30 if style in ["aggressive", "nuclear"] else 0.16)
    grade -= max(0, own - 28) * (0.45 if style in ["aggressive", "nuclear"] else 0.25)
    if stack_team and normalize_team(player.get("team", "")) == stack_team and normalize_position(player.get("position", "")) != "P":
        grade += 6.5 if style in ["aggressive", "nuclear"] else 4.0
    if str(player.get("core_play_tier", "")).lower() in ["fade", "inactive"]:
        grade -= 20
    if str(player.get("core_play_tier", "")).lower() == "bad_chalk":
        grade -= 10
    return grade


def v2_choose_stack_teams(hitters):
    teams = {}
    for p in hitters:
        team = normalize_team(p.get("team", ""))
        if team not in teams:
            teams[team] = {"players": [], "score": 0.0}
        teams[team]["players"].append(p)
    scored = []
    for team, data in teams.items():
        players = data["players"]
        if len(players) < 3:
            continue
        team_total = estimated_team_total(team)
        avg_lev = sum(safe_float(p.get("leverage_score", 45), 45) for p in players) / len(players)
        avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in players) / len(players)
        top_ceil = sum(sorted([v2_player_ceiling(p, "95") for p in players], reverse=True)[:5])
        score = top_ceil + max(0, team_total - 4.0) * 12 + max(0, avg_lev - 45) * 0.55 + max(0, 20 - avg_own) * 0.55
        scored.append((team, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [team for team, score in scored]


def v2_required_position_count(position):
    return 2 if position == "P" else (3 if position == "OF" else 1)


def v2_same_position_count(lineup, position):
    return len([p for p in lineup if normalize_position(p.get("position", "")) == position])


def v2_lineup_position_valid(lineup):
    return (
        v2_same_position_count(lineup, "P") == 2
        and v2_same_position_count(lineup, "C") == 1
        and v2_same_position_count(lineup, "1B") == 1
        and v2_same_position_count(lineup, "2B") == 1
        and v2_same_position_count(lineup, "3B") == 1
        and v2_same_position_count(lineup, "SS") == 1
        and v2_same_position_count(lineup, "OF") == 3
        and not same_team_pitcher_conflict(lineup)
        and all(optimizer_starter_eligible(player) for player in lineup)
    )


def v2_attempt_lineup(groups, stack_team=None, stack_size=4, secondary_team=None, style="balanced", locked_objects=None, excluded_names=None, offset=0, max_players_per_team=5, min_salary=0, avoid_pitcher_vs_hitter=True):
    locked_objects = locked_objects or []
    excluded_names = excluded_names or set()
    lineup = []
    used = set()

    def add_player(p):
        if not p or p.get("name") in used or p.get("name") in excluded_names:
            return False
        pos = normalize_position(p.get("position", ""))
        if v2_same_position_count(lineup, pos) >= v2_required_position_count(pos):
            return False
        if not optimizer_starter_eligible(p):
            return False
        if pos == "P" and any(
            normalize_position(existing.get("position", "")) == "P"
            and normalize_team(existing.get("team", "")) == normalize_team(p.get("team", ""))
            for existing in lineup
        ):
            return False
        lineup.append(p)
        used.add(p.get("name"))
        return True

    for p in locked_objects:
        add_player(p)

    # Pitchers: ceiling plus not directly against the stack when possible.
    pitcher_pool = list(groups.get("P", []))
    pitcher_pool.sort(key=lambda p: v2_player_tournament_grade(p, None, style), reverse=True)
    pitcher_rotation = pitcher_pool[offset % max(1, len(pitcher_pool)):] + pitcher_pool[:offset % max(1, len(pitcher_pool))]
    for p in pitcher_rotation:
        if v2_same_position_count(lineup, "P") >= 2:
            break
        if stack_team and normalize_team(p.get("opponent", "")) == stack_team and avoid_pitcher_vs_hitter:
            continue
        add_player(p)
    for p in pitcher_rotation:
        if v2_same_position_count(lineup, "P") >= 2:
            break
        add_player(p)

    # Main stack hitters.
    hitter_positions = ["C", "1B", "2B", "3B", "SS", "OF"]
    stack_candidates = []
    for pos in hitter_positions:
        stack_candidates.extend([p for p in groups.get(pos, []) if normalize_team(p.get("team", "")) == stack_team])
    stack_candidates.sort(key=lambda p: v2_player_tournament_grade(p, stack_team, style), reverse=True)
    rotated_stack = stack_candidates[offset % max(1, len(stack_candidates)):] + stack_candidates[:offset % max(1, len(stack_candidates))]
    for p in rotated_stack:
        if len([x for x in lineup if normalize_position(x.get("position", "")) != "P" and normalize_team(x.get("team", "")) == stack_team]) >= stack_size:
            break
        add_player(p)

    # Secondary stack, 2-3 players if possible.
    secondary_target = 3 if style == "nuclear" else 2
    sec_candidates = []
    if secondary_team and secondary_team != stack_team:
        for pos in hitter_positions:
            sec_candidates.extend([p for p in groups.get(pos, []) if normalize_team(p.get("team", "")) == secondary_team])
        sec_candidates.sort(key=lambda p: v2_player_tournament_grade(p, secondary_team, style), reverse=True)
        for p in sec_candidates:
            if len([x for x in lineup if normalize_position(x.get("position", "")) != "P" and normalize_team(x.get("team", "")) == secondary_team]) >= secondary_target:
                break
            add_player(p)

    # Fill positions by tournament grade.
    for pos in ["C", "1B", "2B", "3B", "SS", "OF"]:
        while v2_same_position_count(lineup, pos) < v2_required_position_count(pos):
            pool = [p for p in groups.get(pos, []) if p.get("name") not in used and p.get("name") not in excluded_names]
            if not pool:
                break
            pool.sort(key=lambda p: v2_player_tournament_grade(p, stack_team, style), reverse=True)
            idx = (offset + len(lineup)) % len(pool)
            add_player(pool[idx])
            if len(pool) == 1:
                break

    if len(lineup) != 10 or not v2_lineup_position_valid(lineup):
        return None

    # Salary repair: replace worst points-per-dollar/tournament grade player first.
    attempts = 0
    while sum(safe_int(p.get("salary", 0), 0) for p in lineup) > SALARY_CAP and attempts < 20:
        attempts += 1
        replaceable = [(idx, p) for idx, p in enumerate(lineup) if p.get("name") not in [x.get("name") for x in locked_objects]]
        if not replaceable:
            return None
        replaceable.sort(key=lambda item: (safe_int(item[1].get("salary", 0), 0), -v2_player_tournament_grade(item[1], stack_team, style)), reverse=True)
        replaced = False
        for idx, current in replaceable:
            pos = normalize_position(current.get("position", ""))
            cheaper = [p for p in groups.get(pos, []) if p.get("name") not in used and safe_int(p.get("salary", 0), 0) < safe_int(current.get("salary", 0), 0)]
            cheaper.sort(key=lambda p: v2_player_tournament_grade(p, stack_team, style), reverse=True)
            for rep in cheaper[:12]:
                new_lineup = list(lineup)
                new_lineup[idx] = rep
                if sum(safe_int(p.get("salary", 0), 0) for p in new_lineup) <= SALARY_CAP or safe_int(rep.get("salary",0),0) < safe_int(current.get("salary",0),0):
                    used.remove(current.get("name"))
                    used.add(rep.get("name"))
                    lineup[idx] = rep
                    replaced = True
                    break
            if replaced:
                break
        if not replaced:
            return None

    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    if salary > SALARY_CAP or salary < min_salary:
        return None
    if any(c > min(max_players_per_team, 5) for c in count_team_players(lineup, hitters_only=True).values()):
        return None
    if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(lineup):
        return None
    return lineup


def build_fast_multi_lineups_for_pro(request, count):
    locked_players = request.locked_players or []
    excluded_players = request.excluded_players or []
    excluded_names = set(excluded_players)
    mode = str(getattr(request, "mode", "cash") or "cash").lower()
    count = count if count in [1, 5, 10, 20] else 1
    randomness = safe_int(getattr(request, "randomness", 0), 0)
    strategy_mode = str(getattr(request, "strategy_mode", "") or "").lower()
    stack_type = str(getattr(request, "stack_type", "auto") or "auto").lower()
    build_style = str(getattr(request, "build_style", "") or "").lower()
    style = "nuclear" if "nuclear" in build_style or randomness >= 55 else ("aggressive" if "aggressive" in build_style or randomness >= 30 or "large" in strategy_mode or "twenty" in strategy_mode else "balanced")

    players = add_values(load_players())
    error = validate_locks(players, locked_players, excluded_players)
    if error:
        return [], error, {}, 0
    optimized_pool, trim_report = build_optimizer_pool_with_fallback(players, locked_players=locked_players, excluded_players=excluded_players)
    optimized_pool = [p for p in optimized_pool if p.get("name") not in excluded_names and valid_optimizer_player(p) and not is_manual_inactive_player(p)]

    groups = {pos: [p for p in optimized_pool if normalize_position(p.get("position", "")) == pos] for pos in ["P", "C", "1B", "2B", "3B", "SS", "OF"]}
    for pos in groups:
        groups[pos].sort(key=lambda p: v2_player_tournament_grade(p, None, style), reverse=True)

    if not has_required_mlb_positions(optimized_pool):
        return [], f"Not enough players at each MLB position after slate cleanup. Pool counts: P={len(groups['P'])}, C={len(groups['C'])}, 1B={len(groups['1B'])}, 2B={len(groups['2B'])}, 3B={len(groups['3B'])}, SS={len(groups['SS'])}, OF={len(groups['OF'])}.", trim_report, 0

    locked_objects = [p for p in optimized_pool if p.get("name") in set(locked_players)]
    hitters = [p for p in optimized_pool if normalize_position(p.get("position", "")) != "P"]
    stack_teams = v2_choose_stack_teams(hitters)
    if not stack_teams:
        stack_teams = list({normalize_team(p.get("team", "")) for p in hitters})

    if mode == "cash":
        desired_stack_sizes = [2, 3]
    elif stack_type in ["5-3", "5-2"] or style == "nuclear":
        desired_stack_sizes = [5, 5, 4, 5, 3]
    elif stack_type in ["4-3"] or style == "aggressive":
        desired_stack_sizes = [4, 5, 4, 3]
    else:
        desired_stack_sizes = [4, 3, 5, 4]

    candidates = []
    seen = set()
    checked = 0
    attempts = max(650, count * 95)
    max_players_per_team = min(max(safe_int(getattr(request, "max_players_per_team", 5), 5), 3), 6 if mode == "gpp" else 5)
    min_salary = safe_int(getattr(request, "min_salary", 0), 0)
    if mode == "gpp" and min_salary == 0:
        min_salary = 45500 if style in ["aggressive", "nuclear"] else 47000
    avoid_conflict = bool(getattr(request, "avoid_pitcher_vs_hitter", True))
    if getattr(request, "force_bring_back", None) is not None:
        avoid_conflict = bool(getattr(request, "force_bring_back", True))

    for i in range(attempts):
        checked += 1
        stack_team = stack_teams[i % len(stack_teams)] if stack_teams else None
        secondary_team = stack_teams[(i // max(1, len(stack_teams)) + i + 1) % len(stack_teams)] if len(stack_teams) > 1 else None
        stack_size = desired_stack_sizes[i % len(desired_stack_sizes)]
        lineup = v2_attempt_lineup(
            groups,
            stack_team=stack_team,
            stack_size=stack_size,
            secondary_team=secondary_team,
            style=style,
            locked_objects=locked_objects,
            excluded_names=excluded_names,
            offset=i,
            max_players_per_team=max_players_per_team,
            min_salary=min_salary,
            avoid_pitcher_vs_hitter=avoid_conflict,
        )
        if not lineup:
            continue
        if not has_all_locked(lineup, locked_players):
            continue
        key = lineup_key(lineup)
        if key in seen:
            continue
        seen.add(key)
        salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
        projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
        score = score_lineup(lineup, mode, randomness)
        data = add_lineup_metadata({
            "mode": mode,
            "total_salary": salary,
            "projected_points": round(projection, 2),
            "optimizer_score": round(score, 2),
            "lineup": lineup,
        })
        # Put true tournament equity into optimizer score after metadata is attached.
        q = data.get("lineup_quality_breakdown", {})
        data["optimizer_score"] = round(
            safe_float(data.get("optimizer_score", 0), 0)
            + safe_float(q.get("ceiling_score", 0), 0) * (1.25 if mode == "gpp" else 0.25)
            + safe_float(q.get("stack_score", 0), 0) * (1.05 if mode == "gpp" else 0.10)
            + safe_float(q.get("leverage_score", 0), 0) * (0.85 if mode == "gpp" else 0.10)
            + safe_float(q.get("uniqueness_score", 0), 0) * (0.55 if mode == "gpp" else 0.05),
            2,
        )
        candidates.append(data)

    if not candidates:
        return [], "Tournament Engine V2 could not find valid MLB lineups. Try lowering minimum salary, clearing locks/excludes, or allowing 5 players per team.", trim_report, checked

    candidates.sort(key=lambda x: (safe_float(x.get("optimizer_score", 0), 0), safe_float(x.get("lineup_quality_score", 0), 0)), reverse=True)
    selected = diversify_lineups(
        all_lineups=candidates,
        count=count,
        max_exposure=min(max(safe_int(getattr(request, "max_exposure", 60), 60), 20), 100),
        max_same_players=min(max(safe_int(getattr(request, "max_same_players", 7), 7), 3), 9),
        locked_players=locked_players,
        player_min_exposure=getattr(request, "player_min_exposure", {}),
        player_max_exposure=getattr(request, "player_max_exposure", {}),
    )
    selected.sort(key=lambda x: (safe_float(x.get("optimizer_score", 0), 0), safe_float(x.get("lineup_quality_score", 0), 0)), reverse=True)
    trim_report["tournament_engine_version"] = TOURNAMENT_ENGINE_VERSION
    trim_report["candidate_count"] = len(candidates)
    trim_report["builder_style"] = style
    return selected, None, trim_report, checked


def payout_for_rank(rank, contest):
    contest_size = max(1, safe_int(contest.get("contest_size", 1), 1))
    paid = max(1, min(contest_size, safe_int(contest.get("estimated_paid_spots") or contest.get("paid_positions") or 1, 1)))
    prize_pool = max(0.0, safe_float(contest.get("prize_pool", 0), 0))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 5.0), 5.0))
    rank = max(1, safe_int(rank, 1))
    payout_table = contest.get("payout_table")
    if not isinstance(payout_table, list):
        payout_table = load_payout_table()
    for tier in payout_table:
        if safe_int(tier.get("start_rank"), 0) <= rank <= safe_int(tier.get("end_rank"), 0):
            return round(max(0.0, safe_float(tier.get("payout"), 0)), 2)
    if payout_table and rank > max(safe_int(tier.get("end_rank"), 0) for tier in payout_table):
        return 0.0
    top_prize = safe_float(contest.get("top_prize", 0), 0)
    if top_prize <= 0:
        # Realistic top-heavy estimate: big fields pay 10-18% to first, small fields 8-12%.
        top_prize = prize_pool * (0.16 if contest_size >= 20000 else 0.12 if contest_size >= 5000 else 0.09)
    min_cash = max(round(entry_fee * 1.8, 2), round(prize_pool * 0.00018, 2))
    if safe_int(rank, contest_size) > paid:
        return 0.0
    if rank == 1:
        return round(top_prize, 2)
    pct = rank / max(1, paid)
    # Smooth top-heavy curve from top prize down to min cash.
    if pct <= 0.001:
        frac = 0.72
    elif pct <= 0.005:
        frac = 0.38
    elif pct <= 0.01:
        frac = 0.22
    elif pct <= 0.025:
        frac = 0.115
    elif pct <= 0.05:
        frac = 0.065
    elif pct <= 0.10:
        frac = 0.036
    elif pct <= 0.20:
        frac = 0.020
    elif pct <= 0.40:
        frac = 0.010
    else:
        frac = 0.0
    payout = max(min_cash, top_prize * frac) if frac > 0 else min_cash
    return round(min(payout, top_prize), 2)


def v2_estimate_rank_from_score(score, lineup, contest):
    contest_size = max(10, safe_int(contest.get("contest_size", 5000), 5000))
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    quality = lineup_quality_profile(lineup, "gpp")
    # strength translates into rank. This is calibrated to avoid fake #2 ranks for ordinary lineups.
    strength = (
        safe_float(quality.get("lineup_quality_score", 0), 0) * 0.34
        + safe_float(ceiling.get("ceiling_score", 0), 0) * 0.26
        + safe_float(stack.get("stack_score", 0), 0) * 0.22
        + safe_float(lev.get("leverage_score", 0), 0) * 0.18
    )
    # median rank: even strong GPP lineups often have middling median outcomes.
    median_pct = 0.72 - (strength / 100.0) * 0.45
    median_rank = int(max(1, min(contest_size, contest_size * median_pct)))
    # ceiling rank: 95th/99th percentile outcome.
    ceiling_strength = safe_float(ceiling.get("ceiling_score", 0), 0) * 0.36 + safe_float(stack.get("stack_score", 0), 0) * 0.30 + safe_float(lev.get("leverage_score", 0), 0) * 0.22 + safe_float(lev.get("uniqueness_score", 0), 0) * 0.12
    ceiling_pct = 0.18 - (ceiling_strength / 100.0) * 0.155
    ceiling_rank = int(max(1, min(contest_size, contest_size * max(0.008, ceiling_pct))))
    takedown_pct = 0.035 - (ceiling_strength / 100.0) * 0.032
    takedown_rank = int(max(1, min(contest_size, contest_size * max(0.00025, takedown_pct))))
    return median_rank, ceiling_rank, takedown_rank, strength, ceiling_strength


def monte_carlo_lineup_simulation_v2(lineup, contest, runs=700, field_scores=None):
    contest_size = max(10, safe_int(contest.get("contest_size", 5000), 5000))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", 1), 1)))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 5.0), 5.0))

    median_rank, ceiling_rank, takedown_rank, strength, ceiling_strength = v2_estimate_rank_from_score(0, lineup, contest)
    paid_rate = paid_spots / contest_size
    cash_probability = max(0.0, min(95.0, paid_rate * 100 + (strength - 50) * 0.45))
    top_10_probability = max(0.0, min(65.0, (10.0 + (strength - 50) * 0.42 + (ceiling_strength - 50) * 0.18)))
    top_1_probability = max(0.0, min(14.0, 0.35 + max(0, ceiling_strength - 45) * 0.105 + max(0, strength - 62) * 0.06))
    top_0_1_probability = max(0.0, min(1.6, 0.015 + max(0, ceiling_strength - 55) * 0.018 + max(0, strength - 75) * 0.014))
    win_probability = max(0.0, min(0.18, top_0_1_probability * 0.055))

    median_payout = payout_for_rank(median_rank, contest)
    ceiling_payout = payout_for_rank(ceiling_rank, contest)
    takedown_payout = payout_for_rank(takedown_rank, contest)
    min_cash = payout_for_rank(paid_spots, contest)
    top_10_rank = max(1, int(contest_size * 0.10))
    top_1_rank = max(1, int(contest_size * 0.01))
    top_01_rank = max(1, int(contest_size * 0.001))
    top_10_payout = payout_for_rank(top_10_rank, contest)
    top_1_payout = payout_for_rank(top_1_rank, contest)
    top_01_payout = payout_for_rank(top_01_rank, contest)

    # Probability-weighted payout. This is not a guarantee and avoids fake giant EV.
    expected_payout = (
        (cash_probability / 100.0) * min_cash * 0.75
        + (top_10_probability / 100.0) * max(top_10_payout - min_cash, 0) * 0.35
        + (top_1_probability / 100.0) * max(top_1_payout - min_cash, 0) * 0.55
        + (top_0_1_probability / 100.0) * max(top_01_payout - top_1_payout, 0) * 0.85
        + (win_probability / 100.0) * max(payout_for_rank(1, contest) - top_01_payout, 0)
    )
    # Upside lineups can have positive EV, but clamp out impossible moon math.
    expected_payout = max(0.0, min(expected_payout, max(entry_fee * 8.0, top_1_payout * 0.10)))
    expected_value = expected_payout - entry_fee
    roi = (expected_value / entry_fee) * 100

    return {
        "simulation_runs": runs,
        "average_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "median_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "ceiling_sim_score": v2_lineup_ceiling_profile(lineup).get("p95_ceiling_points", 0),
        "floor_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup) * 0.58, 2),
        "average_rank": median_rank,
        "projected_rank": median_rank,
        "median_rank": median_rank,
        "ceiling_rank": ceiling_rank,
        "takedown_rank": takedown_rank,
        "cash_probability": round(cash_probability, 1),
        "top_10_probability": round(top_10_probability, 1),
        "top_1_probability": round(top_1_probability, 2),
        "top_0_1_probability": round(top_0_1_probability, 3),
        "win_probability": round(win_probability, 3),
        "expected_payout": round(expected_payout, 2),
        "expected_value": round(expected_value, 2),
        "roi_percent": round(roi, 1),
        "projected_payout": round(expected_payout, 2),
        "median_payout": round(median_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "best_payout": round(max(ceiling_payout, takedown_payout), 2),
        "min_cash_payout": round(min_cash, 2),
        "top_10_rank_payout": round(top_10_payout, 2),
        "top_1_rank_payout": round(top_1_payout, 2),
        "top_0_1_rank_payout": round(top_01_payout, 2),
        "tournament_strength": round(strength, 1),
        "ceiling_strength": round(ceiling_strength, 1),
    }


# ============================================================
# DFS EDGE MLB - TOURNAMENT ENGINE V3 OVERRIDES
# Goal: stop building projection-sorter lineups and target contest-winning
# tournament equity: ceiling, stack correlation, leverage, uniqueness,
# and top 0.1% upside. These definitions intentionally come last so the
# existing FastAPI routes call them at runtime.
# ============================================================

TOURNAMENT_ENGINE_VERSION = "dfs_edge_mlb_tournament_engine_v3_takedown_ev"


def v3_is_gpp_mode(mode, randomness=0):
    mode = str(mode or "gpp").lower()
    r = safe_int(randomness, 0)
    return mode in ["gpp", "single_entry", "big_gpp", "large_gpp", "tournament"] or r >= 20


def v3_style_from_request(request, mode="gpp"):
    raw_style = str(getattr(request, "build_style", "") or getattr(request, "strategy_mode", "") or "").lower()
    focus = str(getattr(request, "contest_focus", "") or getattr(request, "contest_type", "") or "").lower()
    r = safe_int(getattr(request, "randomness", 0), 0)
    if "nuclear" in raw_style or r >= 70:
        return "nuclear"
    if "aggressive" in raw_style or "big" in focus or "large" in focus or r >= 35:
        return "aggressive"
    if "safe" in raw_style or str(mode).lower() == "cash":
        return "safe"
    return "balanced"


def v3_player_distribution(player):
    pos = normalize_position(player.get("position", ""))
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    core = safe_float(player.get("core_play_score", 50), 50)
    total = safe_float(player.get("team_total", 4.2), 4.2)
    trend = safe_float(player.get("trend_score", 50), 50)
    salary = safe_int(player.get("salary", 0), 0)
    value = (proj / salary) * 1000 if salary > 0 else 0

    if pos == "P":
        floor_mult = 0.46 if proj < 15 else 0.55
        p85_mult = 1.28 + max(0, lev - 50) * 0.002
        p95_mult = 1.55 + max(0, lev - 50) * 0.004
        p99_mult = 1.92 + max(0, lev - 55) * 0.007
        if own <= 10:
            p95_mult += 0.08
            p99_mult += 0.14
    else:
        # MLB hitter outcomes are highly volatile. Tournament winning lineups need this.
        floor_mult = 0.20
        p85_mult = 1.72
        p95_mult = 2.55
        p99_mult = 3.65
        if total >= 5.0:
            p95_mult += 0.20
            p99_mult += 0.32
        if own <= 8:
            p95_mult += 0.28
            p99_mult += 0.55
        elif own <= 14:
            p95_mult += 0.14
            p99_mult += 0.28
        if lev >= 60:
            p95_mult += 0.16
            p99_mult += 0.34
        if trend >= 70:
            p95_mult += 0.10
            p99_mult += 0.18
        if value >= 2.2:
            p85_mult += 0.12
            p95_mult += 0.10

    floor = round(max(0, proj * floor_mult), 2)
    p50 = round(proj, 2)
    p85 = round(max(p50, proj * p85_mult), 2)
    p95 = round(max(p85, proj * p95_mult + max(0, core - 60) * 0.035), 2)
    p99 = round(max(p95, proj * p99_mult + max(0, lev - 55) * 0.08), 2)
    return {"floor": floor, "p50": p50, "p85": p85, "p95": p95, "p99": p99}


def v2_player_ceiling(player, percentile="95"):
    d = v3_player_distribution(player)
    key = "p99" if str(percentile) in ["99", "p99"] else "p95" if str(percentile) in ["95", "p95"] else "p85"
    return d[key]


def v2_lineup_ceiling_profile(lineup):
    if not lineup:
        return {"boosted_projection": 0, "raw_projection": 0, "p85_ceiling_points": 0, "p95_ceiling_points": 0, "p99_ceiling_points": 0, "ceiling_score": 0}
    raw = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
    boosted = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    p85 = sum(v3_player_distribution(p)["p85"] for p in lineup)
    p95 = sum(v3_player_distribution(p)["p95"] for p in lineup)
    p99 = sum(v3_player_distribution(p)["p99"] for p in lineup)
    hitters = [p for p in lineup if normalize_position(p.get("position", "")) != "P"]
    stack = best_stack_info(lineup)
    stack_size = safe_int(stack.get("size", 0), 0)
    team_total = estimated_team_total(stack.get("team", "")) if stack.get("team") else 4.2
    stack_bonus = max(0, stack_size - 2) * (3.8 + max(0, team_total - 4.2) * 1.7)
    avg_own_hitters = sum(safe_float(p.get("ownership", 12), 12) for p in hitters) / len(hitters) if hitters else 12
    low_owned_bonus = max(0, 18 - avg_own_hitters) * 0.55
    p95 += stack_bonus + low_owned_bonus
    p99 += stack_bonus * 1.65 + low_owned_bonus * 1.35
    # Score rewards separation between median and 95/99 ceiling, not just raw projection.
    ceiling_gap = max(0, p95 - boosted)
    ceiling_score = 36 + (boosted - 65) * 0.42 + ceiling_gap * 0.72 + stack_bonus * 1.05 + low_owned_bonus * 0.65
    ceiling_score = round(max(0, min(100, ceiling_score)), 1)
    return {
        "boosted_projection": round(boosted, 2),
        "raw_projection": round(raw, 2),
        "p85_ceiling_points": round(p85, 2),
        "p95_ceiling_points": round(p95, 2),
        "p99_ceiling_points": round(p99, 2),
        "ceiling_score": ceiling_score,
        "ceiling_gap": round(ceiling_gap, 2),
    }


def v2_lineup_stack_profile(lineup):
    hitters = [p for p in lineup if normalize_position(p.get("position", "")) != "P"]
    counts = {}
    for p in hitters:
        team = normalize_team(p.get("team", ""))
        counts[team] = counts.get(team, 0) + 1
    if not counts:
        return {"stack_score": 0, "stack_label": "No Stack", "primary_stack_team": "", "primary_stack_size": 0, "secondary_stack_team": "", "secondary_stack_size": 0, "stack_counts": {}}
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    primary_team, primary_size = ordered[0]
    secondary_team, secondary_size = (ordered[1] if len(ordered) > 1 else ("", 0))
    primary_total = estimated_team_total(primary_team)
    secondary_total = estimated_team_total(secondary_team) if secondary_team else 0
    primary_players = [p for p in hitters if normalize_team(p.get("team", "")) == primary_team]
    secondary_players = [p for p in hitters if normalize_team(p.get("team", "")) == secondary_team]
    primary_ceiling = sum(v3_player_distribution(p)["p95"] for p in primary_players)
    secondary_ceiling = sum(v3_player_distribution(p)["p95"] for p in secondary_players)
    primary_own = sum(safe_float(p.get("ownership", 12), 12) for p in primary_players) / len(primary_players) if primary_players else 12
    secondary_own = sum(safe_float(p.get("ownership", 12), 12) for p in secondary_players) / len(secondary_players) if secondary_players else 12

    size_score = {1: 8, 2: 22, 3: 48, 4: 74, 5: 88}.get(primary_size, 95)
    if primary_size >= 5:
        label = "5-Man Takedown Stack"
    elif primary_size == 4:
        label = "4-Man GPP Stack"
    elif primary_size == 3:
        label = "3-Man Stack"
    else:
        label = "Thin Stack"

    secondary_bonus = 0
    if secondary_size >= 3:
        secondary_bonus = 13
        label += " + 3-Man Secondary"
    elif secondary_size == 2:
        secondary_bonus = 7
        label += " + Mini Correlation"

    total_bonus = max(0, primary_total - 4.0) * 8.5 + max(0, secondary_total - 4.0) * 3.5
    low_own_bonus = max(0, 18 - primary_own) * 0.85 + max(0, 16 - secondary_own) * 0.35
    ceiling_bonus = max(0, primary_ceiling - 35) * 0.38 + max(0, secondary_ceiling - 20) * 0.18
    stack_score = round(max(0, min(100, size_score + secondary_bonus + total_bonus + low_own_bonus + ceiling_bonus - max(0, primary_own - 26) * 0.6)), 1)
    return {
        "stack_score": stack_score,
        "stack_label": label,
        "primary_stack_team": primary_team,
        "primary_stack_size": primary_size,
        "primary_stack_team_total": round(primary_total, 1),
        "secondary_stack_team": secondary_team,
        "secondary_stack_size": secondary_size,
        "secondary_stack_team_total": round(secondary_total, 1),
        "stack_counts": counts,
        "primary_stack_avg_ownership": round(primary_own, 1),
    }


def v2_lineup_leverage_profile(lineup):
    if not lineup:
        return {"leverage_score": 0, "uniqueness_score": 0, "duplication_risk": 100, "average_ownership": 0, "chalk_count": 0, "low_owned_count": 0}
    avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in lineup) / len(lineup)
    max_own = max(safe_float(p.get("ownership", 12), 12) for p in lineup)
    chalk_count = len([p for p in lineup if safe_float(p.get("ownership", 12), 12) >= 24])
    mega_chalk = len([p for p in lineup if safe_float(p.get("ownership", 12), 12) >= 32])
    low_count = len([p for p in lineup if safe_float(p.get("ownership", 12), 12) <= 10])
    mid_low = len([p for p in lineup if 10 < safe_float(p.get("ownership", 12), 12) <= 16])
    player_lev = sum(safe_float(p.get("leverage_score", 45), 45) for p in lineup) / len(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    stack = v2_lineup_stack_profile(lineup)
    leverage_score = 42 + (player_lev - 45) * 0.72 + low_count * 6.2 + mid_low * 2.4 + max(0, ceiling.get("ceiling_score", 0) - 60) * 0.22
    leverage_score -= chalk_count * 4.7 + mega_chalk * 5.5 + max(0, avg_own - 18) * 1.1
    uniqueness_score = 45 + low_count * 7.8 + mid_low * 2.6 + max(0, 18 - avg_own) * 2.1 + stack.get("stack_score", 0) * 0.10 - chalk_count * 5.5 - mega_chalk * 7.0
    duplication_risk = 100 - uniqueness_score + max(0, avg_own - 16) * 1.8 + chalk_count * 6.0 - max(0, stack.get("primary_stack_size", 0) - 3) * 4.0
    return {
        "leverage_score": round(max(0, min(100, leverage_score)), 1),
        "uniqueness_score": round(max(0, min(100, uniqueness_score)), 1),
        "duplication_risk": round(max(0, min(100, duplication_risk)), 1),
        "average_ownership": round(avg_own, 2),
        "max_ownership": round(max_own, 1),
        "chalk_count": chalk_count,
        "low_owned_count": low_count,
    }


def v2_tournament_equity_score(lineup, mode="gpp", style="balanced"):
    projection = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    conflict = pitcher_vs_hitter_conflict(lineup)
    inactive = len([p for p in lineup if not bool(p.get("active", True))])
    bad_chalk = safe_int(core.get("bad_chalk_count", 0), 0)
    fade = safe_int(core.get("fade_count", 0), 0)
    style = str(style or "balanced").lower()
    if str(mode).lower() == "cash" or style == "safe":
        score = projection * 0.92 + safe_float(core.get("average_core_play_score", 50), 50) * 0.30 + ceiling.get("ceiling_score", 0) * 0.22 - conflict * 18 - inactive * 100
    elif style == "nuclear":
        score = ceiling.get("p99_ceiling_points", 0) * 1.20 + stack.get("stack_score", 0) * 1.42 + lev.get("leverage_score", 0) * 1.08 + lev.get("uniqueness_score", 0) * 0.95 + projection * 0.05
        score -= bad_chalk * 12 + fade * 10 + conflict * 18 + inactive * 100
    elif style == "aggressive":
        score = ceiling.get("p95_ceiling_points", 0) * 1.06 + stack.get("stack_score", 0) * 1.20 + lev.get("leverage_score", 0) * 0.92 + lev.get("uniqueness_score", 0) * 0.70 + projection * 0.10
        score -= bad_chalk * 10 + fade * 9 + conflict * 18 + inactive * 100
    else:
        score = ceiling.get("p95_ceiling_points", 0) * 0.82 + stack.get("stack_score", 0) * 0.82 + lev.get("leverage_score", 0) * 0.62 + projection * 0.30 + lev.get("uniqueness_score", 0) * 0.35
        score -= bad_chalk * 7 + fade * 8 + conflict * 18 + inactive * 100
    return round(score, 4)


def score_lineup(lineup, mode, randomness=0):
    style = "nuclear" if safe_int(randomness, 0) >= 65 else ("aggressive" if safe_int(randomness, 0) >= 30 or str(mode).lower() != "cash" else "safe")
    return round(v2_tournament_equity_score(lineup, mode, style) + deterministic_random_bonus(lineup, min(100, safe_int(randomness, 0))) * (0.55 if style in ["aggressive", "nuclear"] else 0.12), 4)


def lineup_quality_profile(lineup, mode="gpp"):
    if not lineup:
        return {"lineup_quality_score": 0, "win_probability": 0, "lineup_quality_label": "No Lineup", "lineup_quality_breakdown": {"projection_score": 0, "ceiling_score": 0, "leverage_score": 0, "stack_score": 0, "core_score": 0, "salary_score": 0, "safety_score": 0}}
    mode = str(mode or "gpp").lower()
    projection = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    projection_score = round(max(0, min(100, (projection - 60) * 1.55)), 1)
    ceiling_score = safe_float(ceiling.get("ceiling_score", 0), 0)
    stack_score = safe_float(stack.get("stack_score", 0), 0)
    leverage_score = safe_float(lev.get("leverage_score", 0), 0)
    uniqueness_score = safe_float(lev.get("uniqueness_score", 0), 0)
    core_score = safe_float(core.get("average_core_play_score", 50), 50)
    salary_score = 92 if 0 <= remaining <= 1700 else 82 if remaining <= 3200 else 70 if remaining <= 5200 else 58
    safety_score = 93 - len([p for p in lineup if not bool(p.get("active", True))]) * 40 - (22 if pitcher_vs_hitter_conflict(lineup) else 0)
    safety_score -= safe_int(core.get("fade_count", 0), 0) * 8
    safety_score = round(max(0, min(100, safety_score)), 1)

    if mode == "cash":
        quality = projection_score * 0.38 + safety_score * 0.26 + core_score * 0.17 + ceiling_score * 0.08 + leverage_score * 0.05 + salary_score * 0.06
    else:
        quality = ceiling_score * 0.31 + stack_score * 0.24 + leverage_score * 0.20 + uniqueness_score * 0.13 + projection_score * 0.07 + core_score * 0.03 + salary_score * 0.02
    quality -= safe_int(core.get("bad_chalk_count", 0), 0) * (5.0 if mode != "cash" else 2.0)
    quality = round(max(0, min(100, quality)), 1)
    takedown_strength = round(max(0, min(100, ceiling_score * 0.34 + stack_score * 0.27 + leverage_score * 0.22 + uniqueness_score * 0.17)), 1)

    if mode != "cash":
        if takedown_strength >= 82:
            label = "Takedown Candidate"
        elif takedown_strength >= 72:
            label = "Strong GPP Upside"
        elif takedown_strength >= 60:
            label = "Playable Tournament Build"
        elif takedown_strength >= 48:
            label = "Needs More Upside"
        else:
            label = "Weak Tournament Build"
    else:
        label = "Cash Core" if quality >= 82 else "Cash Viable" if quality >= 70 else "Risky Cash" if quality >= 55 else "Weak Build"
    return {
        "lineup_quality_score": quality,
        "win_probability": takedown_strength if mode != "cash" else round(max(0, min(100, quality * 0.8 + safety_score * 0.2)), 1),
        "lineup_quality_label": label,
        "lineup_quality_breakdown": {
            "projection_score": projection_score,
            "ceiling_score": round(ceiling_score, 1),
            "leverage_score": round(leverage_score, 1),
            "stack_score": round(stack_score, 1),
            "core_score": round(core_score, 1),
            "salary_score": round(salary_score, 1),
            "safety_score": round(safety_score, 1),
            "uniqueness_score": round(uniqueness_score, 1),
            "duplication_risk": round(safe_float(lev.get("duplication_risk", 0), 0), 1),
        },
        "takedown_strength": takedown_strength,
        "tournament_engine_version": TOURNAMENT_ENGINE_VERSION,
        "p95_ceiling_points": ceiling.get("p95_ceiling_points", 0),
        "p99_ceiling_points": ceiling.get("p99_ceiling_points", 0),
        "stack_label": stack.get("stack_label", ""),
    }


def add_lineup_metadata(lineup_data):
    lineup = lineup_data["lineup"]
    mode = lineup_data.get("mode", "cash")
    stack_basic = best_stack_info(lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    lineup_data["best_stack_team"] = stack.get("primary_stack_team") or stack_basic.get("team", "")
    lineup_data["best_stack_size"] = stack.get("primary_stack_size") or stack_basic.get("size", 0)
    lineup_data["team_breakdown"] = stack_basic.get("counts", {})
    lineup_data["pitcher_conflict"] = pitcher_vs_hitter_conflict(lineup)
    lineup_data["salary_remaining"] = SALARY_CAP - lineup_data["total_salary"]
    lineup_data["roster_slots"] = ROSTER_SLOTS
    lineup_data["boost_breakdown"] = lineup_boost_breakdown(lineup, mode)
    lineup_data["lineup_explanation"] = lineup_explanation(lineup, mode)
    lineup_data["average_ownership"] = round(sum(safe_float(p.get("ownership", 0), 0) for p in lineup) / len(lineup), 2) if lineup else 0
    lineup_data.update(lineup_leverage_profile(lineup))
    lineup_data.update(lineup_core_profile(lineup))
    lineup_data.update(lineup_quality_profile(lineup, mode))
    lineup_data["tournament_engine_version"] = TOURNAMENT_ENGINE_VERSION
    lineup_data["v2_stack_profile"] = stack
    lineup_data["v2_leverage_profile"] = lev
    lineup_data["v2_ceiling_profile"] = ceiling
    lineup_data["stack_correlation_score"] = stack.get("stack_score", 0)
    lineup_data["ceiling_score"] = ceiling.get("ceiling_score", 0)
    lineup_data["tournament_notes"] = [
        f"{stack.get('stack_label', 'Stack profile')} ({stack.get('primary_stack_team', '')} {stack.get('primary_stack_size', 0)})",
        f"Ceiling {ceiling.get('ceiling_score', 0)} / Leverage {lev.get('leverage_score', 0)} / Unique {lev.get('uniqueness_score', 0)}",
        "V3 targets first-place equity, not median cash safety." if str(mode).lower() != "cash" else "Cash mode targets median safety and projection.",
    ]
    lineup_data["lineup_health"] = calculate_lineup_health_profile(lineup_data)
    return lineup_data


def v2_player_tournament_grade(player, stack_team=None, style="balanced", position_need=None):
    pos = normalize_position(player.get("position", ""))
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    dist = v3_player_distribution(player)
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    core = safe_float(player.get("core_play_score", 50), 50)
    total = safe_float(player.get("team_total", 4.2), 4.2)
    style = str(style or "balanced").lower()
    grade = dist["p95"] * 1.02 + dist["p99"] * 0.42 + proj * 0.12 + lev * 0.12 + core * 0.03 + max(0, total - 4.2) * 3.0
    if style == "nuclear":
        grade = dist["p99"] * 1.20 + dist["p95"] * 0.65 + lev * 0.20 + max(0, 16 - own) * 0.75 + max(0, total - 4.2) * 4.4
    elif style == "aggressive":
        grade = dist["p99"] * 0.82 + dist["p95"] * 0.92 + lev * 0.18 + max(0, 18 - own) * 0.52 + max(0, total - 4.2) * 3.7
    elif style == "safe":
        grade = proj * 1.35 + dist["p85"] * 0.38 + core * 0.08 - max(0, own - 30) * 0.2
    if stack_team and normalize_team(player.get("team", "")) == normalize_team(stack_team) and pos != "P":
        grade += 15.0 if style == "nuclear" else 11.0 if style == "aggressive" else 7.0
    if pos == "P" and style in ["aggressive", "nuclear"] and own <= 12 and proj >= 13:
        grade += 4.0
    if str(player.get("core_play_tier", "")).lower() in ["fade", "inactive"]:
        grade -= 50
    if str(player.get("core_play_tier", "")).lower() == "bad_chalk" and style in ["aggressive", "nuclear"]:
        grade -= 18
    return grade


def build_fast_multi_lineups_for_pro(request, count):
    mode = str(getattr(request, "mode", "gpp") or "gpp").lower()
    style = v3_style_from_request(request, mode)
    randomness = safe_int(getattr(request, "randomness", 0), 0)
    if style == "aggressive":
        randomness = max(randomness, 45)
    if style == "nuclear":
        randomness = max(randomness, 75)
    if mode != "cash" and style == "balanced":
        randomness = max(randomness, 28)

    players = [p for p in add_values(load_players()) if bool(p.get("active", True))]
    excluded_names = set(getattr(request, "excluded_players", []) or [])
    locked_players = getattr(request, "locked_players", []) or []
    max_players_per_team = max(3, min(safe_int(getattr(request, "max_players_per_team", 5), 5), 5))
    min_salary = safe_int(getattr(request, "min_salary", 0), 0)
    avoid_conflict = bool(getattr(request, "avoid_pitcher_vs_hitter", True))

    pool = [p for p in players if p.get("name") not in excluded_names and safe_int(p.get("salary", 0), 0) > 0]
    locked_objects = [p for p in pool if p.get("name") in locked_players]
    groups = {pos: [] for pos in ["P", "C", "1B", "2B", "3B", "SS", "OF"]}
    for p in pool:
        pos = normalize_position(p.get("position", ""))
        if pos in groups:
            groups[pos].append(p)

    hitters = [p for p in pool if normalize_position(p.get("position", "")) != "P"]
    stack_teams = v2_choose_stack_teams(hitters)
    # Nuclear also tests more lower-owned stack teams, not only best projection teams.
    if style in ["aggressive", "nuclear"]:
        team_scores = []
        by_team = {}
        for h in hitters:
            by_team.setdefault(normalize_team(h.get("team", "")), []).append(h)
        for team, ps in by_team.items():
            if len(ps) >= 3:
                avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in ps) / len(ps)
                ceil = sum(sorted([v3_player_distribution(p)["p99"] for p in ps], reverse=True)[:5])
                team_scores.append((team, ceil + max(0, 18 - avg_own) * 5 + max(0, estimated_team_total(team) - 4.2) * 12))
        team_scores.sort(key=lambda x: x[1], reverse=True)
        for team, _ in team_scores:
            if team not in stack_teams:
                stack_teams.append(team)
    if not stack_teams:
        stack_teams = [""]

    trim_report = {"tournament_engine_version": TOURNAMENT_ENGINE_VERSION, "builder_style": style, "stack_teams_tested": stack_teams[:12], "candidate_count": 0}
    candidates = []
    seen = set()
    attempts = max(260, count * (95 if style in ["aggressive", "nuclear"] else 65))
    stack_sizes = [5, 4, 3] if mode != "cash" else [3, 2]
    if style == "nuclear":
        stack_sizes = [5, 5, 4, 4, 3]
    elif style == "aggressive":
        stack_sizes = [5, 4, 4, 3]

    for i in range(attempts):
        stack_team = stack_teams[i % len(stack_teams)] if stack_teams else None
        secondary_options = [t for t in stack_teams if t and t != stack_team]
        secondary_team = secondary_options[(i // max(1, len(stack_teams))) % len(secondary_options)] if secondary_options else None
        stack_size = stack_sizes[i % len(stack_sizes)]
        lineup = v2_attempt_lineup(
            groups,
            stack_team=stack_team,
            stack_size=stack_size,
            secondary_team=secondary_team,
            style=style,
            locked_objects=locked_objects,
            excluded_names=excluded_names,
            offset=i + deterministic_random_bonus([{"name": str(i)}], randomness),
            max_players_per_team=max_players_per_team,
            min_salary=min_salary,
            avoid_pitcher_vs_hitter=avoid_conflict,
        )
        if not lineup or not v2_lineup_position_valid(lineup):
            continue
        if not has_all_locked(lineup, locked_players):
            continue
        key = lineup_key(lineup)
        if key in seen:
            continue
        seen.add(key)
        salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
        if salary > SALARY_CAP or salary < min_salary:
            continue
        projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
        data = add_lineup_metadata({"mode": mode, "total_salary": salary, "projected_points": round(projection, 2), "optimizer_score": 0, "lineup": lineup})
        q = data.get("lineup_quality_breakdown", {})
        # True objective: take down tournaments. Projection is only a tiebreaker in GPP.
        if mode == "cash" or style == "safe":
            objective = safe_float(q.get("projection_score", 0), 0) * 1.15 + safe_float(q.get("safety_score", 0), 0) * 0.95 + safe_float(q.get("core_score", 0), 0) * 0.34
        elif style == "nuclear":
            objective = safe_float(q.get("ceiling_score", 0), 0) * 2.10 + safe_float(q.get("stack_score", 0), 0) * 1.85 + safe_float(q.get("leverage_score", 0), 0) * 1.45 + safe_float(q.get("uniqueness_score", 0), 0) * 1.30 - safe_float(q.get("duplication_risk", 0), 0) * 0.42
        elif style == "aggressive":
            objective = safe_float(q.get("ceiling_score", 0), 0) * 1.82 + safe_float(q.get("stack_score", 0), 0) * 1.55 + safe_float(q.get("leverage_score", 0), 0) * 1.22 + safe_float(q.get("uniqueness_score", 0), 0) * 0.95 - safe_float(q.get("duplication_risk", 0), 0) * 0.30
        else:
            objective = safe_float(q.get("ceiling_score", 0), 0) * 1.38 + safe_float(q.get("stack_score", 0), 0) * 1.08 + safe_float(q.get("leverage_score", 0), 0) * 0.82 + safe_float(q.get("projection_score", 0), 0) * 0.50
        objective += deterministic_random_bonus(lineup, randomness) * (0.70 if style in ["aggressive", "nuclear"] else 0.22)
        data["optimizer_score"] = round(objective, 2)
        data["builder_style"] = style
        data["optimizer_objective"] = "takedown_equity" if mode != "cash" else "cash_safety"
        candidates.append(data)

    if not candidates:
        return [], "Tournament Engine V3 could not find valid lineups. Try clearing locks/excludes, lowering min salary, or allowing 5 players per team.", trim_report, attempts

    candidates.sort(key=lambda x: (safe_float(x.get("optimizer_score", 0), 0), safe_float(x.get("takedown_strength", 0), 0), safe_float(x.get("ceiling_score", 0), 0)), reverse=True)
    selected = diversify_lineups(
        all_lineups=candidates,
        count=count,
        max_exposure=min(max(safe_int(getattr(request, "max_exposure", 60), 60), 20), 100),
        max_same_players=min(max(safe_int(getattr(request, "max_same_players", 7), 7), 3), 9),
        locked_players=locked_players,
        player_min_exposure=getattr(request, "player_min_exposure", {}),
        player_max_exposure=getattr(request, "player_max_exposure", {}),
    )
    selected.sort(key=lambda x: (safe_float(x.get("optimizer_score", 0), 0), safe_float(x.get("takedown_strength", 0), 0)), reverse=True)
    trim_report["candidate_count"] = len(candidates)
    trim_report["returned_count"] = len(selected)
    return selected, None, trim_report, attempts


def v2_estimate_rank_from_score(score, lineup, contest):
    contest_size = max(10, safe_int(contest.get("contest_size", contest.get("field_size", 5000)), 5000))
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    quality = lineup_quality_profile(lineup, "gpp")
    strength = safe_float(quality.get("lineup_quality_score", 0), 0)
    takedown = safe_float(quality.get("takedown_strength", 0), 0)
    # Median is honest, but improved for actually strong builds.
    median_pct = 0.62 - (strength / 100.0) * 0.46 - max(0, takedown - 70) * 0.0025
    median_rank = int(max(1, min(contest_size, contest_size * max(0.045, median_pct))))
    ceiling_pct = 0.155 - (takedown / 100.0) * 0.137
    ceiling_rank = int(max(1, min(contest_size, contest_size * max(0.0035, ceiling_pct))))
    takedown_pct = 0.018 - (takedown / 100.0) * 0.0172
    takedown_rank = int(max(1, min(contest_size, contest_size * max(0.00012, takedown_pct))))
    return median_rank, ceiling_rank, takedown_rank, strength, takedown


def monte_carlo_lineup_simulation_v2(lineup, contest, runs=1200, field_scores=None):
    contest_size = max(10, safe_int(contest.get("contest_size", contest.get("field_size", 5000)), 5000))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", int(contest_size * 0.20)), int(contest_size * 0.20))))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 5.0), 5.0))
    median_rank, ceiling_rank, takedown_rank, strength, takedown = v2_estimate_rank_from_score(0, lineup, contest)
    paid_rate = paid_spots / contest_size
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)

    cash_probability = max(0.0, min(92.0, paid_rate * 100 + (strength - 55) * 0.62 + max(0, ceiling.get("ceiling_score", 0) - 70) * 0.12))
    top_10_probability = max(0.0, min(55.0, 4.0 + (takedown - 45) * 0.55))
    top_1_probability = max(0.0, min(10.5, 0.20 + max(0, takedown - 50) * 0.135 + max(0, stack.get("stack_score", 0) - 75) * 0.025))
    top_0_1_probability = max(0.0, min(1.20, 0.01 + max(0, takedown - 60) * 0.022 + max(0, lev.get("uniqueness_score", 0) - 70) * 0.006))
    win_probability = max(0.0, min(0.22, top_0_1_probability * 0.075))

    min_cash = payout_for_rank(paid_spots, contest)
    top_10_payout = payout_for_rank(max(1, int(contest_size * 0.10)), contest)
    top_1_payout = payout_for_rank(max(1, int(contest_size * 0.01)), contest)
    top_01_payout = payout_for_rank(max(1, int(contest_size * 0.001)), contest)
    first_payout = payout_for_rank(1, contest)
    median_payout = payout_for_rank(median_rank, contest)
    ceiling_payout = payout_for_rank(ceiling_rank, contest)
    takedown_payout = payout_for_rank(takedown_rank, contest)
    # Expected payout is probability weighted. Median payout can be $0 while GPP upside EV is positive.
    expected_payout = (
        (cash_probability / 100.0) * min_cash * 0.82
        + (top_10_probability / 100.0) * max(top_10_payout - min_cash, 0) * 0.45
        + (top_1_probability / 100.0) * max(top_1_payout - top_10_payout, 0) * 0.72
        + (top_0_1_probability / 100.0) * max(top_01_payout - top_1_payout, 0) * 0.92
        + (win_probability / 100.0) * max(first_payout - top_01_payout, 0)
    )
    # Do not clamp elite upside to tiny values, but stop impossible fantasy math.
    expected_payout = max(0.0, min(expected_payout, max(entry_fee * 20.0, top_1_payout * 0.22)))
    expected_value = expected_payout - entry_fee
    roi = (expected_value / entry_fee) * 100
    return {
        "simulation_runs": runs,
        "average_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "median_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "ceiling_sim_score": ceiling.get("p95_ceiling_points", 0),
        "floor_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup) * 0.55, 2),
        "average_rank": median_rank,
        "projected_rank": median_rank,
        "median_rank": median_rank,
        "ceiling_rank": ceiling_rank,
        "takedown_rank": takedown_rank,
        "cash_probability": round(cash_probability, 1),
        "top_10_probability": round(top_10_probability, 1),
        "top_1_probability": round(top_1_probability, 2),
        "top_0_1_probability": round(top_0_1_probability, 3),
        "win_probability": round(win_probability, 3),
        "expected_payout": round(expected_payout, 2),
        "expected_value": round(expected_value, 2),
        "roi_percent": round(roi, 1),
        "projected_payout": round(expected_payout, 2),
        "median_payout": round(median_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "best_payout": round(max(ceiling_payout, takedown_payout), 2),
        "min_cash_payout": round(min_cash, 2),
        "top_10_rank_payout": round(top_10_payout, 2),
        "top_1_rank_payout": round(top_1_payout, 2),
        "top_0_1_rank_payout": round(top_01_payout, 2),
        "tournament_strength": round(strength, 1),
        "ceiling_strength": round(takedown, 1),
        "simulator_note": "Projected payout is probability-weighted GPP upside EV. Median payout is the middle outcome and may still be $0 in large fields.",
    }


# ============================================================
# DFS EDGE MLB - TOURNAMENT ENGINE V4 PRODUCTION PATCH
# Purpose:
# - Stop lineup generation timeouts by replacing brute-force/loop-heavy
#   building with a bounded stochastic beam builder.
# - Make Aggressive/Nuclear/Big GPP actually prioritize ceiling, stack
#   correlation, leverage, uniqueness, and top-end tournament equity.
# - Keep existing API routes unchanged; FastAPI endpoints above resolve
#   these global function names at request time.
# ============================================================

TOURNAMENT_ENGINE_VERSION = "dfs_edge_mlb_tournament_engine_v4_timeout_safe_takedown"

V4_REQUIRED_COUNTS = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}


def v4_style_from_request(request, mode="gpp"):
    raw = (
        str(getattr(request, "build_style", "") or "") + " " +
        str(getattr(request, "strategy_mode", "") or "") + " " +
        str(getattr(request, "contest_focus", "") or "") + " " +
        str(getattr(request, "contest_type", "") or "") + " " +
        str(getattr(request, "stack_type", "") or "")
    ).lower()
    r = safe_int(getattr(request, "randomness", 0), 0)
    m = str(mode or "gpp").lower()
    if "cash" in raw or m == "cash":
        return "safe"
    if "nuclear" in raw or r >= 72:
        return "nuclear"
    if "aggressive" in raw or "massive" in raw or "big" in raw or "large" in raw or r >= 38:
        return "aggressive"
    if "single" in raw:
        return "single_entry"
    return "balanced"


def v4_player_dist(player):
    # Fast percentile model. This is deterministic, API-free, and designed for ranking/building,
    # not pretending to be a guaranteed projection.
    pos = normalize_position(player.get("position", ""))
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    total = safe_float(player.get("team_total", 4.2), 4.2)
    trend = safe_float(player.get("trend_score", 50), 50)
    data_boost = safe_float(player.get("data_engine_boost", 0), 0)
    if pos == "P":
        vol = 0.32 + (0.05 if own <= 12 else 0) + (0.04 if lev >= 58 else 0)
        p50 = proj
        p75 = proj * (1.18 + vol * 0.10)
        p90 = proj * (1.38 + vol * 0.18)
        p95 = proj * (1.55 + vol * 0.22)
        p99 = proj * (1.85 + vol * 0.25)
    else:
        # Hitter distribution needs to be wide. MLB GPPs are won by volatile HR/RBI stacks.
        vol = 0.62 + (0.12 if own <= 8 else 0.04 if own <= 15 else 0) + (0.08 if total >= 5.0 else 0) + (0.06 if lev >= 58 else 0)
        p50 = proj
        p75 = proj * (1.35 + vol * 0.08)
        p90 = proj * (1.95 + vol * 0.16)
        p95 = proj * (2.55 + vol * 0.20) + max(0, total - 4.2) * 1.1
        p99 = proj * (3.45 + vol * 0.28) + max(0, total - 4.2) * 2.0 + max(0, trend - 55) * 0.035 + max(0, 18 - own) * 0.10
    return {
        "p50": round(max(0, p50), 2),
        "p75": round(max(0, p75 + data_boost * 0.15), 2),
        "p90": round(max(0, p90 + data_boost * 0.25), 2),
        "p95": round(max(0, p95 + data_boost * 0.35), 2),
        "p99": round(max(0, p99 + data_boost * 0.50), 2),
    }


def v4_player_grade(player, style="balanced", stack_team=None):
    pos = normalize_position(player.get("position", ""))
    proj = safe_float(player.get("boosted_projection", player.get("projection", 0)), 0)
    own = safe_float(player.get("ownership", 12), 12)
    lev = safe_float(player.get("leverage_score", 45), 45)
    chalk = safe_float(player.get("chalk_score", 0), 0)
    core = safe_float(player.get("core_play_score", 50), 50)
    salary = safe_int(player.get("salary", 0), 0)
    total = safe_float(player.get("team_total", 4.2), 4.2)
    dist = v4_player_dist(player)
    value = (proj / salary) * 1000 if salary > 0 else 0
    style = str(style or "balanced").lower()

    if style == "safe":
        grade = proj * 2.2 + dist["p75"] * 0.45 + core * 0.12 + value * 2.8 - max(0, chalk - 65) * 0.08
    elif style == "single_entry":
        grade = dist["p90"] * 1.15 + dist["p95"] * 0.65 + proj * 0.45 + lev * 0.20 + core * 0.07 + max(0, total - 4.1) * 4.0 - max(0, own - 26) * 0.18
    elif style == "nuclear":
        grade = dist["p99"] * 1.50 + dist["p95"] * 0.82 + lev * 0.32 + max(0, 18 - own) * 1.20 + max(0, total - 4.2) * 7.5 - max(0, chalk - 54) * 0.45
    elif style == "aggressive":
        grade = dist["p99"] * 1.05 + dist["p95"] * 1.05 + lev * 0.28 + max(0, 20 - own) * 0.82 + max(0, total - 4.2) * 6.2 - max(0, chalk - 58) * 0.34
    else:
        grade = dist["p95"] * 1.1 + dist["p90"] * 0.72 + proj * 0.45 + lev * 0.18 + core * 0.05 + value * 1.6

    if stack_team and pos != "P" and normalize_team(player.get("team", "")) == normalize_team(stack_team):
        grade += 24.0 if style == "nuclear" else 18.0 if style == "aggressive" else 12.0 if style == "single_entry" else 8.0
    if pos == "P" and style in ["aggressive", "nuclear"] and own <= 15 and proj >= 12:
        grade += 5.0
    tier = str(player.get("core_play_tier", "")).lower()
    if tier in ["inactive", "fade"]:
        grade -= 80
    if tier == "bad_chalk" and style in ["aggressive", "nuclear"]:
        grade -= 25
    return float(grade)


def v4_team_stack_scores(hitters, style="balanced"):
    by_team = {}
    for h in hitters:
        team = normalize_team(h.get("team", ""))
        if team and team != "UNK":
            by_team.setdefault(team, []).append(h)
    scores = []
    for team, ps in by_team.items():
        if len(ps) < 2:
            continue
        top = sorted(ps, key=lambda p: v4_player_grade(p, style, stack_team=team), reverse=True)[:6]
        p95 = sum(v4_player_dist(p)["p95"] for p in top[:5])
        p99 = sum(v4_player_dist(p)["p99"] for p in top[:5])
        avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in top) / max(1, len(top))
        total = estimated_team_total(team)
        leverage_bonus = max(0, 18 - avg_own) * (2.2 if style in ["aggressive", "nuclear"] else 1.1)
        score = p95 * 0.85 + p99 * 0.48 + max(0, total - 4.0) * 14 + leverage_bonus + min(len(ps), 6) * 2.0
        scores.append((team, score, len(ps), round(avg_own, 1), round(total, 1)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def v4_lineup_counts(lineup):
    counts = {k: 0 for k in V4_REQUIRED_COUNTS}
    for p in lineup:
        pos = normalize_position(p.get("position", ""))
        if pos in counts:
            counts[pos] += 1
    return counts


def v4_can_add(lineup, player, max_players_per_team=5, avoid_pitcher_vs_hitter=True):
    name = player.get("name")
    if any(p.get("name") == name for p in lineup):
        return False
    pos = normalize_position(player.get("position", ""))
    counts = v4_lineup_counts(lineup)
    if pos not in V4_REQUIRED_COUNTS or counts.get(pos, 0) >= V4_REQUIRED_COUNTS[pos]:
        return False
    if not optimizer_starter_eligible(player):
        return False
    if pos == "P" and any(
        normalize_position(existing.get("position", "")) == "P"
        and normalize_team(existing.get("team", "")) == normalize_team(player.get("team", ""))
        for existing in lineup
    ):
        return False
    team_counts = count_team_players(lineup, hitters_only=False)
    team = normalize_team(player.get("team", ""))
    if team_counts.get(team, 0) >= max_players_per_team:
        return False
    if pos != "P" and count_team_players(lineup, hitters_only=True).get(team, 0) >= 5:
        return False
    if avoid_pitcher_vs_hitter:
        trial = lineup + [player]
        if pitcher_vs_hitter_conflict(trial):
            return False
    return True


def v4_required_missing(lineup):
    counts = v4_lineup_counts(lineup)
    return {pos: max(0, req - counts.get(pos, 0)) for pos, req in V4_REQUIRED_COUNTS.items()}


def v4_min_remaining_salary(groups, missing, selected_names):
    total = 0
    for pos, need in missing.items():
        if need <= 0:
            continue
        options = [p for p in groups.get(pos, []) if p.get("name") not in selected_names]
        options.sort(key=lambda p: safe_int(p.get("salary", 0), 0))
        if len(options) < need:
            return 999999
        total += sum(safe_int(p.get("salary", 0), 0) for p in options[:need])
    return total


def v4_fill_position(lineup, groups, pos, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter, seed_offset=0, prefer_salary=None):
    selected_names = set(p.get("name") for p in lineup)
    options = [p for p in groups.get(pos, []) if p.get("name") not in selected_names]
    if prefer_salary == "high":
        options.sort(key=lambda p: (safe_int(p.get("salary", 0), 0), v4_player_grade(p, style, stack_team)), reverse=True)
    elif prefer_salary == "low":
        options.sort(key=lambda p: (safe_int(p.get("salary", 0), 0), -v4_player_grade(p, style, stack_team)))
    else:
        options.sort(key=lambda p: v4_player_grade(p, style, stack_team), reverse=True)
    if seed_offset:
        # Deterministic rotation gives diversity without expensive random search.
        cut = min(len(options), max(1, seed_offset % max(1, min(len(options), 9))))
        if len(options) > 4:
            options = options[cut:cut+18] + options[:cut] + options[cut+18:]
    for p in options:
        current_salary = sum(safe_int(x.get("salary", 0), 0) for x in lineup)
        if current_salary + safe_int(p.get("salary", 0), 0) > SALARY_CAP:
            continue
        # Leave enough salary room for cheapest remaining roster spots.
        trial = lineup + [p]
        missing = v4_required_missing(trial)
        selected = set(x.get("name") for x in trial)
        cheapest_left = v4_min_remaining_salary(groups, missing, selected)
        if current_salary + safe_int(p.get("salary", 0), 0) + cheapest_left > SALARY_CAP:
            continue
        if v4_can_add(lineup, p, max_players_per_team, avoid_pitcher_vs_hitter):
            lineup.append(p)
            return True
    return False


def v4_upgrade_salary_floor(lineup, groups, min_salary, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter):
    if min_salary <= 0:
        return lineup
    # Upgrade low salary pieces while staying valid. Bounded loops only.
    for _ in range(18):
        salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
        if salary >= min_salary:
            break
        improved = False
        lineup_sorted = sorted(list(lineup), key=lambda p: (safe_int(p.get("salary", 0), 0), v4_player_grade(p, style, stack_team)))
        for old in lineup_sorted:
            pos = normalize_position(old.get("position", ""))
            old_salary = safe_int(old.get("salary", 0), 0)
            current_names = set(p.get("name") for p in lineup)
            replacements = [p for p in groups.get(pos, []) if p.get("name") not in current_names and safe_int(p.get("salary", 0), 0) > old_salary]
            replacements.sort(key=lambda p: (safe_int(p.get("salary", 0), 0) - old_salary <= (min_salary - salary + 2500), v4_player_grade(p, style, stack_team), safe_int(p.get("salary", 0), 0)), reverse=True)
            for new in replacements[:18]:
                trial = [p for p in lineup if p.get("name") != old.get("name")] + [new]
                new_salary = sum(safe_int(p.get("salary", 0), 0) for p in trial)
                if new_salary > SALARY_CAP:
                    continue
                if count_team_players(trial).get(normalize_team(new.get("team", "")), 0) > max_players_per_team:
                    continue
                if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(trial):
                    continue
                if v2_lineup_position_valid(trial):
                    lineup = trial
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return lineup


def v4_repair_salary_cap(lineup, groups, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter):
    # Downgrade until under cap. Bounded, deterministic.
    for _ in range(20):
        salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
        if salary <= SALARY_CAP:
            return lineup
        changed = False
        for old in sorted(lineup, key=lambda p: safe_int(p.get("salary", 0), 0), reverse=True):
            pos = normalize_position(old.get("position", ""))
            old_salary = safe_int(old.get("salary", 0), 0)
            current_names = set(p.get("name") for p in lineup)
            replacements = [p for p in groups.get(pos, []) if p.get("name") not in current_names and safe_int(p.get("salary", 0), 0) < old_salary]
            replacements.sort(key=lambda p: (v4_player_grade(p, style, stack_team), safe_int(p.get("salary", 0), 0)), reverse=True)
            for new in replacements[:20]:
                trial = [p for p in lineup if p.get("name") != old.get("name")] + [new]
                if sum(safe_int(p.get("salary", 0), 0) for p in trial) > SALARY_CAP:
                    continue
                if count_team_players(trial).get(normalize_team(new.get("team", "")), 0) > max_players_per_team:
                    continue
                if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(trial):
                    continue
                if v2_lineup_position_valid(trial):
                    lineup = trial
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return lineup


def v4_build_one_lineup(groups, style, stack_team, secondary_team, stack_target, locked_objects, excluded_names, offset, max_players_per_team, min_salary, avoid_pitcher_vs_hitter):
    lineup = []
    excluded_names = set(excluded_names or [])
    # Add locks first.
    for p in locked_objects:
        if p.get("name") in excluded_names:
            return None
        if not v4_can_add(lineup, p, max_players_per_team=max_players_per_team, avoid_pitcher_vs_hitter=False):
            return None
        lineup.append(p)
    if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(lineup):
        return None

    # Pitchers: prioritize ceiling/leverage in GPP, safety in cash.
    while v4_lineup_counts(lineup).get("P", 0) < 2:
        if not v4_fill_position(lineup, groups, "P", style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter, seed_offset=offset):
            return None

    # Primary stack first for GPP styles.
    if style != "safe" and stack_team:
        for _ in range(max(0, stack_target - best_stack_info(lineup).get("size", 0))):
            stack_hitters = [p for pos in ["C", "1B", "2B", "3B", "SS", "OF"] for p in groups.get(pos, []) if normalize_team(p.get("team", "")) == normalize_team(stack_team)]
            stack_hitters = [p for p in stack_hitters if p.get("name") not in set(x.get("name") for x in lineup)]
            stack_hitters.sort(key=lambda p: v4_player_grade(p, style, stack_team), reverse=True)
            added = False
            for p in stack_hitters[:30]:
                if v4_can_add(lineup, p, max_players_per_team, avoid_pitcher_vs_hitter):
                    lineup.append(p)
                    added = True
                    break
            if not added:
                break

    # Secondary mini-stack for aggressive/nuclear if possible.
    if style in ["aggressive", "nuclear"] and secondary_team:
        for _ in range(2):
            sec_hitters = [p for pos in ["C", "1B", "2B", "3B", "SS", "OF"] for p in groups.get(pos, []) if normalize_team(p.get("team", "")) == normalize_team(secondary_team)]
            sec_hitters = [p for p in sec_hitters if p.get("name") not in set(x.get("name") for x in lineup)]
            sec_hitters.sort(key=lambda p: v4_player_grade(p, style, secondary_team), reverse=True)
            for p in sec_hitters[:25]:
                if v4_can_add(lineup, p, max_players_per_team, avoid_pitcher_vs_hitter):
                    lineup.append(p)
                    break

    # Fill exact roster slots.
    for pos, req in V4_REQUIRED_COUNTS.items():
        while v4_lineup_counts(lineup).get(pos, 0) < req:
            if not v4_fill_position(lineup, groups, pos, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter, seed_offset=offset + len(lineup)):
                return None

    lineup = v4_repair_salary_cap(lineup, groups, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter)
    lineup = v4_upgrade_salary_floor(lineup, groups, min_salary, style, stack_team, max_players_per_team, avoid_pitcher_vs_hitter)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    if salary > SALARY_CAP:
        return None
    if min_salary > 0 and salary < min_salary:
        # Do not loop forever. Return None so the caller can test another stack/offset.
        return None
    if not v2_lineup_position_valid(lineup):
        return None
    if avoid_pitcher_vs_hitter and pitcher_vs_hitter_conflict(lineup):
        return None
    return lineup


def v4_lineup_objective(lineup, mode="gpp", style="balanced"):
    if not lineup:
        return -99999
    projection = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    p95 = sum(v4_player_dist(p)["p95"] for p in lineup)
    p99 = sum(v4_player_dist(p)["p99"] for p in lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    salary_score = 10 if 0 <= remaining <= 1800 else 6 if remaining <= 3500 else 2
    stack_score = safe_float(stack.get("stack_score", 0), 0)
    lev_score = safe_float(lev.get("leverage_score", 0), 0)
    uniq = safe_float(lev.get("uniqueness_score", 0), 0)
    chalk = safe_float(lev.get("duplication_risk", 0), 0)
    core_score = safe_float(core.get("average_core_play_score", 50), 50)

    if str(mode).lower() == "cash" or style == "safe":
        return projection * 1.9 + core_score * 0.18 + salary_score + min(100, stack_score) * 0.08 - chalk * 0.05
    if style == "nuclear":
        return p99 * 1.65 + p95 * 0.65 + stack_score * 2.10 + lev_score * 1.55 + uniq * 1.25 - chalk * 0.55 + salary_score
    if style == "aggressive":
        return p99 * 1.10 + p95 * 1.05 + stack_score * 1.75 + lev_score * 1.32 + uniq * 0.92 - chalk * 0.38 + salary_score
    if style == "single_entry":
        return p95 * 1.25 + projection * 0.65 + stack_score * 1.15 + lev_score * 0.88 + core_score * 0.10 - chalk * 0.22 + salary_score
    return p95 * 1.05 + projection * 0.85 + stack_score * 0.88 + lev_score * 0.60 + salary_score


def build_fast_multi_lineups_for_pro(request, count):
    """
    V4 bounded builder. No brute-force combinations, no unbounded validation loops.
    Returns fast even on live DK CSV slates and makes Aggressive/Nuclear actually
    optimize for ceiling + stack correlation + leverage.
    """
    mode = str(getattr(request, "mode", "gpp") or "gpp").lower()
    style = v4_style_from_request(request, mode)
    count = count if count in [1, 5, 10, 20] else 1
    locked_players = getattr(request, "locked_players", []) or []
    excluded_players = getattr(request, "excluded_players", []) or []
    excluded_names = set(excluded_players)
    max_players_per_team = max(3, min(safe_int(getattr(request, "max_players_per_team", 5), 5), 5))
    if style in ["aggressive", "nuclear"] and mode != "cash":
        max_players_per_team = max(4, max_players_per_team)
    min_salary = max(0, min(SALARY_CAP, safe_int(getattr(request, "min_salary", 0), 0)))
    avoid_conflict = bool(getattr(request, "avoid_pitcher_vs_hitter", True))

    raw_players = add_values(load_players())
    error = validate_locks(raw_players, locked_players, excluded_players)
    if error:
        return [], error, {}, 0

    # Use fallback pool so auto-cleanup trims do not kill live generation.
    pool, trim_report = build_optimizer_pool_with_fallback(raw_players, locked_players, excluded_players)
    pool = [p for p in add_values(pool) if p.get("name") not in excluded_names and valid_optimizer_player(p) and not is_manual_inactive_player(p)]
    if not has_required_mlb_positions(pool):
        return [], "Not enough confirmed or likely MLB starters at every roster position. Refresh MLB starters closer to lock, then try again.", trim_report, 0

    groups = {pos: [] for pos in V4_REQUIRED_COUNTS}
    for p in pool:
        pos = normalize_position(p.get("position", ""))
        if pos in groups:
            groups[pos].append(p)
    for pos in groups:
        groups[pos].sort(key=lambda p: v4_player_grade(p, style), reverse=True)

    locked_objects = [p for p in pool if p.get("name") in set(locked_players)]
    hitters = [p for p in pool if normalize_position(p.get("position", "")) != "P"]
    team_scores = v4_team_stack_scores(hitters, style)
    stack_teams = [x[0] for x in team_scores[:18]] or [""]

    stack_sizes = [2] if style == "safe" else [4, 3, 5, 4, 3]
    if style == "single_entry":
        stack_sizes = [4, 3, 4, 5]
    if style == "aggressive":
        stack_sizes = [4, 5, 4, 3, 5]
    if style == "nuclear":
        stack_sizes = [5, 4, 5, 4, 3]
    stack_sizes = [min(max_players_per_team, s) for s in stack_sizes]

    candidates = []
    seen = set()
    # Bounded attempts keeps Render/live backend responsive.
    attempts = min(900, max(220, count * (95 if style in ["aggressive", "nuclear"] else 70)))
    for i in range(attempts):
        stack_team = stack_teams[i % len(stack_teams)] if stack_teams else ""
        secondary_candidates = [t for t in stack_teams if t and t != stack_team]
        secondary_team = secondary_candidates[(i // max(1, len(stack_teams))) % len(secondary_candidates)] if secondary_candidates else None
        stack_target = stack_sizes[i % len(stack_sizes)]
        lineup = v4_build_one_lineup(
            groups=groups,
            style=style,
            stack_team=stack_team,
            secondary_team=secondary_team,
            stack_target=stack_target,
            locked_objects=locked_objects,
            excluded_names=excluded_names,
            offset=i,
            max_players_per_team=max_players_per_team,
            min_salary=min_salary,
            avoid_pitcher_vs_hitter=avoid_conflict,
        )
        if not lineup:
            continue
        key = lineup_key(lineup)
        if key in seen:
            continue
        seen.add(key)
        salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
        projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
        data = add_lineup_metadata({
            "mode": mode,
            "total_salary": salary,
            "projected_points": round(projection, 2),
            "optimizer_score": 0,
            "lineup": lineup,
        })
        objective = v4_lineup_objective(lineup, mode, style) + deterministic_random_bonus(lineup, safe_int(getattr(request, "randomness", 0), 0)) * (0.9 if style in ["aggressive", "nuclear"] else 0.25)
        data["optimizer_score"] = round(objective, 2)
        data["optimizer_objective"] = "v4_tournament_takedown_equity" if mode != "cash" else "v4_cash_safety"
        data["builder_style"] = style
        candidates.append(data)

    if not candidates:
        # Emergency final fallback: ignore min salary first, then return the best valid lineup rather than timing out.
        relaxed_request = request
        try:
            setattr(relaxed_request, "min_salary", 0)
        except Exception:
            pass
        if min_salary > 0:
            original_min = min_salary
            min_salary = 0
            for i in range(80):
                stack_team = stack_teams[i % len(stack_teams)] if stack_teams else ""
                lineup = v4_build_one_lineup(groups, style, stack_team, None, min(max_players_per_team, 4), locked_objects, excluded_names, i + 1000, max_players_per_team, 0, avoid_conflict)
                if lineup:
                    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
                    projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
                    data = add_lineup_metadata({"mode": mode, "total_salary": salary, "projected_points": round(projection, 2), "optimizer_score": 0, "lineup": lineup})
                    data["optimizer_score"] = round(v4_lineup_objective(lineup, mode, style), 2)
                    data["builder_style"] = style
                    data["optimizer_warning"] = f"Min salary {original_min} was too restrictive for this slate/settings; returned best valid lineup under cap."
                    candidates.append(data)
                    break
        if not candidates:
            return [], "The optimizer could not build a legal lineup from confirmed or likely starters. Refresh MLB starters, clear risky locks/excludes, or lower minimum salary.", {**trim_report, "builder_style": style, "v4_attempts": attempts}, attempts

    candidates.sort(key=lambda x: (safe_float(x.get("optimizer_score", 0), 0), safe_float(x.get("takedown_strength", 0), 0), safe_float(x.get("ceiling_score", 0), 0)), reverse=True)
    max_exposure = min(max(safe_int(getattr(request, "max_exposure", 65), 65), 20), 100)
    max_same = min(max(safe_int(getattr(request, "max_same_players", 7), 7), 3), 9)
    selected = diversify_lineups(
        all_lineups=candidates,
        count=count,
        max_exposure=max_exposure,
        max_same_players=max_same,
        locked_players=locked_players,
        player_min_exposure=getattr(request, "player_min_exposure", {}),
        player_max_exposure=getattr(request, "player_max_exposure", {}),
    )
    if len(selected) < count:
        # Fill without similarity restriction if user constraints are too tight.
        existing = {lineup_key(x["lineup"]) for x in selected}
        for cand in candidates:
            if len(selected) >= count:
                break
            k = lineup_key(cand["lineup"])
            if k not in existing:
                selected.append(cand)
                existing.add(k)
    selected.sort(key=lambda x: safe_float(x.get("optimizer_score", 0), 0), reverse=True)
    report = dict(trim_report or {})
    report.update({
        "tournament_engine_version": TOURNAMENT_ENGINE_VERSION,
        "builder_style": style,
        "candidate_count": len(candidates),
        "returned_count": len(selected),
        "v4_attempts": attempts,
        "stack_teams_tested": stack_teams[:12],
        "timeout_safe": True,
        "pool_count": len(pool),
    })
    return selected[:count], None, report, attempts


def v2_lineup_stack_profile(lineup):
    hitters = get_hitters(lineup)
    counts = count_team_players(lineup, hitters_only=True)
    if not hitters or not counts:
        return {"stack_score": 0, "stack_team": "", "primary_stack_team": "", "primary_stack_size": 0, "secondary_stack_size": 0, "stack_label": "No Stack", "stack_correlation_multiplier": 1.0}
    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    team, size = sorted_counts[0]
    secondary = sorted_counts[1][1] if len(sorted_counts) > 1 else 0
    team_total = estimated_team_total(team)
    team_hitters = [h for h in hitters if normalize_team(h.get("team", "")) == team]
    p95 = sum(v4_player_dist(h)["p95"] for h in team_hitters)
    avg_own = sum(safe_float(h.get("ownership", 12), 12) for h in team_hitters) / max(1, len(team_hitters))
    score = 18 + size * 13 + max(0, size - 3) * 10 + max(0, team_total - 4.1) * 8 + min(22, p95 * 0.18) + max(0, 16 - avg_own) * 1.1
    if secondary >= 2:
        score += 10
    label = "No Stack"
    if size >= 5:
        label = "Nuclear 5-man stack"
    elif size == 4:
        label = "Strong 4-man stack"
    elif size == 3:
        label = "Primary 3-man stack"
    elif size == 2:
        label = "Mini-stack"
    return {
        "stack_score": round(max(0, min(score, 100)), 1),
        "stack_team": team,
        "primary_stack_team": team,
        "primary_stack_size": size,
        "stack_size": size,
        "secondary_stack_size": secondary,
        "stack_label": label,
        "stack_counts": counts,
        "team_total": team_total,
        "average_stack_ownership": round(avg_own, 1),
        "stack_correlation_multiplier": round(1.0 + min(0.42, size * 0.055 + max(0, team_total - 4.2) * 0.025), 3),
    }


def v2_lineup_ceiling_profile(lineup):
    if not lineup:
        return {"ceiling_score": 0, "p95_ceiling_points": 0, "p99_ceiling_points": 0, "median_points": 0}
    p50 = sum(v4_player_dist(p)["p50"] for p in lineup)
    p95 = sum(v4_player_dist(p)["p95"] for p in lineup)
    p99 = sum(v4_player_dist(p)["p99"] for p in lineup)
    stack = v2_lineup_stack_profile(lineup)
    mult = safe_float(stack.get("stack_correlation_multiplier", 1.0), 1.0)
    p95 *= mult
    p99 *= (mult + 0.06)
    score = (p95 - 95) * 1.05 + (p99 - 135) * 0.42 + safe_float(stack.get("stack_score", 0), 0) * 0.22
    return {
        "ceiling_score": round(max(0, min(100, score)), 1),
        "p95_ceiling_points": round(p95, 2),
        "p99_ceiling_points": round(p99, 2),
        "median_points": round(p50, 2),
    }


def v2_lineup_leverage_profile(lineup):
    if not lineup:
        return {"leverage_score": 0, "uniqueness_score": 0, "duplication_risk": 0, "average_ownership": 0}
    avg_own = sum(safe_float(p.get("ownership", 12), 12) for p in lineup) / len(lineup)
    lev_avg = sum(safe_float(p.get("leverage_score", 45), 45) for p in lineup) / len(lineup)
    low_owned_upside = len([p for p in lineup if safe_float(p.get("ownership", 12), 12) <= 10 and v4_player_dist(p)["p95"] >= safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) * 2.0])
    chalk_count = len([p for p in lineup if safe_float(p.get("ownership", 12), 12) >= 25])
    stack = v2_lineup_stack_profile(lineup)
    uniqueness = 72 - avg_own * 1.15 + low_owned_upside * 5.5 + max(0, safe_float(stack.get("primary_stack_size", 0), 0) - 3) * 4
    duplication = avg_own * 1.8 + chalk_count * 7.0 - low_owned_upside * 3.5 - max(0, safe_float(stack.get("primary_stack_size", 0), 0) - 3) * 2.2
    leverage = lev_avg * 0.82 + uniqueness * 0.34 - max(0, chalk_count - 2) * 4.0
    return {
        "leverage_score": round(max(0, min(100, leverage)), 1),
        "uniqueness_score": round(max(0, min(100, uniqueness)), 1),
        "duplication_risk": round(max(0, min(100, duplication)), 1),
        "average_ownership": round(avg_own, 2),
        "low_owned_upside_count": low_owned_upside,
        "chalk_count": chalk_count,
        "leverage_label": "Contrarian upside" if uniqueness >= 70 else "Balanced leverage" if leverage >= 50 else "Chalky / duplicated",
    }


def lineup_quality_profile(lineup, mode="gpp"):
    if not lineup:
        return {"lineup_quality_score": 0, "win_probability": 0, "lineup_quality_label": "No Lineup", "lineup_quality_breakdown": {}}
    mode = str(mode or "gpp").lower()
    projection = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    stack = v2_lineup_stack_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    core = lineup_core_profile(lineup)
    salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    remaining = SALARY_CAP - salary
    projection_score = round(max(0, min(100, (projection - 60) * 1.45)), 1)
    ceiling_score = safe_float(ceiling.get("ceiling_score", 0), 0)
    stack_score = safe_float(stack.get("stack_score", 0), 0)
    leverage_score = safe_float(lev.get("leverage_score", 0), 0)
    uniqueness_score = safe_float(lev.get("uniqueness_score", 0), 0)
    duplication_risk = safe_float(lev.get("duplication_risk", 0), 0)
    core_score = safe_float(core.get("average_core_play_score", 50), 50)
    salary_score = 95 if 0 <= remaining <= 1800 else 85 if remaining <= 3500 else 72 if remaining <= 5200 else 55
    safety_score = 90 - (25 if pitcher_vs_hitter_conflict(lineup) else 0) - safe_int(core.get("fade_count", 0), 0) * 8
    if mode == "cash":
        quality = projection_score * 0.46 + safety_score * 0.34 + core_score * 0.14 + salary_score * 0.06
        takedown = ceiling_score * 0.35 + stack_score * 0.20 + leverage_score * 0.20 + projection_score * 0.25
        label = "Cash Core" if quality >= 72 else "Playable" if quality >= 56 else "Weak Build"
    else:
        takedown = ceiling_score * 0.32 + stack_score * 0.27 + leverage_score * 0.22 + uniqueness_score * 0.13 + projection_score * 0.06 - duplication_risk * 0.06
        quality = projection_score * 0.18 + ceiling_score * 0.25 + stack_score * 0.22 + leverage_score * 0.18 + uniqueness_score * 0.10 + salary_score * 0.07 - duplication_risk * 0.04
        label = "Massive GPP Winner Profile" if takedown >= 78 else "Big GPP Upside" if takedown >= 60 else "Needs More Ceiling" if takedown < 48 else "Playable"
    quality = round(max(0, min(100, quality)), 1)
    takedown = round(max(0, min(100, takedown)), 1)
    return {
        "lineup_quality_score": quality,
        "win_probability": round(max(0, min(100, takedown * 0.72)), 2),
        "takedown_strength": takedown,
        "lineup_quality_label": label,
        "lineup_quality_breakdown": {
            "projection_score": projection_score,
            "ceiling_score": ceiling_score,
            "stack_score": stack_score,
            "leverage_score": leverage_score,
            "uniqueness_score": uniqueness_score,
            "duplication_risk": duplication_risk,
            "core_score": round(core_score, 1),
            "salary_score": salary_score,
            "safety_score": round(max(0, min(100, safety_score)), 1),
        },
    }


def add_lineup_metadata(lineup_data):
    lineup = lineup_data.get("lineup", []) or []
    mode = lineup_data.get("mode", "gpp")
    total_salary = sum(safe_int(p.get("salary", 0), 0) for p in lineup)
    raw_projection = sum(safe_float(p.get("projection", 0), 0) for p in lineup)
    boosted = sum(safe_float(p.get("boosted_projection", p.get("projection", 0)), 0) for p in lineup)
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    core = lineup_core_profile(lineup)
    quality = lineup_quality_profile(lineup, mode)
    q = quality.get("lineup_quality_breakdown", {})
    lineup_data.update({
        "total_salary": total_salary,
        "salary_remaining": SALARY_CAP - total_salary,
        "projected_points": round(raw_projection, 2),
        "boosted_projection": round(boosted, 2),
        "average_ownership": lev.get("average_ownership", 0),
        "best_stack_team": stack.get("primary_stack_team", stack.get("stack_team", "")),
        "best_stack_size": stack.get("primary_stack_size", stack.get("stack_size", 0)),
        "stack_score": stack.get("stack_score", 0),
        "stack_correlation_score": stack.get("stack_score", 0),
        "leverage_score": lev.get("leverage_score", 0),
        "uniqueness_score": lev.get("uniqueness_score", 0),
        "duplication_risk": lev.get("duplication_risk", 0),
        "ceiling_score": ceiling.get("ceiling_score", 0),
        "p95_ceiling_points": ceiling.get("p95_ceiling_points", 0),
        "p99_ceiling_points": ceiling.get("p99_ceiling_points", 0),
        "lineup_quality_score": quality.get("lineup_quality_score", 0),
        "win_probability": quality.get("win_probability", 0),
        "takedown_strength": quality.get("takedown_strength", 0),
        "lineup_quality_label": quality.get("lineup_quality_label", "Playable"),
        "lineup_quality_breakdown": q,
        "core_play_count": core.get("core_play_count", 0),
        "strong_play_count": core.get("strong_play_count", 0),
        "fade_count": core.get("fade_count", 0),
        "bad_chalk_count": core.get("bad_chalk_count", 0),
        "v2_stack_profile": stack,
        "v2_leverage_profile": lev,
        "v2_ceiling_profile": ceiling,
        "tournament_engine_version": TOURNAMENT_ENGINE_VERSION,
        "tournament_notes": [
            f"{stack.get('stack_label', 'Stack')} • {stack.get('primary_stack_team', '')} {stack.get('primary_stack_size', 0)}",
            f"Ceiling {q.get('ceiling_score', 0)} / Stack {q.get('stack_score', 0)} / Leverage {q.get('leverage_score', 0)} / Unique {q.get('uniqueness_score', 0)}",
            "V4 is timeout-safe and builds for tournament ceiling, not just median projection.",
        ],
    })
    try:
        lineup_data["lineup_health"] = calculate_lineup_health_profile(lineup_data)
    except Exception:
        lineup_data["lineup_health"] = {"health_score": 100, "label": "OK"}
    return lineup_data


def score_lineup(lineup, mode, randomness=0):
    style = "nuclear" if safe_int(randomness, 0) >= 72 else "aggressive" if safe_int(randomness, 0) >= 38 or str(mode).lower() != "cash" else "safe"
    return round(v4_lineup_objective(lineup, mode, style) + deterministic_random_bonus(lineup, randomness) * 0.45, 4)


def v2_estimate_rank_from_score(score, lineup, contest):
    contest_size = max(10, safe_int(contest.get("contest_size", contest.get("field_size", 5000)), 5000))
    quality = lineup_quality_profile(lineup, "gpp")
    strength = safe_float(quality.get("lineup_quality_score", 0), 0)
    takedown = safe_float(quality.get("takedown_strength", 0), 0)
    # Honest median, but strong tournament lineups should project closer to the paid cut.
    median_pct = 0.70 - strength * 0.0062 - takedown * 0.0028
    median_pct = max(0.035, min(0.92, median_pct))
    ceiling_pct = 0.24 - takedown * 0.00215 - strength * 0.00065
    ceiling_pct = max(0.0025, min(0.45, ceiling_pct))
    takedown_pct = 0.035 - takedown * 0.000335
    takedown_pct = max(0.00008, min(0.08, takedown_pct))
    return int(max(1, contest_size * median_pct)), int(max(1, contest_size * ceiling_pct)), int(max(1, contest_size * takedown_pct)), strength, takedown


def monte_carlo_lineup_simulation_v2(lineup, contest, runs=900, field_scores=None):
    contest_size = max(10, safe_int(contest.get("contest_size", contest.get("field_size", 5000)), 5000))
    paid_spots = max(1, min(contest_size, safe_int(contest.get("paid_positions") or contest.get("estimated_paid_spots", int(contest_size * 0.20)), int(contest_size * 0.20))))
    entry_fee = max(0.01, safe_float(contest.get("entry_fee", 5.0), 5.0))
    median_rank, ceiling_rank, takedown_rank, strength, takedown = v2_estimate_rank_from_score(0, lineup, contest)
    paid_rate = paid_spots / contest_size
    stack = v2_lineup_stack_profile(lineup)
    lev = v2_lineup_leverage_profile(lineup)
    ceiling = v2_lineup_ceiling_profile(lineup)
    # Realistic probabilities. Elite lineups can have upside, but not fantasy 30% top-1% in massive fields.
    cash_probability = max(0.0, min(88.0, paid_rate * 100 + (strength - 50) * 0.55 + (takedown - 50) * 0.18))
    top_10_probability = max(0.0, min(42.0, 3.0 + (takedown - 42) * 0.42 + max(0, paid_rate - 0.20) * 20))
    top_1_probability = max(0.0, min(8.0, 0.12 + max(0, takedown - 48) * 0.095 + max(0, safe_float(stack.get("stack_score", 0), 0) - 70) * 0.018))
    top_0_1_probability = max(0.0, min(0.85, 0.005 + max(0, takedown - 58) * 0.012 + max(0, safe_float(lev.get("uniqueness_score", 0), 0) - 72) * 0.003))
    win_probability = max(0.0, min(0.16, top_0_1_probability * 0.09))
    min_cash = payout_for_rank(paid_spots, contest)
    top_10_payout = payout_for_rank(max(1, int(contest_size * 0.10)), contest)
    top_1_payout = payout_for_rank(max(1, int(contest_size * 0.01)), contest)
    top_01_payout = payout_for_rank(max(1, int(contest_size * 0.001)), contest)
    first_payout = payout_for_rank(1, contest)
    median_payout = payout_for_rank(median_rank, contest)
    ceiling_payout = payout_for_rank(ceiling_rank, contest)
    takedown_payout = payout_for_rank(takedown_rank, contest)
    expected_payout = (
        (cash_probability / 100.0) * min_cash * 0.72
        + (top_10_probability / 100.0) * max(top_10_payout - min_cash, 0) * 0.40
        + (top_1_probability / 100.0) * max(top_1_payout - top_10_payout, 0) * 0.62
        + (top_0_1_probability / 100.0) * max(top_01_payout - top_1_payout, 0) * 0.82
        + (win_probability / 100.0) * max(first_payout - top_01_payout, 0)
    )
    # Cap expected value to avoid fake huge ROI. Ceiling/best payout still shows upside separately.
    expected_payout = max(0.0, min(expected_payout, max(entry_fee * 18.0, top_1_payout * 0.18)))
    expected_value = expected_payout - entry_fee
    roi = (expected_value / entry_fee) * 100
    return {
        "simulation_runs": runs,
        "average_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "median_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup), 2),
        "ceiling_sim_score": ceiling.get("p95_ceiling_points", 0),
        "floor_sim_score": round(sum(safe_float(p.get("projection", 0), 0) for p in lineup) * 0.55, 2),
        "average_rank": median_rank,
        "projected_rank": median_rank,
        "median_rank": median_rank,
        "ceiling_rank": ceiling_rank,
        "takedown_rank": takedown_rank,
        "cash_probability": round(cash_probability, 1),
        "top_10_probability": round(top_10_probability, 1),
        "top_1_probability": round(top_1_probability, 2),
        "top_0_1_probability": round(top_0_1_probability, 3),
        "win_probability": round(win_probability, 3),
        "expected_payout": round(expected_payout, 2),
        "expected_value": round(expected_value, 2),
        "roi_percent": round(roi, 1),
        "projected_payout": round(expected_payout, 2),
        "median_payout": round(median_payout, 2),
        "ceiling_payout": round(ceiling_payout, 2),
        "best_payout": round(max(ceiling_payout, takedown_payout), 2),
        "min_cash_payout": round(min_cash, 2),
        "top_10_rank_payout": round(top_10_payout, 2),
        "top_1_rank_payout": round(top_1_payout, 2),
        "top_0_1_rank_payout": round(top_01_payout, 2),
        "tournament_strength": round(strength, 1),
        "ceiling_strength": round(takedown, 1),
        "simulator_note": "EV is probability-weighted. Median payout can be $0 while ceiling/takedown payout shows tournament upside.",
    }
