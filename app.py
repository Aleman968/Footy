
import os
import json
import re
import math
from datetime import datetime, timedelta

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://api.football-data-api.com"
APP_TIMEZONE = "Europe/Rome"


def load_api_key():
    try:
        key = str(st.secrets["FOOTYSTATS_API_KEY"]).strip()
        if key:
            return key
    except Exception:
        pass

    key = os.getenv("FOOTYSTATS_API_KEY", "").strip()
    if key:
        return key

    st.error("API key non trovata. Su Streamlit Cloud inserisci FOOTYSTATS_API_KEY nei Secrets.")
    st.stop()


def safe_float(value, default=0.0):
    try:
        if value in (None, "", "null"):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value in (None, "", "null"):
            return default
        return int(float(value))
    except Exception:
        return default


def format_dt_short(unix_ts):
    try:
        return datetime.fromtimestamp(int(unix_ts)).strftime("%d/%m %H:%M")
    except Exception:
        return "-"


def normalize_text(text):
    return " ".join(str(text or "").strip().lower().split())


def clean_league_name(name):
    name = str(name or "").strip()
    if not name:
        return "Campionato"
    return re.sub(r"\s*\((?:19|20)\d{2}(?:/?(?:19|20)\d{2})?\)\s*$", "", name).strip()


def build_pretty_league_name(country, league_name):
    country = str(country or "").strip()
    league_name = str(league_name or "").strip()
    if country and league_name:
        if country.lower() in league_name.lower():
            return clean_league_name(league_name)
        return clean_league_name(f"{country} - {league_name}")
    return clean_league_name(league_name or country or "Campionato")


def deep_find_first(obj, candidate_keys):
    if isinstance(obj, dict):
        for k in candidate_keys:
            if k in obj and obj[k] not in (None, "", [], {}):
                return obj[k]
        for v in obj.values():
            found = deep_find_first(v, candidate_keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = deep_find_first(item, candidate_keys)
            if found not in (None, "", [], {}):
                return found
    return None


def deep_collect_ids(obj):
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in {"id", "season_id", "competition_id", "league_id"}:
                val = safe_int(v, 0)
                if val:
                    found.add(val)
            found.update(deep_collect_ids(v))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found.update(deep_collect_ids(item))
    return found


def coerce_league_item(raw_item):
    if isinstance(raw_item, dict):
        return raw_item
    if isinstance(raw_item, (list, tuple)):
        merged = {}
        for part in raw_item:
            if isinstance(part, dict):
                for k, v in part.items():
                    if k not in merged or merged.get(k) in (None, "", [], {}):
                        merged[k] = v
        return merged
    return {}

@st.cache_data(ttl=43200)
def fetch_all_leagues_fallback():
    key = load_api_key()
    response = requests.get(
        f"{API_BASE}/league-list",
        params={"key": key},
        timeout=45,
    )
    if not response.ok:
        return {"leagues": [], "id_to_key": {}, "id_to_name": {}, "name_map": {}}

    payload = response.json()
    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raw_data = []

    leagues = []
    id_to_key = {}
    id_to_name = {}
    name_map = {}

    for idx, raw_item in enumerate(raw_data):
        item = coerce_league_item(raw_item)
        if not item:
            continue

        season_blob = deep_find_first(item, ["season"]) or {}
        if not isinstance(season_blob, dict):
            season_blob = {}

        season_id = safe_int(deep_find_first(item, ["season_id"]) or season_blob.get("id"), 0)
        item_id = safe_int(deep_find_first(item, ["id"]), 0)
        country = str(deep_find_first(item, ["country"]) or "").strip()
        league_name = str(
            deep_find_first(item, ["league_name"])
            or deep_find_first(item, ["english_name"])
            or deep_find_first(item, ["name_it"])
            or deep_find_first(item, ["name"])
            or ""
        ).strip()

        clean_name = build_pretty_league_name(country, league_name)
        canonical_key = f"league_{season_id or item_id or idx}"
        row = {
            "key": canonical_key,
            "season_id": season_id,
            "item_id": item_id,
            "name": clean_name,
            "country": country,
            "league_name": league_name,
        }
        leagues.append(row)

        for found_id in [season_id, item_id]:
            if found_id:
                id_to_key[found_id] = canonical_key
                id_to_name[found_id] = row["name"]

        for label in {row["name"], row["league_name"]}:
            label_norm = normalize_text(label)
            if label_norm:
                name_map.setdefault(label_norm, set()).add(canonical_key)

    leagues.sort(key=lambda x: x["name"])
    return {
        "leagues": leagues,
        "id_to_key": id_to_key,
        "id_to_name": id_to_name,
        "name_map": name_map,
    }



@st.cache_data(ttl=43200)
def fetch_chosen_leagues():
    key = load_api_key()
    response = requests.get(
        f"{API_BASE}/league-list",
        params={"key": key, "chosen_leagues_only": "true"},
        timeout=45,
    )

    if not response.ok:
        error_preview = response.text[:500] if response.text else "Nessun dettaglio disponibile"
        st.error(
            f"Errore FootyStats su league-list: HTTP {response.status_code}. "
            f"Risposta API: {error_preview}"
        )
        st.stop()

    payload = response.json()

    leagues = []
    id_to_key = {}
    id_to_name = {}
    name_map = {}

    raw_data = payload.get("data", [])
    if not isinstance(raw_data, list):
        raw_data = []

    for idx, raw_item in enumerate(raw_data):
        item = coerce_league_item(raw_item)
        if not item:
            continue

        season_blob = deep_find_first(item, ["season"]) or {}
        if not isinstance(season_blob, dict):
            season_blob = {}

        season_id = safe_int(deep_find_first(item, ["season_id"]) or season_blob.get("id"), 0)
        item_id = safe_int(deep_find_first(item, ["id"]), 0)
        extra_ids = sorted(deep_collect_ids(raw_item) | deep_collect_ids(item))

        country = str(deep_find_first(item, ["country"]) or "").strip()
        league_name = str(
            deep_find_first(item, ["league_name"])
            or deep_find_first(item, ["english_name"])
            or deep_find_first(item, ["name_it"])
            or deep_find_first(item, ["name"])
            or ""
        ).strip()

        clean_name = build_pretty_league_name(country, league_name)
        canonical_key = f"league_{season_id or item_id or idx}"
        row = {
            "key": canonical_key,
            "season_id": season_id,
            "item_id": item_id,
            "extra_ids": extra_ids,
            "name": clean_name,
            "country": country,
            "league_name": league_name,
        }
        leagues.append(row)

        ids_for_row = set(extra_ids)
        if season_id:
            ids_for_row.add(season_id)
        if item_id:
            ids_for_row.add(item_id)

        for found_id in ids_for_row:
            id_to_key[found_id] = canonical_key
            id_to_name[found_id] = row["name"]

        for label in {row["name"], row["league_name"]}:
            label_norm = normalize_text(label)
            if label_norm:
                name_map.setdefault(label_norm, set()).add(canonical_key)

    leagues.sort(key=lambda x: x["name"])
    return {
        "leagues": leagues,
        "id_to_key": id_to_key,
        "id_to_name": id_to_name,
        "name_map": name_map,
    }


def infer_name_from_match(match):
    for k in ["competition_name", "league_name", "league", "competition"]:
        val = str(match.get(k, "")).strip()
        if val and val not in ("0", "-1"):
            return clean_league_name(val)
    return "Campionato"


def resolve_match_league(match, chosen_lookup):
    comp_id = safe_int(match.get("competition_id"), 0)

    if comp_id and comp_id in chosen_lookup["id_to_key"]:
        key = chosen_lookup["id_to_key"][comp_id]
        name = chosen_lookup["id_to_name"].get(comp_id) or infer_name_from_match(match)
        return key, clean_league_name(name), comp_id

    for k in ["competition_name", "league_name", "league", "competition"]:
        val = normalize_text(match.get(k, ""))
        if val and val in chosen_lookup["name_map"]:
            key = sorted(chosen_lookup["name_map"][val])[0]
            chosen_row = next((x for x in chosen_lookup["leagues"] if x["key"] == key), None)
            return key, clean_league_name(chosen_row["name"] if chosen_row else infer_name_from_match(match)), safe_int((chosen_row or {}).get("season_id"), 0) or comp_id

    return f"unmatched_{comp_id or '0'}", clean_league_name(infer_name_from_match(match)), comp_id


def build_match_label(match):
    home = match.get("home_name", "Home")
    away = match.get("away_name", "Away")
    when = format_dt_short(match.get("date_unix"))
    return f"{when} | {home} vs {away}"


@st.cache_data(ttl=900)
def fetch_matches_14_days():
    key = load_api_key()
    chosen_lookup = fetch_chosen_leagues()
    collected = []
    base_day = datetime.now()

    for i in range(15):
        date_str = (base_day + timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            response = requests.get(
                f"{API_BASE}/todays-matches",
                params={"key": key, "date": date_str, "timezone": APP_TIMEZONE},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            matches = payload.get("data", [])
            if not isinstance(matches, list):
                matches = []

            for match in matches:
                league_key, league_name, season_id = resolve_match_league(match, chosen_lookup)
                match["_league_key"] = league_key
                match["_league_name"] = league_name
                match["_season_id"] = season_id
                match["_match_label"] = build_match_label(match)
                collected.append(match)
        except Exception:
            continue

    collected.sort(key=lambda m: safe_int(m.get("date_unix"), 0))
    return collected


def is_completed_match(match):
    status = str(match.get("status", "")).strip().lower()
    if status in {"incomplete", "scheduled", "postponed", "cancelled"}:
        return False
    if safe_int(match.get("date_unix"), 0) > int(datetime.now().timestamp()):
        return False
    hg = match.get("homeGoalCount")
    ag = match.get("awayGoalCount")
    return hg not in (None, "", "null") and ag not in (None, "", "null")


@st.cache_data(ttl=1800)
def fetch_league_recent_results(season_id):
    key = load_api_key()
    if not season_id:
        return []

    candidates = [
        (f"{API_BASE}/league-matches", {"key": key, "season_id": season_id}),
        (f"{API_BASE}/league-season", {"key": key, "season_id": season_id, "include": "matches"}),
    ]

    for url, params in candidates:
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            possible = data.get("matches", []) if isinstance(data, dict) else data
            if not isinstance(possible, list):
                continue
            parsed = [m for m in possible if isinstance(m, dict) and is_completed_match(m)]
            if parsed:
                parsed.sort(key=lambda x: safe_int(x.get("date_unix"), 0), reverse=True)
                return parsed
        except Exception:
            continue
    return []


def compute_recent_form(all_matches, team_id, venue, n=5):
    if not team_id:
        return {}

    filtered = []
    for m in all_matches:
        home_id = safe_int(m.get("homeID"), 0)
        away_id = safe_int(m.get("awayID"), 0)

        if venue == "home":
            if home_id != team_id:
                continue
            team_goals = safe_float(m.get("homeGoalCount"))
            opp_goals = safe_float(m.get("awayGoalCount"))
        elif venue == "away":
            if away_id != team_id:
                continue
            team_goals = safe_float(m.get("awayGoalCount"))
            opp_goals = safe_float(m.get("homeGoalCount"))
        else:
            continue

        total = team_goals + opp_goals
        filtered.append(
            {
                "team_goals": team_goals,
                "opp_goals": opp_goals,
                "over15": 1 if total >= 2 else 0,
                "under35": 1 if total <= 3 else 0,
            }
        )

    recent = filtered[:n]
    if not recent:
        return {}

    count = len(recent)
    btts_hits = sum(1 for x in recent if x["team_goals"] > 0 and x["opp_goals"] > 0)
    over25_hits = sum(1 for x in recent if (x["team_goals"] + x["opp_goals"]) >= 3)
    under45_hits = sum(1 for x in recent if (x["team_goals"] + x["opp_goals"]) <= 4)

    return {
        "count": count,
        "scored_avg": round(sum(x["team_goals"] for x in recent) / count, 2),
        "conceded_avg": round(sum(x["opp_goals"] for x in recent) / count, 2),
        "over15_rate": round(sum(x["over15"] for x in recent) / count, 2),
        "under35_rate": round(sum(x["under35"] for x in recent) / count, 2),
        "btts_rate": round(btts_hits / count, 2),
        "over25_rate": round(over25_hits / count, 2),
        "under45_rate": round(under45_hits / count, 2),
    }




@st.cache_data(ttl=1800)
def fetch_league_team_stats(season_id):
    key = load_api_key()
    if not season_id:
        return {}

    candidates = [
        (f"{API_BASE}/league-teams", {"key": key, "season_id": season_id, "include": "stats"}),
        (f"{API_BASE}/league-table", {"key": key, "season_id": season_id}),
    ]

    for url, params in candidates:
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            if not isinstance(data, list):
                continue

            teams = {}
            for idx_row, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    continue

                team_id = safe_int(item.get("id") or item.get("team_id"), 0)
                if not team_id:
                    continue

                stats = item.get("stats") or item.get("table") or item
                stats = stats if isinstance(stats, dict) else {}

                team_name = str(
                    item.get("name")
                    or item.get("team_name")
                    or stats.get("team_name")
                    or stats.get("name")
                    or f"Team {team_id}"
                ).strip()

                scored_home = safe_float(
                    stats.get("seasonScoredAVG_home")
                    or item.get("seasonScoredAVG_home")
                    or stats.get("scored_home")
                    or item.get("scored_home")
                )
                conceded_home = safe_float(
                    stats.get("seasonConcededAVG_home")
                    or item.get("seasonConcededAVG_home")
                    or stats.get("conceded_home")
                    or item.get("conceded_home")
                )
                scored_away = safe_float(
                    stats.get("seasonScoredAVG_away")
                    or item.get("seasonScoredAVG_away")
                    or stats.get("scored_away")
                    or item.get("scored_away")
                )
                conceded_away = safe_float(
                    stats.get("seasonConcededAVG_away")
                    or item.get("seasonConcededAVG_away")
                    or stats.get("conceded_away")
                    or item.get("conceded_away")
                )

                teams[team_id] = {
                    "team_name": team_name,
                    "position": safe_int(
                        item.get("position")
                        or item.get("rank")
                        or item.get("place")
                        or stats.get("position")
                        or stats.get("rank")
                        or idx_row,
                        idx_row,
                    ),
                    "played": safe_int(
                        item.get("played")
                        or item.get("matches")
                        or item.get("games_played")
                        or stats.get("played")
                        or stats.get("matches")
                        or stats.get("games_played"),
                        0,
                    ),
                    "points": safe_int(
                        item.get("points")
                        or item.get("pts")
                        or stats.get("points")
                        or stats.get("pts"),
                        0,
                    ),
                    "wins": safe_int(
                        item.get("wins")
                        or item.get("won")
                        or stats.get("wins")
                        or stats.get("won"),
                        0,
                    ),
                    "draws": safe_int(
                        item.get("draws")
                        or item.get("drawn")
                        or stats.get("draws")
                        or stats.get("drawn"),
                        0,
                    ),
                    "losses": safe_int(
                        item.get("losses")
                        or item.get("lost")
                        or stats.get("losses")
                        or stats.get("lost"),
                        0,
                    ),
                    "scored_home": scored_home,
                    "conceded_home": conceded_home,
                    "scored_away": scored_away,
                    "conceded_away": conceded_away,
                    "scored_average": round(((scored_home + scored_away) / 2), 2) if (scored_home or scored_away) else 0.0,
                    "conceded_average": round(((conceded_home + conceded_away) / 2), 2) if (conceded_home or conceded_away) else 0.0,
                }
            if teams:
                return teams
        except Exception:
            continue
    return {}




@st.cache_data(ttl=1800)
def fetch_league_standings(season_id):
    key = load_api_key()
    if not season_id:
        return []

    def normalize_table_rows(table_candidate):
        rows = []
        if isinstance(table_candidate, list):
            source_rows = table_candidate
        elif isinstance(table_candidate, dict):
            # Support {"table": [...]}, {"rows": [...]}, or nested stage/group dicts
            for k in ["table", "rows", "standings", "data"]:
                if isinstance(table_candidate.get(k), list):
                    source_rows = table_candidate.get(k)
                    break
            else:
                source_rows = []
                # some payloads group tables by round/group names
                for v in table_candidate.values():
                    if isinstance(v, list):
                        source_rows.extend(v)
                    elif isinstance(v, dict):
                        for kk in ["table", "rows", "standings", "data"]:
                            vv = v.get(kk)
                            if isinstance(vv, list):
                                source_rows.extend(vv)
        else:
            source_rows = []

        for idx_row, item in enumerate(source_rows, start=1):
            if not isinstance(item, dict):
                continue

            stats = item.get("table") or item.get("stats") or item

            row = {
                "Pos": safe_int(
                    item.get("position")
                    or item.get("rank")
                    or item.get("place")
                    or stats.get("position")
                    or stats.get("rank")
                    or stats.get("place"),
                    idx_row,
                ),
                "Squadra": str(
                    item.get("name")
                    or item.get("team_name")
                    or item.get("club_name")
                    or item.get("team")
                    or stats.get("team_name")
                    or stats.get("name")
                    or stats.get("club_name")
                    or stats.get("team")
                    or f"Team {idx_row}"
                ).strip(),
                "Pt": safe_int(
                    item.get("points")
                    or item.get("pts")
                    or item.get("point")
                    or stats.get("points")
                    or stats.get("pts")
                    or stats.get("point"),
                    0,
                ),
                "G": safe_int(
                    item.get("played")
                    or item.get("matches")
                    or item.get("games_played")
                    or item.get("mp")
                    or stats.get("played")
                    or stats.get("matches")
                    or stats.get("games_played")
                    or stats.get("mp"),
                    0,
                ),
                "V": safe_int(
                    item.get("wins")
                    or item.get("won")
                    or item.get("w")
                    or stats.get("wins")
                    or stats.get("won")
                    or stats.get("w"),
                    0,
                ),
                "N": safe_int(
                    item.get("draws")
                    or item.get("drawn")
                    or item.get("d")
                    or stats.get("draws")
                    or stats.get("drawn")
                    or stats.get("d"),
                    0,
                ),
                "P": safe_int(
                    item.get("losses")
                    or item.get("lost")
                    or item.get("l")
                    or stats.get("losses")
                    or stats.get("lost")
                    or stats.get("l"),
                    0,
                ),
            }
            if row["Squadra"]:
                rows.append(row)
        return rows

    urls = [
        (f"{API_BASE}/league-tables", {"key": key, "season_id": season_id}),
        (f"{API_BASE}/league-season", {"key": key, "season_id": season_id, "include": "table"}),
        (f"{API_BASE}/league-table", {"key": key, "season_id": season_id}),
        (f"{API_BASE}/league-teams", {"key": key, "season_id": season_id, "include": "table"}),
    ]

    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data")

            candidates = []

            # docs: league-tables returns league_table, all_matches_table_overall, specific_tables
            if isinstance(data, dict):
                for k in ["league_table", "all_matches_table_overall", "all_matches_table_home", "all_matches_table_away"]:
                    if k in data:
                        candidates.append(data.get(k))
                specific = data.get("specific_tables")
                if isinstance(specific, list):
                    for item in specific:
                        if isinstance(item, dict):
                            for kk in ["league_table", "table", "rows", "standings"]:
                                if kk in item:
                                    candidates.append(item.get(kk))
                        else:
                            candidates.append(item)
                candidates.append(data)

            elif isinstance(data, list):
                candidates.append(data)

            # deep fallbacks
            for key_name in ["league_table", "all_matches_table_overall", "specific_tables", "table", "standings", "league_table"]:
                found = deep_find_first(payload, [key_name])
                if found not in (None, "", [], {}):
                    candidates.append(found)

            for cand in candidates:
                rows = normalize_table_rows(cand)
                if rows:
                    rows.sort(key=lambda x: (x["Pos"] if x["Pos"] else 999, -x["Pt"], x["Squadra"]))
                    return rows
        except Exception:
            continue

    return []

    def extract_rows(payload):
        if not isinstance(payload, dict):
            return []

        candidates = [
            payload.get("data"),
            deep_find_first(payload, ["table"]),
            deep_find_first(payload, ["standings"]),
            deep_find_first(payload, ["league_table"]),
            deep_find_first(payload, ["classification"]),
        ]

        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                return candidate
            if isinstance(candidate, dict):
                for subkey in ["table", "standings", "rows", "data"]:
                    sub = candidate.get(subkey)
                    if isinstance(sub, list) and sub:
                        return sub
        return []

    urls = [
        (f"{API_BASE}/league-table", {"key": key, "season_id": season_id}),
        (f"{API_BASE}/league-season", {"key": key, "season_id": season_id, "include": "table"}),
        (f"{API_BASE}/league-teams", {"key": key, "season_id": season_id, "include": "table"}),
    ]

    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            data_rows = extract_rows(payload)
            if not isinstance(data_rows, list) or not data_rows:
                continue

            rows = []
            for idx_row, item in enumerate(data_rows, start=1):
                if not isinstance(item, dict):
                    continue

                stats = item.get("table") or item.get("stats") or item
                stats = stats if isinstance(stats, dict) else {}

                team_name = str(
                    item.get("name")
                    or item.get("team_name")
                    or stats.get("team_name")
                    or stats.get("name")
                    or item.get("club_name")
                    or stats.get("club_name")
                    or f"Team {idx_row}"
                ).strip()

                row = {
                    "Pos": safe_int(
                        item.get("position")
                        or item.get("rank")
                        or item.get("place")
                        or stats.get("position")
                        or stats.get("rank")
                        or stats.get("place"),
                        idx_row,
                    ),
                    "Squadra": team_name,
                    "Pt": safe_int(
                        item.get("points")
                        or item.get("pts")
                        or stats.get("points")
                        or stats.get("pts"),
                        0,
                    ),
                    "G": safe_int(
                        item.get("played")
                        or item.get("matches")
                        or item.get("games_played")
                        or item.get("mp")
                        or stats.get("played")
                        or stats.get("matches")
                        or stats.get("games_played")
                        or stats.get("mp"),
                        0,
                    ),
                    "V": safe_int(
                        item.get("wins")
                        or item.get("won")
                        or item.get("w")
                        or stats.get("wins")
                        or stats.get("won")
                        or stats.get("w"),
                        0,
                    ),
                    "N": safe_int(
                        item.get("draws")
                        or item.get("drawn")
                        or item.get("d")
                        or stats.get("draws")
                        or stats.get("drawn")
                        or stats.get("d"),
                        0,
                    ),
                    "P": safe_int(
                        item.get("losses")
                        or item.get("lost")
                        or item.get("l")
                        or stats.get("losses")
                        or stats.get("lost")
                        or stats.get("l"),
                        0,
                    ),
                }
                rows.append(row)

            rows = [r for r in rows if r["Squadra"]]
            if rows:
                rows.sort(key=lambda x: (x["Pos"] if x["Pos"] else 999, -x["Pt"], x["Squadra"]))
                return rows
        except Exception:
            continue

    return []

    try:
        response = requests.get(
            f"{API_BASE}/league-table",
            params={"key": key, "season_id": season_id},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])
        if not isinstance(data, list):
            return []

        rows = []
        for idx_row, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue

            stats = item.get("table") or item.get("stats") or item
            stats = stats if isinstance(stats, dict) else {}

            row = {
                "Pos": safe_int(
                    item.get("position")
                    or item.get("rank")
                    or item.get("place")
                    or stats.get("position")
                    or stats.get("rank"),
                    idx_row,
                ),
                "Squadra": str(
                    item.get("name")
                    or item.get("team_name")
                    or stats.get("team_name")
                    or stats.get("name")
                    or f"Team {idx_row}"
                ).strip(),
                "Pt": safe_int(
                    item.get("points")
                    or item.get("pts")
                    or stats.get("points")
                    or stats.get("pts"),
                    0,
                ),
                "G": safe_int(
                    item.get("played")
                    or item.get("matches")
                    or item.get("games_played")
                    or stats.get("played")
                    or stats.get("matches")
                    or stats.get("games_played"),
                    0,
                ),
                "V": safe_int(
                    item.get("wins")
                    or item.get("won")
                    or stats.get("wins")
                    or stats.get("won"),
                    0,
                ),
                "N": safe_int(
                    item.get("draws")
                    or item.get("drawn")
                    or stats.get("draws")
                    or stats.get("drawn"),
                    0,
                ),
                "P": safe_int(
                    item.get("losses")
                    or item.get("lost")
                    or stats.get("losses")
                    or stats.get("lost"),
                    0,
                ),
            }
            rows.append(row)

        rows.sort(key=lambda x: (x["Pos"] if x["Pos"] else 999, -x["Pt"], x["Squadra"]))
        return rows
    except Exception:
        return []


def extract_first_metric(match, candidate_keys, default=0.0):
    for key in candidate_keys:
        if key in match and match.get(key) not in (None, "", "null"):
            return safe_float(match.get(key), default)
    found = deep_find_first(match, candidate_keys)
    return safe_float(found, default)


def get_match_profile(match):
    over15 = extract_first_metric(match, ["o15_potential", "over15_potential"])
    over25 = extract_first_metric(match, ["o25_potential", "over25_potential"])
    under45 = extract_first_metric(match, ["u45_potential", "under45_potential"])
    over05_ht = extract_first_metric(match, ["o05HT_potential", "o05_ht_potential", "over05_ht_potential"])
    btts = extract_first_metric(match, ["btts_potential", "btts"])
    quota_gol = extract_first_metric(match, ["odds_btts_yes", "odds_ft_btts_yes", "btts_yes_odds"])
    quota_over25 = extract_first_metric(match, ["odds_ft_over25", "odds_over25"])

    quota_mg_25 = extract_first_metric(match, ["odds_multigol_2_5", "odds_mg_2_5", "odds_goals_2_5"])


    multigol_24_direct = extract_first_metric(
        match,
        [
            "multigol_2_4_potential",
            "multigoal_2_4_potential",
            "mg_2_4_potential",
            "goals_2_4_potential",
            "goal_range_2_4_potential",
        ],
        default=0.0,
    )
    multigol_24 = multigol_24_direct if multigol_24_direct > 0 else min(over15, under45)

    return {
        "over15": over15,
        "multigol_24": multigol_24,
        "multigol_24_is_estimated": multigol_24_direct <= 0,
        "under45": under45,
        "over25": over25,
        "over05_ht": over05_ht,
        "btts": btts,
        "quota_gol": quota_gol,
        "quota_over25": quota_over25,
        "quota_mg_25": quota_mg_25,
    }



def evaluate_picks(match, weighted_env=None, exact_scores=None):
    p = get_match_profile(match)
    mg_weighted_total = safe_float((weighted_env or {}).get("mg25", {}).get("weighted_total"), 0.0)
    over_weighted_total = safe_float((weighted_env or {}).get("over25", {}).get("weighted_total"), 0.0)

    if mg_weighted_total <= 0:
        mg_weighted_total = safe_float(match.get("team_a_xg_prematch"), 0.0) + safe_float(match.get("team_b_xg_prematch"), 0.0)
    if over_weighted_total <= 0:
        over_weighted_total = safe_float(match.get("team_a_xg_prematch"), 0.0) + safe_float(match.get("team_b_xg_prematch"), 0.0)

    p["mg_weighted_total"] = mg_weighted_total
    p["over_weighted_total"] = over_weighted_total

    mg25_ok = (
        p["over15"] > 75 and
        p["multigol_24"] > 60 and
        p["under45"] > 78 and
        2.20 <= mg_weighted_total <= 3.60
    )

    over25_ok = (
        p["over25"] > 60 and
        1.45 <= p["quota_over25"] <= 1.70 and
        p["quota_gol"] > 0 and
        p["quota_gol"] < p["quota_over25"] and
        p["over05_ht"] > 70 and
        over_weighted_total >= 2.40
    )

    if exact_scores:
        if mg25_ok and not exact_scores_support_mg25(exact_scores):
            mg25_ok = False
        if over25_ok and not exact_scores_support_over25(exact_scores):
            over25_ok = False

    picks = []
    reasons = []

    if mg25_ok:
        picks.append("MULTIGOL 2-5")
        reasons.append(f"Over 1.5 > 75, MG 2-4 > 60, Under 4.5 > 78, media ponderata MG {mg_weighted_total:.2f} tra 2.20 e 3.60")

    if over25_ok:
        picks.append("OVER 2.5")
        reasons.append(f"Over 2.5 > 60, quota 1.45-1.70, quota Gol < quota Over, Over 0.5 PT > 70, media ponderata Over {over_weighted_total:.2f} >= 2.40")

    if not picks:
        return "NO BET", "Nessuna delle due strategie supera i filtri", p

    return " + ".join(picks), " | ".join(reasons), p



def build_exact_score_candidates(match, profile, form_bundle=None, team_stats=None):
    form_bundle = form_bundle or {}
    team_stats = team_stats or {}

    home_name = (match.get("home_name") or "").strip()
    away_name = (match.get("away_name") or "").strip()

    home_form = form_bundle.get("home") or {}
    away_form = form_bundle.get("away") or {}

    home_stats = {}
    away_stats = {}
    if isinstance(team_stats, dict):
        for _, team in team_stats.items():
            name = str(team.get("team_name", "")).strip().lower()
            if home_name and name == home_name.lower():
                home_stats = team
            if away_name and name == away_name.lower():
                away_stats = team

    def team_metric(primary, fallback=0.0):
        return safe_float(primary, fallback)

    # Feed / pre-match signals
    home_ppg = extract_first_metric(
        match,
        [
            "pre_match_teamA_overall_ppg",
            "team_a_ppg",
            "home_ppg",
            "home_ppg_prematch",
            "pre_match_home_ppg",
        ],
        default=1.35,
    )
    away_ppg = extract_first_metric(
        match,
        [
            "pre_match_teamB_overall_ppg",
            "team_b_ppg",
            "away_ppg",
            "away_ppg_prematch",
            "pre_match_away_ppg",
        ],
        default=1.15,
    )

    home_xg = extract_first_metric(match, ["team_a_xg_prematch", "home_xg", "home_xg_prematch"], default=1.35)
    away_xg = extract_first_metric(match, ["team_b_xg_prematch", "away_xg", "away_xg_prematch"], default=1.15)

    # Recent form
    home_scored_form = team_metric(home_form.get("scored_avg"), home_xg)
    home_conceded_form = team_metric(home_form.get("conceded_avg"), 1.10)
    away_scored_form = team_metric(away_form.get("scored_avg"), away_xg)
    away_conceded_form = team_metric(away_form.get("conceded_avg"), 1.10)

    # League team stats, if available
    home_scored_league = team_metric(
        home_stats.get("scored_average_home") or home_stats.get("scored_average"),
        home_scored_form,
    )
    home_conceded_league = team_metric(
        home_stats.get("conceded_average_home") or home_stats.get("conceded_average"),
        home_conceded_form,
    )
    away_scored_league = team_metric(
        away_stats.get("scored_average_away") or away_stats.get("scored_average"),
        away_scored_form,
    )
    away_conceded_league = team_metric(
        away_stats.get("conceded_average_away") or away_stats.get("conceded_average"),
        away_conceded_form,
    )

    # Blend all sources
    exp_home = max(
        0.2,
        (
            home_xg * 0.30
            + home_scored_form * 0.20
            + away_conceded_form * 0.15
            + home_scored_league * 0.20
            + away_conceded_league * 0.15
        ),
    )
    exp_away = max(
        0.2,
        (
            away_xg * 0.30
            + away_scored_form * 0.20
            + home_conceded_form * 0.15
            + away_scored_league * 0.20
            + home_conceded_league * 0.15
        ),
    )

    over15 = profile.get("over15", 0)
    over25 = profile.get("over25", 0)
    under45 = profile.get("under45", 0)
    btts = profile.get("btts", 0)
    over05_ht = profile.get("over05_ht", 0)
    quota_gol = profile.get("quota_gol", 0)
    quota_over25 = profile.get("quota_over25", 0)

    candidates = [
        (1, 0), (0, 1), (1, 1),
        (2, 0), (0, 2), (2, 1), (1, 2),
        (2, 2), (3, 0), (0, 3), (3, 1), (1, 3)
    ]

    ranked = []
    ppg_gap = home_ppg - away_ppg

    for hg, ag in candidates:
        total = hg + ag
        both_score = hg > 0 and ag > 0

        # Start from closeness to expected goals
        score = 100.0
        score -= abs(hg - exp_home) * 18
        score -= abs(ag - exp_away) * 18

        # Total goals structure from market/feed
        if total >= 2:
            score += over15 * 0.12
        else:
            score -= 8

        if total >= 3:
            score += over25 * 0.18
        else:
            score += (100 - over25) * 0.06

        if total <= 4:
            score += under45 * 0.10
        else:
            score -= 10

        # BTTS / Goal market
        if both_score:
            score += btts * 0.18
            if quota_gol > 0 and quota_over25 > 0 and quota_gol < quota_over25:
                score += 4
        else:
            score += (100 - btts) * 0.08

        # Early-goal environment slightly favors 2-1 / 1-2 / 2-0 / 0-2 / 1-1
        if over05_ht > 70 and (hg, ag) in {(2, 1), (1, 2), (2, 0), (0, 2), (1, 1)}:
            score += 4

        # Home/away bias from PPG
        if hg > ag:
            score += max(0, ppg_gap) * 5
        elif ag > hg:
            score += max(0, -ppg_gap) * 5
        else:
            score += max(0, 1.2 - abs(ppg_gap)) * 2

        # Small preference for more common exact scores
        if (hg, ag) in {(1, 1), (2, 1), (1, 2), (2, 0), (0, 2)}:
            score += 2

        ranked.append({"scoreline": f"{hg}-{ag}", "score": round(score, 2)})

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:3]



def summarize_recent_trends(form_data):
    if not form_data:
        return {
            "count": 0,
            "gg_count": 0,
            "ng_count": 0,
            "over15_count": 0,
            "over25_count": 0,
            "under45_count": 0,
            "avg_total_goals": 0.0,
        }

    count = int(form_data.get("count", 0) or 0)
    gg_rate = safe_float(form_data.get("btts_rate"), 0.0)
    over15_rate = safe_float(form_data.get("over15_rate"), 0.0)
    over25_rate = safe_float(form_data.get("over25_rate"), 0.0)
    under45_rate = safe_float(form_data.get("under45_rate"), 0.0)
    scored_avg = safe_float(form_data.get("scored_avg"), 0.0)
    conceded_avg = safe_float(form_data.get("conceded_avg"), 0.0)

    gg_count = round(count * gg_rate)
    over15_count = round(count * over15_rate)
    over25_count = round(count * over25_rate)
    under45_count = round(count * under45_rate)
    ng_count = max(0, count - gg_count)
    avg_total_goals = scored_avg + conceded_avg

    return {
        "count": count,
        "gg_count": gg_count,
        "ng_count": ng_count,
        "over15_count": over15_count,
        "over25_count": over25_count,
        "under45_count": under45_count,
        "avg_total_goals": avg_total_goals,
    }





def get_grouped_filtered_matches(matches, team_stats_by_league=None, recent_results_by_league=None):
    rows = []
    team_stats_by_league = team_stats_by_league or {}
    recent_results_by_league = recent_results_by_league or {}

    for m in matches:
        try:
            home_id = safe_int(m.get("homeID"), 0)
            away_id = safe_int(m.get("awayID"), 0)

            league_key = m.get("_league_key")
            season_id_local = m.get("_season_id") or m.get("season_id") or m.get("seasonID") or m.get("season")

            league_team_stats = team_stats_by_league.get(league_key)
            if league_team_stats is None and season_id_local:
                try:
                    league_team_stats = fetch_league_team_stats(season_id_local)
                except Exception:
                    league_team_stats = {}
                team_stats_by_league[league_key] = league_team_stats

            league_recent_results = recent_results_by_league.get(league_key)
            if league_recent_results is None and season_id_local:
                try:
                    league_recent_results = fetch_league_recent_results(season_id_local)
                except Exception:
                    league_recent_results = []
                recent_results_by_league[league_key] = league_recent_results

            home_stats = (league_team_stats or {}).get(home_id, {})
            away_stats = (league_team_stats or {}).get(away_id, {})

            form_bundle = {
                "home": compute_recent_form(league_recent_results or [], home_id, "home", n=5),
                "away": compute_recent_form(league_recent_results or [], away_id, "away", n=5),
            }

            weighted_env = build_weighted_goal_environment(
                home_stats,
                away_stats,
                form_bundle,
                m,
            )

            temp_pick, temp_reason, temp_profile = evaluate_picks(m, weighted_env=weighted_env)
            exact_scores = build_exact_score_candidates(m, temp_profile, form_bundle=form_bundle, team_stats=league_team_stats or {})
            pick, reason, profile = evaluate_picks(m, weighted_env=weighted_env, exact_scores=exact_scores)
        except Exception:
            continue

        league_name = m.get("_league_name") or m.get("competition_name") or m.get("league_name") or "Campionato"
        match_name = m.get("_match_label") or f"{m.get('home_name', 'Casa')} vs {m.get('away_name', 'Ospite')}"

        if "OVER 2.5" in pick:
            rows.append({
                "strategy": "OVER 2.5",
                "league": league_name,
                "match_name": match_name,
                "percent": safe_float(profile.get("over25"), 0.0),
            })

        if "MULTIGOL 2-5" in pick:
            rows.append({
                "strategy": "MULTIGOL 2-5",
                "league": league_name,
                "match_name": match_name,
                "percent": safe_float(profile.get("multigol_24"), 0.0),
            })

    rows.sort(key=lambda x: (-x["percent"], str(x["league"]), str(x["match_name"])))
    return rows




def infer_matchday(selected):
    candidate_keys = [
        "game_week", "match_round", "round", "round_name", "week", "gw",
        "roundID", "round_id", "gameweek", "stage", "stage_name"
    ]
    for key in candidate_keys:
        val = selected.get(key)
        if val not in (None, "", "null"):
            if key in {"roundID", "round_id"}:
                return f"{val}"
            return val

    nested = deep_find_first(selected, candidate_keys)
    if nested not in (None, "", "null"):
        return nested

    return "-"




def standings_rows_from_team_stats(team_stats):
    rows = []
    for team_id, item in (team_stats or {}).items():
        if not isinstance(item, dict):
            continue
        rows.append({
            "Pos": safe_int(item.get("position"), 0),
            "Squadra": item.get("team_name", f"Team {team_id}"),
            "Pt": safe_int(item.get("points"), 0),
            "G": safe_int(item.get("played"), 0),
            "V": safe_int(item.get("wins"), 0),
            "N": safe_int(item.get("draws"), 0),
            "P": safe_int(item.get("losses"), 0),
        })
    rows = [r for r in rows if r["Squadra"]]
    rows.sort(key=lambda x: (x["Pos"] if x["Pos"] else 999, -x["Pt"], x["Squadra"]))
    return rows


def weighted_team_goal_profile_for_strategy(team_stats_data, recent_form_data, side="home", prematch_xg=0.0, strategy="mg25"):
    team_stats_data = team_stats_data or {}
    recent_form_data = recent_form_data or {}

    scored_general = safe_float(team_stats_data.get("scored_average"), 0.0)
    conceded_general = safe_float(team_stats_data.get("conceded_average"), 0.0)

    if side == "home":
        scored_split = safe_float(team_stats_data.get("scored_home"), scored_general)
        conceded_split = safe_float(team_stats_data.get("conceded_home"), conceded_general)
    else:
        scored_split = safe_float(team_stats_data.get("scored_away"), scored_general)
        conceded_split = safe_float(team_stats_data.get("conceded_away"), conceded_general)

    form_scored = safe_float(recent_form_data.get("scored_avg"), scored_split)
    form_conceded = safe_float(recent_form_data.get("conceded_avg"), conceded_split)

    if strategy == "over25":
        w = {"general": 0.20, "split": 0.35, "form": 0.25, "xg": 0.20}
    else:
        w = {"general": 0.25, "split": 0.35, "form": 0.30, "xg": 0.10}

    scored_weighted = (
        scored_general * w["general"] +
        scored_split * w["split"] +
        form_scored * w["form"] +
        prematch_xg * w["xg"]
    )

    conceded_weighted = (
        conceded_general * w["general"] +
        conceded_split * w["split"] +
        form_conceded * w["form"] +
        prematch_xg * w["xg"]
    )

    return {
        "scored_general": scored_general,
        "conceded_general": conceded_general,
        "scored_split": scored_split,
        "conceded_split": conceded_split,
        "form_scored": form_scored,
        "form_conceded": form_conceded,
        "prematch_xg": prematch_xg,
        "scored_weighted": round(scored_weighted, 2),
        "conceded_weighted": round(conceded_weighted, 2),
    }


def build_weighted_goal_environment(home_stats, away_stats, form_bundle, selected):
    home_xg = safe_float(selected.get("team_a_xg_prematch"), 0.0)
    away_xg = safe_float(selected.get("team_b_xg_prematch"), 0.0)

    home_mg = weighted_team_goal_profile_for_strategy(home_stats, (form_bundle or {}).get("home"), side="home", prematch_xg=home_xg, strategy="mg25")
    away_mg = weighted_team_goal_profile_for_strategy(away_stats, (form_bundle or {}).get("away"), side="away", prematch_xg=away_xg, strategy="mg25")
    mg_expected_home = round((home_mg["scored_weighted"] + away_mg["conceded_weighted"]) / 2, 2)
    mg_expected_away = round((away_mg["scored_weighted"] + home_mg["conceded_weighted"]) / 2, 2)
    mg_total = round(mg_expected_home + mg_expected_away, 2)

    home_over = weighted_team_goal_profile_for_strategy(home_stats, (form_bundle or {}).get("home"), side="home", prematch_xg=home_xg, strategy="over25")
    away_over = weighted_team_goal_profile_for_strategy(away_stats, (form_bundle or {}).get("away"), side="away", prematch_xg=away_xg, strategy="over25")
    over_expected_home = round((home_over["scored_weighted"] + away_over["conceded_weighted"]) / 2, 2)
    over_expected_away = round((away_over["scored_weighted"] + home_over["conceded_weighted"]) / 2, 2)
    over_total = round(over_expected_home + over_expected_away, 2)

    return {
        "mg25": {
            "home": home_mg,
            "away": away_mg,
            "expected_home_goals": mg_expected_home,
            "expected_away_goals": mg_expected_away,
            "weighted_total": mg_total,
        },
        "over25": {
            "home": home_over,
            "away": away_over,
            "expected_home_goals": over_expected_home,
            "expected_away_goals": over_expected_away,
            "weighted_total": over_total,
        },
        "weighted_total": mg_total,
        "home": home_mg,
        "away": away_mg,
        "expected_home_goals": mg_expected_home,
        "expected_away_goals": mg_expected_away,
    }


def exact_scores_support_over25(exact_scores):
    top = (exact_scores or [])[:3]
    if len(top) < 3:
        return False
    for item in top:
        try:
            h, a = [int(x) for x in str(item.get("scoreline", "")).split("-")]
        except Exception:
            return False
        if h + a < 3:
            return False
    return True


def exact_scores_support_mg25(exact_scores):
    top = (exact_scores or [])[:3]
    if len(top) < 3:
        return False
    for item in top:
        try:
            h, a = [int(x) for x in str(item.get("scoreline", "")).split("-")]
        except Exception:
            return False
        if not (2 <= h + a <= 5):
            return False
    return True

def build_match_export_payload(selected, profile=None, pick=None, reason=None, exact_scores=None, home_stats=None, away_stats=None, form_bundle=None, weighted_env=None):
    return {
        "match_info": selected,
        "strategy_result": {
            "pick": pick,
            "reason": reason,
            "profile": profile or {},
            "exact_scores": exact_scores or [],
            "weighted_env": weighted_env or {},
        },
        "team_stats": {
            "home": home_stats or {},
            "away": away_stats or {},
        },
        "recent_form": form_bundle or {},
    }




def simple_pick(match, form):
    o15 = safe_float(match.get("o15_potential"))
    u35 = safe_float(match.get("u35_potential"))
    xg = safe_float(match.get("total_xg_prematch"))
    btts = safe_float(match.get("btts_potential"))

    home = form.get("home", {})
    away = form.get("away", {})
    form_ready = home.get("count", 0) >= 3 and away.get("count", 0) >= 3

    if not form_ready:
        return "NO BET", "Forma non sufficiente"

    recent_over15 = (home.get("over15_rate", 0) + away.get("over15_rate", 0)) / 2
    recent_under35 = (home.get("under35_rate", 0) + away.get("under35_rate", 0)) / 2

    if 72 <= o15 <= 82 and xg >= 2.2 and recent_over15 >= 0.60:
        return "OVER 1.5", "Match da gol ma non scontato"

    if 70 <= u35 <= 85 and xg <= 2.6 and recent_under35 >= 0.55 and btts < 60:
        return "UNDER 3.5", "Match controllato e non troppo aperto"

    return "NO BET", "Nessuna condizione valida"


def fmt_stat(value):
    if value in (None, "", 0):
        return "-"
    return f"{safe_float(value):.2f}"


def app():
    st.set_page_config(page_title="MG Footy App Simple", layout="wide")

    st.markdown(
        """
        <style>
        .stApp {background: linear-gradient(180deg, #f6f8fc 0%, #eef3f9 100%);}
        .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1240px;}
        h1, h2, h3, p, div, span, label {color:#24364b;}
        .card {
            background:#ffffff;
            border:1px solid #dde5f0;
            border-radius:22px;
            padding:20px;
            margin-top:12px;
            margin-bottom:12px;
            box-shadow: 0 10px 30px rgba(34, 57, 94, 0.08);
        }
        .section-title {
            font-size:22px;
            font-weight:800;
            margin-bottom:12px;
            color:#24364b;
        }
        .hero-card{
            background:#ffffff;
            border:1px solid #dbe4ef;
            border-radius:26px;
            padding:24px 26px;
            box-shadow:0 12px 30px rgba(34,57,94,.08);
            margin-bottom:14px;
        }
        .hero-title{
            text-align:center;
            font-size:34px;
            font-weight:800;
            color:#24364b;
            margin-bottom:8px;
        }
        .hero-sub{
            text-align:center;
            color:#71839b;
            font-size:18px;
            margin-bottom:14px;
        }
        .bet-pill{
            display:inline-block;
            background:linear-gradient(90deg,#1fa553,#15803d);
            color:white;
            font-weight:800;
            font-size:20px;
            padding:10px 26px;
            border-radius:999px;
            box-shadow:0 8px 18px rgba(31,165,83,.22);
        }
        .bet-pill-wrap{ text-align:center; margin: 8px 0 6px; }
        .quality{
            text-align:center;
            font-size:20px;
            font-weight:700;
            color:#3e536d;
            margin-top:8px;
        }
        .quality strong{color:#1d7f43;}
        .metrics-row{
            display:grid;
            grid-template-columns: repeat(4, 1fr);
            gap:14px;
            margin-top:8px;
            margin-bottom:8px;
        }
        .metric-card{
            border-radius:20px;
            padding:18px 14px;
            color:white;
            text-align:center;
            box-shadow:0 10px 22px rgba(33,52,84,0.14);
        }
        .metric-card .label{font-size:18px;font-weight:800;opacity:.95;}
        .metric-card .value{font-size:34px;font-weight:900;line-height:1.1;margin-top:10px;}
        .m-green{background:linear-gradient(135deg,#2fb46c,#1f8f53);}
        .m-blue{background:linear-gradient(135deg,#2f8ff1,#205eb6);}
        .m-red{background:linear-gradient(135deg,#ef5350,#c62828);}
        .m-orange{background:linear-gradient(135deg,#f4a340,#ef7e23);}
        .mini-row{
            display:grid;
            grid-template-columns: repeat(4, 1fr);
            gap:12px;
            margin-top:8px;
            margin-bottom:8px;
        }
        .mini-box{
            background:#ffffff;
            border:1px solid #dbe4ef;
            border-radius:16px;
            padding:16px 14px;
            text-align:center;
            box-shadow:0 8px 18px rgba(34,57,94,0.05);
        }
        .mini-box .label{font-size:15px;font-weight:700;color:#667a92;}
        .mini-box .value{font-size:28px;font-weight:900;color:#24364b;margin-top:6px;}
        .quote-row{
            display:grid;
            grid-template-columns: repeat(3, 1fr);
            gap:12px;
            margin-top:10px;
        }
        .quote-box{
            background:#f9fbfe;
            border:1px solid #d7e1ec;
            border-radius:16px;
            padding:15px 12px;
            text-align:center;
        }
        .quote-box .label{font-size:16px;font-weight:700;color:#667a92;}
        .quote-box .value{font-size:26px;font-weight:900;color:#24364b;margin-top:4px;}
        .result-pill{
            display:inline-block;
            background:#f9fbfe;
            border:1px solid #d7e1ec;
            border-radius:14px;
            padding:10px 18px;
            margin:4px 8px 4px 0;
            font-size:18px;
            font-weight:800;
            color:#24364b;
            box-shadow:0 5px 12px rgba(34,57,94,0.05);
        }
        .matchday-box{
            background:#ffffff;
            border:1px solid #dbe4ef;
            border-radius:18px;
            padding:18px;
            text-align:center;
            box-shadow:0 8px 18px rgba(34,57,94,0.05);
        }
        .matchday-box .label{font-size:16px;color:#71839b;font-weight:700;}
        .matchday-box .value{font-size:30px;font-weight:900;color:#24364b;margin-top:6px;}
        .standing-row{
            display:flex;justify-content:space-between;align-items:center;
            padding:10px 0;border-bottom:1px solid #edf2f7;font-size:18px;
        }
        .standing-row:last-child{border-bottom:none;}
        .standing-highlight{font-weight:900;color:#1d7f43;}
        div[data-testid="stExpander"]{
            background:#f9fbfe;border:1px solid #dde5f0;border-radius:16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


    st.title("⚽ MG Footy App")
    st.caption("Tema chiaro dashboard, con focus su MULTIGOL 2-5 e OVER 2.5.")

    giorni_da_mostrare = st.slider("Quanti giorni vuoi vedere", min_value=0, max_value=14, value=14)

    if st.button("🔄 Aggiorna dati"):
        st.cache_data.clear()
        st.rerun()


    chosen_lookup = fetch_chosen_leagues()
    if not chosen_lookup.get("leagues"):
        chosen_lookup = fetch_all_leagues_fallback()
    matches = fetch_matches_14_days()

    now_ts = int(datetime.now().timestamp())
    max_ts = now_ts + (giorni_da_mostrare * 86400)
    if giorni_da_mostrare == 0:
        matches = [m for m in matches if safe_int(m.get("date_unix"), 0) >= now_ts and safe_int(m.get("date_unix"), 0) <= now_ts + 86399]
    else:
        matches = [m for m in matches if safe_int(m.get("date_unix"), 0) >= now_ts and safe_int(m.get("date_unix"), 0) <= max_ts]

    available = {}
    for m in matches:
        available[m["_league_key"]] = m["_league_name"]

    if not available:
        st.warning("Nessuna partita trovata nell'intervallo scelto.")
        st.stop()

    default_strategy = st.session_state.get("strategy_view", "Dettaglio partita")
    strategy_options = ["Dettaglio partita", "Solo OVER 2.5", "Solo MULTIGOL 2-5"]
    default_idx = strategy_options.index(default_strategy) if default_strategy in strategy_options else 0
    strategy_view = st.radio(
        "Filtro strategie",
        strategy_options,
        index=default_idx,
        horizontal=True,
    )
    st.session_state["strategy_view"] = strategy_view

    if strategy_view != "Dettaglio partita":
        target_strategy = "OVER 2.5" if strategy_view == "Solo OVER 2.5" else "MULTIGOL 2-5"
        filtered_rows = [r for r in get_grouped_filtered_matches(matches) if r["strategy"] == target_strategy]

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f'<div class="section-title">📋 {target_strategy} - Partite filtrate</div>', unsafe_allow_html=True)
        st.caption("La vista filtro usa la stessa logica del dettaglio: percentuali, quote, medie gol, ultime 5 e xG.")

        if not filtered_rows:
            st.warning(f"Nessuna partita trovata per il filtro {target_strategy}.")
        else:
            current_league = None
            for idx, row in enumerate(filtered_rows):
                if row["league"] != current_league:
                    current_league = row["league"]
                    st.markdown(f"### {current_league}")

                c1, c2 = st.columns([5, 1])
                with c1:
                    st.write(f"**{row['match_name']}** — {row['percent']:.0f}%")
                with c2:
                    if st.button("Apri", key=f"open_match_{target_strategy}_{idx}"):
                        st.session_state["forced_match_label"] = row["match_name"]
                        st.session_state["forced_league_name"] = row["league"]
                        st.session_state["previous_strategy_view"] = strategy_view
                        st.session_state["strategy_view"] = "Dettaglio partita"
                        st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

    league_names = sorted(available.values())
    league_choice = st.selectbox("Scegli il campionato", league_names)
    key_by_name = {v: k for k, v in available.items()}
    selected_key = key_by_name[league_choice]

    league_matches = [m for m in matches if m.get("_league_key") == selected_key]
    if not league_matches:
        st.warning("Nessuna partita trovata per questo campionato.")
        st.stop()

    match_labels = [m["_match_label"] for m in league_matches]

    forced_league_name = st.session_state.get("forced_league_name")
    forced_match_label = st.session_state.get("forced_match_label")

    if forced_league_name and forced_league_name in league_names:
        league_choice = forced_league_name
        selected_key = key_by_name[league_choice]
        league_matches = [m for m in matches if m.get("_league_key") == selected_key]
        match_labels = [m["_match_label"] for m in league_matches]

    default_match_idx = 0
    if forced_match_label and forced_match_label in match_labels:
        default_match_idx = match_labels.index(forced_match_label)

    chosen_label = st.selectbox("Scegli la partita", match_labels, index=default_match_idx)
    selected = next(m for m in league_matches if m["_match_label"] == chosen_label)

    if forced_match_label == chosen_label:
        st.session_state.pop("forced_match_label", None)
        st.session_state.pop("forced_league_name", None)

    season_id = selected.get("_season_id")
    recent_matches = fetch_league_recent_results(season_id)
    home_id = safe_int(selected.get("homeID"), 0)
    away_id = safe_int(selected.get("awayID"), 0)
    form_bundle = {
        "home": compute_recent_form(recent_matches, home_id, "home", n=5),
        "away": compute_recent_form(recent_matches, away_id, "away", n=5),
    }

    team_stats = fetch_league_team_stats(season_id)
    standings_data = fetch_league_standings(season_id)

    # fallback names from current league matches
    for m in league_matches:
        hid = safe_int(m.get("homeID"), 0)
        aid = safe_int(m.get("awayID"), 0)
        if hid and hid in team_stats:
            team_stats[hid]["team_name"] = team_stats[hid].get("team_name") or m.get("home_name", f"Team {hid}")
        if aid and aid in team_stats:
            team_stats[aid]["team_name"] = team_stats[aid].get("team_name") or m.get("away_name", f"Team {aid}")
    home_trend = summarize_recent_trends(form_bundle.get('home'))
    away_trend = summarize_recent_trends(form_bundle.get('away'))
    home_stats = team_stats.get(home_id, {})
    away_stats = team_stats.get(away_id, {})
    weighted_env = build_weighted_goal_environment(home_stats, away_stats, form_bundle, selected)
    temp_pick, temp_reason, temp_profile = evaluate_picks(selected, weighted_env=weighted_env)
    exact_scores = build_exact_score_candidates(selected, temp_profile, form_bundle=form_bundle, team_stats=team_stats)
    pick, reason, profile = evaluate_picks(selected, weighted_env=weighted_env, exact_scores=exact_scores)

    export_payload = build_match_export_payload(
        selected,
        profile=profile,
        pick=pick,
        reason=reason,
        exact_scores=exact_scores,
        home_stats=home_stats,
        away_stats=away_stats,
        form_bundle=form_bundle,
        weighted_env=weighted_env,
    )
    export_json = json.dumps(export_payload, ensure_ascii=False, indent=2)

    back_strategy = st.session_state.get("previous_strategy_view")
    if back_strategy in ("Solo OVER 2.5", "Solo MULTIGOL 2-5"):
        if st.button("⬅️ Torna alla lista filtrata"):
            st.session_state["strategy_view"] = back_strategy
            st.rerun()

    col1, col2 = st.columns([1.2, 1])

    with col1:
        quality_label = "FORTE" if pick != "NO BET" else "NESSUNA BET"
        hero_html = f'''
        <div class="hero-card">
            <div class="hero-title">{selected.get("home_name", "Casa")} vs {selected.get("away_name", "Ospite")}</div>
            <div class="hero-sub">{format_dt_short(selected.get("date_unix"))}</div>
            <div class="bet-pill-wrap"><span class="bet-pill">GIOCATA CONSIGLIATA: {pick}</span></div>
            <div class="quality">Qualità: <strong>{quality_label}</strong></div>
        </div>
        '''
        st.markdown(hero_html, unsafe_allow_html=True)
        if reason:
            st.caption(reason)
        if profile.get("multigol_24_is_estimated"):
            st.info("Nota: il dato MG 2-4 viene stimato con Over 1.5 + Under 4.5 se il campo diretto non è presente nel feed.")


        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⚽ Statistiche squadre</div>', unsafe_allow_html=True)
        xg_home = safe_float(selected.get('team_a_xg_prematch'), 0.0)
        xg_away = safe_float(selected.get('team_b_xg_prematch'), 0.0)
        xg_total = xg_home + xg_away

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**{selected.get('home_name', 'Casa')}**")
            st.write(f"Gol fatti in casa: {fmt_stat(home_stats.get('scored_home'))}")
            st.write(f"Gol subiti in casa: {fmt_stat(home_stats.get('conceded_home'))}")
            st.write(f"xG Casa: {fmt_stat(xg_home)}")
            with st.expander("🔍 Mostra dati avanzati"):
                st.write(f"Media attacco ponderata MG: {fmt_stat(weighted_env.get('mg25', {}).get('home', {}).get('scored_weighted'))}")
                st.write(f"Media difesa ponderata MG: {fmt_stat(weighted_env.get('mg25', {}).get('home', {}).get('conceded_weighted'))}")
                st.write(f"Media attacco ponderata Over: {fmt_stat(weighted_env.get('over25', {}).get('home', {}).get('scored_weighted'))}")
                st.write(f"Media difesa ponderata Over: {fmt_stat(weighted_env.get('over25', {}).get('home', {}).get('conceded_weighted'))}")
            if home_trend.get('count', 0) > 0:
                st.write(f"Ultime 5 GG: {home_trend['gg_count']}/{home_trend['count']}")
                st.write(f"Ultime 5 NG: {home_trend['ng_count']}/{home_trend['count']}")
                st.write(f"Ultime 5 Over 1.5: {home_trend['over15_count']}/{home_trend['count']}")
                st.write(f"Ultime 5 Over 2.5: {home_trend['over25_count']}/{home_trend['count']}")
                st.write(f"Ultime 5 Under 4.5: {home_trend['under45_count']}/{home_trend['count']}")
                st.write(f"Media gol totali ultime 5: {fmt_stat(home_trend['avg_total_goals'])}")
            else:
                st.write("Trend ultime 5 non disponibili")

        with c2:
            st.markdown(f"**{selected.get('away_name', 'Ospite')}**")
            st.write(f"Gol fatti in trasferta: {fmt_stat(away_stats.get('scored_away'))}")
            st.write(f"Gol subiti in trasferta: {fmt_stat(away_stats.get('conceded_away'))}")
            st.write(f"xG Trasferta: {fmt_stat(xg_away)}")
            with st.expander("🔍 Mostra dati avanzati"):
                st.write(f"Media attacco ponderata MG: {fmt_stat(weighted_env.get('mg25', {}).get('away', {}).get('scored_weighted'))}")
                st.write(f"Media difesa ponderata MG: {fmt_stat(weighted_env.get('mg25', {}).get('away', {}).get('conceded_weighted'))}")
                st.write(f"Media attacco ponderata Over: {fmt_stat(weighted_env.get('over25', {}).get('away', {}).get('scored_weighted'))}")
                st.write(f"Media difesa ponderata Over: {fmt_stat(weighted_env.get('over25', {}).get('away', {}).get('conceded_weighted'))}")
            if away_trend.get('count', 0) > 0:
                st.write(f"Ultime 5 GG: {away_trend['gg_count']}/{away_trend['count']}")
                st.write(f"Ultime 5 NG: {away_trend['ng_count']}/{away_trend['count']}")
                st.write(f"Ultime 5 Over 1.5: {away_trend['over15_count']}/{away_trend['count']}")
                st.write(f"Ultime 5 Over 2.5: {away_trend['over25_count']}/{away_trend['count']}")
                st.write(f"Ultime 5 Under 4.5: {away_trend['under45_count']}/{away_trend['count']}")
                st.write(f"Media gol totali ultime 5: {fmt_stat(away_trend['avg_total_goals'])}")
            else:
                st.write("Trend ultime 5 non disponibili")

        st.write(f"**xG Totale Partita:** {fmt_stat(xg_total)}")
        st.write(f"**Media ponderata MG 2-5:** {fmt_stat(weighted_env.get('mg25', {}).get('weighted_total'))}")
        st.write(f"**Gol attesi ponderati MG casa:** {fmt_stat(weighted_env.get('mg25', {}).get('expected_home_goals'))}")
        st.write(f"**Gol attesi ponderati MG trasferta:** {fmt_stat(weighted_env.get('mg25', {}).get('expected_away_goals'))}")
        st.write(f"**Media ponderata Over 2.5:** {fmt_stat(weighted_env.get('over25', {}).get('weighted_total'))}")
        st.write(f"**Gol attesi ponderati Over casa:** {fmt_stat(weighted_env.get('over25', {}).get('expected_home_goals'))}")
        st.write(f"**Gol attesi ponderati Over trasferta:** {fmt_stat(weighted_env.get('over25', {}).get('expected_away_goals'))}")
        st.caption("Pesi differenziati: Over 2.5 privilegia di più xG; MG 2-5 privilegia di più forma recente ed equilibrio.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        xg_home = safe_float(selected.get('team_a_xg_prematch'), 0.0)
        xg_away = safe_float(selected.get('team_b_xg_prematch'), 0.0)
        xg_total = xg_home + xg_away
        media_ultime5 = round((home_trend.get('avg_total_goals', 0.0) + away_trend.get('avg_total_goals', 0.0)) / 2, 2) if (home_trend.get('count', 0) or away_trend.get('count', 0)) else 0.0

        st.markdown('<div class="metrics-row">'
                    + '<div class="metric-card m-green"><div class="label">Over 1.5</div><div class="value">' + f"{profile['over15']:.0f}%" + '</div></div>'
                    + '<div class="metric-card m-blue"><div class="label">MG 2-4</div><div class="value">' + f"{profile['multigol_24']:.0f}%" + '</div></div>'
                    + '<div class="metric-card m-red"><div class="label">Under 4.5</div><div class="value">' + f"{profile['under45']:.0f}%" + '</div></div>'
                    + '<div class="metric-card m-orange"><div class="label">Over 2.5</div><div class="value">' + f"{profile['over25']:.0f}%" + '</div></div>'
                    + '</div>', unsafe_allow_html=True)

        st.markdown('<div class="mini-row">'
                    + '<div class="mini-box"><div class="label">xG Totale</div><div class="value">' + f"{fmt_stat(xg_total)}" + '</div></div>'
                    + '<div class="mini-box"><div class="label">Media Gol Ultime 5</div><div class="value">' + f"{fmt_stat(media_ultime5)}" + '</div></div>'
                    + '<div class="mini-box"><div class="label">Gol Attesi Casa</div><div class="value">' + f"{fmt_stat(weighted_env.get('mg25', {}).get('expected_home_goals'))}" + '</div></div>'
                    + '<div class="mini-box"><div class="label">Gol Attesi Trasferta</div><div class="value">' + f"{fmt_stat(weighted_env.get('mg25', {}).get('expected_away_goals'))}" + '</div></div>'
                    + '</div>', unsafe_allow_html=True)

        st.markdown('<div class="quote-row">'
                    + '<div class="quote-box"><div class="label">Quota Gol</div><div class="value">' + f"{fmt_stat(profile['quota_gol'])}" + '</div></div>'
                    + '<div class="quote-box"><div class="label">Quota Over 2.5</div><div class="value">' + f"{fmt_stat(profile['quota_over25'])}" + '</div></div>'
                    + '<div class="quote-box"><div class="label">Quota MG 2-5</div><div class="value">' + f"{fmt_stat(profile.get('quota_mg_25'))}" + '</div></div>'
                    + '</div>', unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">📅 Giornata Campionato</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="matchday-box"><div class="label">Giornata n°</div><div class="value">{infer_matchday(selected)}</div></div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🏆 Classifica Campionato</div>', unsafe_allow_html=True)
        standings_rows = standings_data or standings_rows_from_team_stats(team_stats)
        if standings_rows:
            class_html = ''
            for row in standings_rows[:20]:
                is_selected = normalize_text(row["Squadra"]) in {normalize_text(selected.get("home_name")), normalize_text(selected.get("away_name"))}
                team_class = "standing-highlight" if is_selected else ""
                marker_star = " ⭐" if is_selected else ""
                class_html += f'<div class="standing-row"><span class="{team_class}">{row["Pos"]}. {row["Squadra"]}{marker_star}</span><span class="{team_class}">{row["Pt"]} pt</span></div>'
            st.markdown(class_html, unsafe_allow_html=True)
        else:
            st.write("Classifica non disponibile")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🎯 3 Risultati Esatti Indicativi</div>', unsafe_allow_html=True)
        exact_html = ''.join([f'<span class="result-pill">{item["scoreline"]}</span>' for item in exact_scores[:3]])
        st.markdown(exact_html, unsafe_allow_html=True)
        st.caption("Calcolo basato su feed pre-match, forma recente e statistiche squadra del campionato.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">📋 Regole attive</div>', unsafe_allow_html=True)
        st.write("**MULTIGOL 2-5**")
        st.write("- Over 1.5 > 75")
        st.write("- Multigol 2-4 > 60")
        st.write("- Under 4.5 > 78")
        st.write("")
        st.write("**OVER 2.5**")
        st.write("- Over 2.5 > 60")
        st.write("- Quota Over 2.5 tra 1.45 e 1.70")
        st.write("- Quota Gol < Quota Over 2.5")
        st.write("- Over 0.5 PT > 70")
        st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    app()
