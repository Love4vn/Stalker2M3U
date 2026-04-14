"""
footonsat_schedule_live.py - FINAL OPTIMIZED
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import urllib.error
import time
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
LIVE_M3U = "live_schedule.m3u"

VALIDATION_CONCURRENT = 50
VALIDATION_TIMEOUT = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SKIP_VALIDATION = "--skip-validation" in sys.argv

# ================== DANH SÁCH GIẢI ĐẤU ==================
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton"
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "olympique marseille", "marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "League Cup": PREMIER_LEAGUE_TEAMS
}

LEAGUE_GROUP_NAME = {
    "Premier League": "Live Premier League",
    "Serie A": "Live Serie A",
    "Bundesliga": "Live Bundesliga",
    "La Liga": "Live La Liga",
    "Ligue 1": "Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
    "UEFA Euro": "Live Euro",
    "FA Cup": "Live FA, League Cup",
    "League Cup": "Live FA, League Cup",
    "Tennis": "Live Tennis",
    "FIFA World Cup": "Live Fifa World Cup",
    "International Friendly": "Live International Friendly"
}

# ================== MAPPING QUỐC GIA MỞ RỘNG ==================
COUNTRY_CODES = {
    "uk", "us", "fr", "de", "it", "es", "pt", "nl", "be", "ch", "at",
    "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "bg", "gr", "tr",
    "il", "au", "ca", "nz", "ie", "gb", "en", "vn", "kr", "jp", "cn",
    "br", "ar", "mx", "in", "za", "ru", "ua", "rs", "hr", "si", "sk", "ie", "am"
}

COUNTRY_NAME_TO_CODE = {
    "united states": "us", "usa": "us", "uk": "uk", "united kingdom": "uk",
    "viet nam": "vn", "vietnam": "vn", "korea": "kr", "south korea": "kr",
    "japan": "jp", "china": "cn", "brazil": "br", "argentina": "ar", "mexico": "mx",
    "india": "in", "south africa": "za", "russia": "ru", "ukraine": "ua",
    "serbia": "rs", "srbija": "rs", "croatia": "hr", "hrvatska": "hr", "slovenia": "si", "slovakia": "sk",
    "france": "fr", "french": "fr", "germany": "de", "deutsch": "de", "deutschland": "de",
    "italy": "it", "italia": "it", "spain": "es", "espana": "es", "portugal": "pt",
    "netherlands": "nl", "nederland": "nl", "belgium": "be", "belgie": "be",
    "switzerland": "ch", "austria": "at", "österreich": "at",
    "sweden": "se", "sverige": "se", "norway": "no", "norge": "no",
    "denmark": "dk", "danmark": "dk", "finland": "fi", "suomi": "fi",
    "poland": "pl", "polska": "pl", "czech": "cz", "czech republic": "cz", "czechia": "cz",
    "hungary": "hu", "romania": "ro", "bulgaria": "bg", "greece": "gr", "hellas": "gr",
    "turkey": "tr", "türkiye": "tr", "israel": "il", "australia": "au",
    "canada": "ca", "new zealand": "nz", "ireland": "ie",
    "indonesia": "id", "malaysia": "my", "singapore": "sg", "thailand": "th",
    "egypt": "eg", "morocco": "ma", "algeria": "dz", "tunisia": "tn", "libya": "ly",
    "sudan": "sd", "ethiopia": "et", "kenya": "ke", "nigeria": "ng", "ghana": "gh",
    "senegal": "sn", "côte d'ivoire": "ci", "cameroon": "cm", "angola": "ao",
    "albania": "al", "great britain": "gb", "england": "gb", "scotland": "gb", "wales": "gb",
    "chile": "cl", "suriname": "sr", "armenia": "am", "georgia": "ge", "azerbaijan": "az", "kazakhstan": "kz"
}

FOOTONSAT_URLS = [
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json",
]

LOVE4VN_URL = "https://raw.githubusercontent.com/Love4vn/Live-Schedue/refs/heads/1/schedule.json"

# ================== HELPER ==================
def is_low_resolution(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in ["sd", "360p", "480p", "576p", "low res", "low quality"])

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join(c for c in s if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def extract_prefix_and_name(name: str) -> Tuple[Optional[str], str]:
    name_lower = name.lower()
    patterns = [
        (r'^\|\s*([a-z]{2,3})\s*\|\s*', 1),
        (r'^([a-z]{2,3})\:\s*', 1),
        (r'^([a-z]{2,3})\s*-\s*', 1),
        (r'^([a-z]{2,3})\|\s*', 1),
        (r'^\[([a-z]{2,3})\]\s*', 1),
        (r'^\(([a-z]{2,3})\)\s*', 1),
    ]
    for pat, group in patterns:
        m = re.match(pat, name_lower)
        if m:
            code = m.group(group)
            if code in COUNTRY_CODES:
                remaining = name_lower[m.end():]
                remaining = re.sub(r'^[\|\:\-\s]+', '', remaining)
                return code, remaining.strip()
    cleaned = re.sub(r'^[\|\s\:\-]+', '', name_lower)
    return None, cleaned

def normalize_channel_name(name: str) -> str:
    _, name = extract_prefix_and_name(name)
    name = re.sub(r'\b(hd|uhd|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc|fhd|full hd|ultra hd)\b', '', name)
    name = name.replace('plus', '+')
    name = name.replace(' and ', ' & ')
    name = re.sub(r'[^\w\s\+]', ' ', name)
    name = ' '.join(name.split())
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def has_critical_mismatch(name1: str, name2: str) -> bool:
    n1_lower = name1.lower()
    n2_lower = name2.lower()
    if ("main event" in n1_lower and "max" in n2_lower) or ("main event" in n2_lower and "max" in n1_lower):
        return True
    if (re.search(r'\b1\b', n1_lower) and re.search(r'\b(max|extra|premium)\b', n2_lower)) or \
       (re.search(r'\b1\b', n2_lower) and re.search(r'\b(max|extra|premium)\b', n1_lower)):
        return True
    return False

def is_channel_match(ch_name: str, m3u_name: str, league: str = None) -> bool:
    if not ch_name or not m3u_name:
        return False
    ch_code, ch_clean = extract_prefix_and_name(ch_name)
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    ch_norm = normalize_channel_name(ch_clean)
    m3u_norm = normalize_channel_name(m3u_clean)
    threshold = 0.85 if league == "Tennis" else 0.95
    if ch_code and m3u_code:
        if ch_code != m3u_code:
            return False
        if ch_norm == m3u_norm:
            return True
        if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
            return ch_norm == m3u_norm
        if has_critical_mismatch(ch_norm, m3u_norm):
            return False
        return similar(ch_norm, m3u_norm) >= 0.9
    else:
        if ch_norm == m3u_norm:
            return True
        if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
            return ch_norm == m3u_norm
        if has_critical_mismatch(ch_norm, m3u_norm):
            return False
        return similar(ch_norm, m3u_norm) >= threshold

def is_channel_match_with_country(m3u_name: str, target_country_code: Optional[str], target_channel_name: str, league: str = None) -> bool:
    if not m3u_name or not target_channel_name:
        return False
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    m3u_norm = normalize_channel_name(m3u_clean)
    target_norm = normalize_channel_name(target_channel_name)
    threshold = 0.85 if league == "Tennis" else 0.95
    if target_country_code:
        if not m3u_code or m3u_code != target_country_code:
            return False
        if m3u_norm == target_norm:
            return True
        if len(m3u_norm) <= 3 or len(target_norm) <= 3:
            return m3u_norm == target_norm
        if has_critical_mismatch(m3u_norm, target_norm):
            return False
        return similar(m3u_norm, target_norm) >= 0.9
    else:
        if m3u_norm == target_norm:
            return True
        if len(m3u_norm) <= 3 or len(target_norm) <= 3:
            return m3u_norm == target_norm
        if has_critical_mismatch(m3u_norm, target_norm):
            return False
        return similar(m3u_norm, target_norm) >= threshold

def get_country_code_from_name(country_name: str) -> Optional[str]:
    if not country_name:
        return None
    name_clean = country_name.lower().strip()
    if name_clean in COUNTRY_NAME_TO_CODE:
        return COUNTRY_NAME_TO_CODE[name_clean]
    for full_name, code in COUNTRY_NAME_TO_CODE.items():
        if full_name in name_clean or name_clean in full_name:
            return code
    return None

def remove_country_from_channel_name(channel_name: str, country_name: str) -> str:
    if not country_name:
        return channel_name
    country_lower = country_name.lower().strip()
    pattern = re.compile(r'\b' + re.escape(country_lower) + r'\b', re.IGNORECASE)
    cleaned = pattern.sub('', channel_name).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned

def extract_country_from_channel_name(channel_name: str) -> Optional[str]:
    name_lower = channel_name.lower()
    code, _ = extract_prefix_and_name(channel_name)
    if code:
        return code
    for keyword, code in COUNTRY_NAME_TO_CODE.items():
        if keyword in name_lower:
            return code
    return None

def extract_match_from_m3u_name(m3u_name: str) -> Optional[str]:
    _, name = extract_prefix_and_name(m3u_name)
    name = re.sub(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|CET|EST|UTC|GMT)?)\b', '', name, flags=re.I)
    name = re.sub(r'\b(apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\b', '', name, flags=re.I)
    name = re.sub(r'\b(?:today|tomorrow|yesterday)\b', '', name, flags=re.I)
    name = re.sub(r'^(?:next\s*\|\s*|ao\s+vivo\s*:\s*)', '', name, flags=re.I)
    name = re.sub(r'\s*(?:8k\s+exclusive|exclusive|ppv\s+\d+|hd|fhd|uhd|4k)\s*', ' ', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) < 5:
        return None
    return name

def is_match_name_similar(match_name: str, m3u_name: str) -> bool:
    extracted = extract_match_from_m3u_name(m3u_name)
    if not extracted:
        return False
    match_norm = normalize(match_name)
    extracted_norm = normalize(extracted)
    match_clean = re.sub(r'\b(vs|v\.|versus)\b', ' ', match_norm)
    extracted_clean = re.sub(r'\b(vs|v\.|versus)\b', ' ', extracted_norm)
    if similar(match_clean, extracted_clean) >= 0.7:
        return True
    teams = re.split(r'\s+vs\s+|\s+v\.?\s+|\s+versus\s+', match_norm)
    if len(teams) == 2:
        team1, team2 = teams
        if team1 in extracted_norm and team2 in extracted_norm:
            return True
    return False

# ================== LỌC GIẢI ĐẤU ==================
def is_tennis_allowed(match_name: str) -> bool:
    return True

def is_football_allowed(league: str, match_name: str) -> bool:
    if league not in ALLOWED_FOOTBALL_LEAGUES:
        return False
    if league in ALLOWED_TEAMS_PER_LEAGUE:
        allowed_teams = ALLOWED_TEAMS_PER_LEAGUE[league]
        match_lower = match_name.lower()
        for team in allowed_teams:
            if team in match_lower:
                return True
        return False
    return True

# ================== FOOTONSAT API ==================
def fetch_footonsat_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"   Lỗi tải {url}: {e}")
        return None

def parse_footonsat_data(data: dict) -> List[Dict]:
    games = []
    if not data or "footonsat" not in data:
        return games
    items = data["footonsat"]
    if not isinstance(items, list):
        return games

    COMPET_MAPPING = {
        "english premier league": "Premier League",
        "serie a": "Serie A",
        "la liga": "La Liga",
        "bundesliga": "Bundesliga",
        "ligue 1": "Ligue 1",
        "uefa champions league": "UEFA Champions League",
        "uefa europa league": "UEFA Europa League",
        "uefa conference league": "UEFA Europa Conference League",
    }

    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, dict) and "match" in item and "time" in item and "date" in item:
            match_info = item
            compet = match_info.get("compet", "").lower()
            league = None
            for key, val in COMPET_MAPPING.items():
                if key in compet:
                    league = val
                    break
            if not league:
                i += 1
                continue

            date_str = match_info.get("date")
            time_str = match_info.get("time")
            if not date_str or not time_str:
                i += 1
                continue
            try:
                dt_utc = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
                kick_utc = int(dt_utc.timestamp())
            except Exception:
                i += 1
                continue

            match_name = match_info.get("match", "").strip()
            channels = []
            j = i + 1
            while j < len(items):
                next_item = items[j]
                if isinstance(next_item, dict) and "match" in next_item and "time" in next_item and "date" in next_item:
                    break
                if isinstance(next_item, dict) and "channel" in next_item:
                    related = next_item.get("related_to", "").strip()
                    if not related or similar(normalize(related), normalize(match_name)) >= 0.7:
                        ch_name = next_item.get("channel")
                        if ch_name:
                            ch_name = re.sub(r'[📺]', '', ch_name).strip()
                            country_code = extract_country_from_channel_name(ch_name)
                            channels.append({
                                "country_code": country_code,
                                "channel_name": ch_name
                            })
                j += 1

            if channels and is_football_allowed(league, match_name):
                games.append({
                    "league": league,
                    "match": match_name,
                    "kick_utc": kick_utc,
                    "time": vn_time(kick_utc),
                    "channels": channels,
                    "source": "footonsat"
                })
            i = j
        else:
            i += 1
    return games

# ================== LOVE4VN API ==================
def fetch_love4vn_json() -> Optional[dict]:
    try:
        req = urllib.request.Request(LOVE4VN_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"   Lỗi tải Love4VN: {e}")
        return None

def parse_love4vn_data(data: dict, start_ts_utc: int, end_ts_utc: int) -> List[Dict]:
    games = []
    if not data or "days" not in data:
        return games
    days = data["days"]
    for day_key, day_info in days.items():
        for game in day_info.get("games", []):
            league = game.get("league", "")
            match_name = game.get("match", "").strip()
            kick_utc = game.get("kick_utc")
            if not kick_utc:
                continue
            if not (start_ts_utc <= kick_utc <= end_ts_utc):
                continue

            if league == "Tennis":
                if not match_name:
                    match_name = "Tennis match"
            else:
                if not is_football_allowed(league, match_name):
                    continue

            channel_sources = []
            tv_channels = game.get("tv_channels", [])
            for entry in tv_channels:
                country_name = entry.get("country", "")
                channels_list = entry.get("channels", [])
                is_virtual = any(v in country_name.lower() for v in ["wheresthematch", "livesportsontv", "ausport"])
                base_code = None if is_virtual else get_country_code_from_name(country_name)
                for ch_name in channels_list:
                    if not ch_name:
                        continue
                    final_code = base_code
                    if final_code is None:
                        final_code = extract_country_from_channel_name(ch_name)
                    if not is_virtual and country_name:
                        cleaned_name = remove_country_from_channel_name(ch_name, country_name)
                    else:
                        cleaned_name = ch_name
                    channel_sources.append({
                        "country_code": final_code,
                        "channel_name": cleaned_name
                    })
            if channel_sources:
                games.append({
                    "league": league,
                    "match": match_name,
                    "kick_utc": kick_utc,
                    "time": game.get("time", vn_time(kick_utc)),
                    "channels": channel_sources,
                    "source": "love4vn"
                })
    return games

# ================== MERGE ==================
def merge_games(games_list: List[Dict]) -> List[Dict]:
    merged = []
    used = set()
    for i, g in enumerate(games_list):
        if i in used:
            continue
        base = g.copy()
        base_match_norm = normalize(base['match'])
        for j, other in enumerate(games_list[i+1:], i+1):
            if j in used:
                continue
            if base['league'] != other['league']:
                continue
            if abs(base['kick_utc'] - other['kick_utc']) > 300:
                continue
            match_norm = normalize(other['match'])
            if similar(base_match_norm, match_norm) < 0.8:
                continue
            if 'channels' in base and 'channels' in other:
                if isinstance(base['channels'][0], str):
                    base['channels'] = [{"country_code": extract_country_from_channel_name(ch), "channel_name": ch} for ch in base['channels']]
                if isinstance(other['channels'][0], str):
                    other_channels = [{"country_code": extract_country_from_channel_name(ch), "channel_name": ch} for ch in other['channels']]
                else:
                    other_channels = other['channels']
                existing_keys = {(c['country_code'], c['channel_name']) for c in base['channels']}
                for c in other_channels:
                    key = (c['country_code'], c['channel_name'])
                    if key not in existing_keys:
                        base['channels'].append(c)
                        existing_keys.add(key)
            used.add(j)
        merged.append(base)
        used.add(i)
    return merged

# ================== M3U PARSER ==================
def parse_m3u(content):
    channels = []
    current = None
    extra = []
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            if current is not None and current.get('name') and current.get('url'):
                if extra:
                    current['extra'] = extra[:]
                channels.append(current)
            if '###' in line:
                current = None
                extra = []
                continue
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current = {'params': {k.lower(): v for k, v in params}}
            parts = line.split(',')
            if len(parts) > 1:
                current['name'] = parts[-1].strip()
            else:
                current['name'] = "Unknown"
            if '###' in current['name']:
                current = None
                extra = []
                continue
            extra = []
        elif line.startswith('http'):
            if current is not None and current.get('name'):
                current['url'] = line
                if extra:
                    current['extra'] = extra[:]
                channels.append(current)
                current = None
                extra = []
        elif line.startswith('#EXTVLCOPT'):
            if current is not None:
                extra.append(line)
        elif line.startswith('#'):
            extra.append(line)
    if current is not None and current.get('name') and current.get('url'):
        if extra:
            current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== TỐI ƯU MATCH KÊNH ==================
def build_channel_index(channels: List[Dict]) -> Dict[str, List[Dict]]:
    index = {}
    for ch in channels:
        _, clean = extract_prefix_and_name(ch['name'])
        norm_name = normalize_channel_name(clean)
        if norm_name not in index:
            index[norm_name] = []
        index[norm_name].append(ch)
        # Thêm tên gốc viết thường để fallback
        if ch['name'].lower() not in index:
            index[ch['name'].lower()] = []
        index[ch['name'].lower()].append(ch)
    return index

def match_channel_fast(target_name: str, target_country: Optional[str], channel_index: Dict[str, List[Dict]], league: str = None) -> List[Dict]:
    matched = []
    _, target_clean = extract_prefix_and_name(target_name)
    target_norm = normalize_channel_name(target_clean)
    if target_norm in channel_index:
        for ch in channel_index[target_norm]:
            if target_country:
                m3u_code, _ = extract_prefix_and_name(ch['name'])
                if m3u_code == target_country:
                    matched.append(ch)
            else:
                matched.append(ch)
    if matched:
        return matched
    # Duyệt toàn bộ nếu không có chính xác
    threshold = 0.85 if league == "Tennis" else 0.95
    for ch_list in channel_index.values():
        for ch in ch_list:
            m3u_code, m3u_clean = extract_prefix_and_name(ch['name'])
            m3u_norm = normalize_channel_name(m3u_clean)
            if target_country:
                if m3u_code != target_country:
                    continue
                if similar(target_norm, m3u_norm) >= 0.9:
                    matched.append(ch)
            else:
                if similar(target_norm, m3u_norm) >= threshold:
                    matched.append(ch)
            if len(matched) > 50:
                break
    return matched

# ================== STREAM VALIDATION ==================
def extract_headers_from_extra(extra_lines: List[str]) -> Dict:
    headers = {}
    for line in extra_lines:
        if line.startswith('#EXTVLCOPT:http-user-agent='):
            ua = line.split('=', 1)[1].strip()
            headers['User-Agent'] = ua
        elif line.startswith('#EXTVLCOPT:http-cookie='):
            cookie = line.split('=', 1)[1].strip()
            headers['Cookie'] = cookie
        elif line.startswith('#EXTVLCOPT:http-header=Authorization:'):
            auth = line.split(':', 1)[1].strip()
            headers['Authorization'] = auth
    return headers

def validate_url_sync(url: str, extra_headers: Dict = None) -> Tuple[bool, Optional[str]]:
    if url.startswith("udp://"):
        return True, None
    url_lower = url.lower()
    if "cinehub24.com" in url_lower or url_lower.endswith(".mp4") or ".mp4?" in url_lower:
        return False, "Blacklisted"
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', USER_AGENT)
        req.add_header('Accept', 'video/*, application/vnd.apple.mpegurl, */*')
        req.add_header('Accept-Language', 'en-US,en;q=0.9,vi;q=0.8')
        req.add_header('Range', 'bytes=0-1024')
        if extra_headers:
            for k, v in extra_headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=VALIDATION_TIMEOUT) as resp:
            status = resp.getcode()
            body = resp.read(20000).decode('utf-8', errors='ignore')
            if status in (200, 206):
                if ".m3u8" in url:
                    if "#EXTM3U" in body or "#EXTINF" in body:
                        return True, None
                    else:
                        return False, "Invalid HLS"
                else:
                    if "<html" in body.lower() or "<body" in body.lower():
                        if "401" in body or "unauthorized" in body.lower():
                            return False, "HTTP 401 Unauthorized"
                        if "access denied" in body.lower():
                            return False, "Access Denied"
                        return False, "HTML error"
                    else:
                        return True, None
            else:
                return False, f"HTTP {status}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "HTTP 401 Unauthorized"
        elif e.code == 403:
            return False, "HTTP 403 Forbidden"
        elif e.code == 404:
            return False, "HTTP 404 Not Found"
        else:
            return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return False, "Timeout"
        else:
            return False, f"URL error: {str(e.reason)}"
    except Exception as e:
        return False, f"Error: {str(e)}"

def validate_events_batch(events: List[Dict]) -> List[Dict]:
    if not events:
        return []
    print(f"\n🔬 Bắt đầu kiểm tra {len(events)} luồng (concurrent={VALIDATION_CONCURRENT}, timeout={VALIDATION_TIMEOUT}s)...")
    valid_events = []
    with ThreadPoolExecutor(max_workers=VALIDATION_CONCURRENT) as executor:
        future_to_event = {}
        for ev in events:
            extra_headers = extract_headers_from_extra(ev['channel'].get('extra', []))
            future = executor.submit(validate_url_sync, ev['channel']['url'], extra_headers)
            future_to_event[future] = ev
        for future in as_completed(future_to_event):
            event = future_to_event[future]
            try:
                is_valid, error = future.result()
                if is_valid:
                    valid_events.append(event)
                else:
                    print(f"   ❌ Bỏ kênh: {event['name'][:80]} - {error}")
            except Exception as e:
                print(f"   ❌ Bỏ kênh (lỗi): {event['name'][:80]} - {str(e)}")
    print(f"   ✅ Kết thúc kiểm tra: {len(valid_events)}/{len(events)} luồng hợp lệ")
    return valid_events

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_ts_utc = int(now_utc.timestamp())
    start_ts_utc = now_ts_utc - 7200
    end_ts_utc = now_ts_utc + 86400

    print("🔄 Bắt đầu lấy lịch (lùi 2h đến 24h tới)...")
    all_games = []

    print("📡 Đang tải footonsat...")
    footonsat_games = []
    for url in FOOTONSAT_URLS:
        print(f"   Đang tải {url}")
        data = fetch_footonsat_json(url)
        if data:
            games = parse_footonsat_data(data)
            footonsat_games.extend(games)
    footonsat_games = [g for g in footonsat_games if start_ts_utc <= g['kick_utc'] <= end_ts_utc]
    print(f"   Footonsat: {len(footonsat_games)} trận")
    all_games.extend(footonsat_games)

    print("📡 Đang tải Love4VN...")
    love4vn_data = fetch_love4vn_json()
    love4vn_games = parse_love4vn_data(love4vn_data, start_ts_utc, end_ts_utc) if love4vn_data else []
    print(f"   Love4VN: {len(love4vn_games)} trận")
    all_games.extend(love4vn_games)

    all_games = merge_games(all_games)
    print(f"✅ Tổng số trận sau merge: {len(all_games)}")

    if not all_games:
        print("⚠️ Không có trận nào. Thoát.")
        return

    print("   📋 Danh sách trận:")
    for g in all_games:
        print(f"      {g['time']} | {g['league']} | {g['match']} (nguồn: {g.get('source','merged')})")

    filtered = []
    for g in all_games:
        kick_vn = datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE)
        if kick_vn > vn_now - timedelta(hours=2):
            filtered.append(g)
    all_games = filtered
    print(f"   ✅ Sau lọc (chưa kết thúc quá 2h): {len(all_games)} trận")

    if not all_games:
        print("⚠️ Không có trận nào sau lọc. Thoát.")
        return

    print("📥 Đang tải M3U...")
    m3u_links = []
    try:
        with open(M3U_LIST_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('http'):
                    m3u_links.append(line)
        print(f"   📋 Tìm thấy {len(m3u_links)} URL")
    except Exception as e:
        print(f"   ❌ Lỗi đọc M3U_list.txt: {e}")

    def fetch_text_sync(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"   Lỗi tải {url[:50]}...: {e}")
            return None

    all_ch = []
    if m3u_links:
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_text_sync, url): url for url in m3u_links}
            for fut in as_completed(futures):
                content = fut.result()
                if content:
                    chs = parse_m3u(content)
                    for ch in chs:
                        if is_low_resolution(ch.get('name', '')):
                            continue
                        all_ch.append(ch)
    else:
        print("   ⚠️ Không có link M3U")

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    print(f"   ✅ Đã tải {len(unique_ch)} kênh")
    print("   📺 50 kênh đầu tiên:")
    for i, ch in enumerate(unique_ch[:50]):
        print(f"      {i+1}. {ch['name']}")

    # Xây dựng index
    print("🔄 Xây dựng index kênh...")
    channel_index = build_channel_index(unique_ch)
    print(f"   ✅ Index có {len(channel_index)} keys")

    print("🔄 Đang match kênh...")
    live_events = []
    for g in all_games:
        used_urls = set()
        channels_info = g.get('channels', [])
        for ch_info in channels_info:
            if isinstance(ch_info, str):
                target_country = None
                target_name = ch_info
            else:
                target_country = ch_info.get('country_code')
                target_name = ch_info.get('channel_name')
            if not target_name:
                continue
            matching = match_channel_fast(target_name, target_country, channel_index, g['league'])
            if matching:
                print(f"   ✅ Match: {g['match']} - {target_name} (country={target_country}) -> {len(matching)} kênh")
            for ch in matching:
                if ch['url'] in used_urls:
                    continue
                used_urls.add(ch['url'])
                display_name = f"{g['time']} | {g['match']}"
                if target_name:
                    display_name += f" ({target_name})"
                live_events.append({
                    "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                    "name": display_name,
                    "channel": ch,
                    "league": g["league"]
                })

    seen = {}
    dedup = []
    for ev in live_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in seen:
            seen[key] = ev
            dedup.append(ev)
    live_events = dedup
    live_events.sort(key=lambda x: x["datetime"])

    if SKIP_VALIDATION:
        print("\n⚠️ Bỏ qua kiểm tra luồng (--skip-validation)")
    else:
        print(f"\n📊 Tổng số kênh sau khi match (chưa kiểm tra): {len(live_events)}")
        live_events = validate_events_batch(live_events)

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group = LEAGUE_GROUP_NAME.get(ev["league"])
            if not group:
                continue
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group}"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'):
                        f.write(line + "\n")
            f.write(ch['url'] + "\n")

    print(f"\n🎉 HOÀN THÀNH! {len(live_events)} kênh hợp lệ trong {LIVE_M3U}")

if __name__ == "__main__":
    asyncio.run(main())
