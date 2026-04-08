"""
footonsat_schedule_live.py
================================
LẤY LỊCH TRỰC TIẾP TỪ footonsat-api VÀ Love4vn/Live-Schedue
Tích hợp M3U với matching thông minh (tách mã quốc gia)
KIỂM TRA LINK STREAM CÒN SỐNG TRƯỚC KHI XUẤT FILE
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple, Any
import aiohttp
from aiohttp import ClientTimeout, ClientSession

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
LIVE_M3U = "live_schedule.m3u"

# Cấu hình validation
VALIDATION_CONCURRENT = 50      # Số lượng request đồng thời
VALIDATION_TIMEOUT = 5          # Timeout mỗi request (giây)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Danh sách giải tennis được phép
ALLOWED_TENNIS_TOURNAMENTS = {
    "atp", "atp tour", "atp world tour", "grand slam", "australian open",
    "roland garros", "french open", "wimbledon", "us open", "nitto atp finals",
    "atp masters", "atp 1000", "atp 500", "atp 250", "monte carlo",
    "linz", "upper austria"
}

# Danh sách các giải bóng đá được phép
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup"
}

# Danh sách đội Premier League
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

# Mã quốc gia thường gặp
COUNTRY_CODES = {
    "uk", "us", "fr", "de", "it", "es", "pt", "nl", "be", "ch", "at",
    "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "bg", "gr", "tr",
    "il", "au", "ca", "nz", "ie", "gb", "en", "vn", "kr", "jp", "cn",
    "br", "ar", "mx", "in", "za", "ru", "ua", "rs", "hr", "si", "sk", "ie"
}

COUNTRY_NAME_TO_CODE = {
    "united states": "us", "usa": "us", "uk": "uk", "united kingdom": "uk",
    "viet nam": "vn", "vietnam": "vn", "korea, republic of": "kr", "south korea": "kr",
    "japan": "jp", "china": "cn", "brazil": "br", "argentina": "ar", "mexico": "mx",
    "india": "in", "south africa": "za", "russia": "ru", "ukraine": "ua",
    "serbia": "rs", "croatia": "hr", "slovenia": "si", "slovakia": "sk",
    "france": "fr", "germany": "de", "italy": "it", "spain": "es", "portugal": "pt",
    "netherlands": "nl", "belgium": "be", "switzerland": "ch", "austria": "at",
    "sweden": "se", "norway": "no", "denmark": "dk", "finland": "fi", "poland": "pl",
    "czechia": "cz", "hungary": "hu", "romania": "ro", "bulgaria": "bg", "greece": "gr",
    "turkey": "tr", "israel": "il", "australia": "au", "canada": "ca", "new zealand": "nz",
    "ireland": "ie", "indonesia": "id", "malaysia": "my", "singapore": "sg", "thailand": "th",
    "egypt": "eg", "morocco": "ma", "algeria": "dz", "tunisia": "tn", "libya": "ly",
    "sudan": "sd", "ethiopia": "et", "kenya": "ke", "nigeria": "ng", "ghana": "gh",
    "senegal": "sn", "côte d'ivoire": "ci", "cameroon": "cm", "angola": "ao"
}

# URL nguồn footonsat
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
    name = re.sub(r'\b(hd|uhd|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc)\b', '', name)
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
    return False

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    if not ch_name or not m3u_name:
        return False
    ch_code, ch_clean = extract_prefix_and_name(ch_name)
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    ch_norm = normalize_channel_name(ch_clean)
    m3u_norm = normalize_channel_name(m3u_clean)
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
        return similar(ch_norm, m3u_norm) >= 0.95

def is_channel_match_with_country(m3u_name: str, target_country_code: Optional[str], target_channel_name: str) -> bool:
    if not m3u_name or not target_channel_name:
        return False
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    m3u_norm = normalize_channel_name(m3u_clean)
    target_norm = normalize_channel_name(target_channel_name)
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
        return similar(m3u_norm, target_norm) >= 0.95

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

# ================== LỌC GIẢI ĐẤU & ĐỘI ==================
def is_tennis_allowed(match_name: str) -> bool:
    if not match_name:
        return False
    match_lower = match_name.lower()
    for keyword in ALLOWED_TENNIS_TOURNAMENTS:
        if keyword in match_lower:
            return True
    return False

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
                            channels.append(ch_name)
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
                if not is_tennis_allowed(match_name):
                    continue
            else:
                if not is_football_allowed(league, match_name):
                    continue

            channel_sources = []
            tv_channels = game.get("tv_channels", [])
            for entry in tv_channels:
                country_name = entry.get("country", "")
                channels_list = entry.get("channels", [])
                non_country_names = {"wheresthematch", "livesportsontv", "ausport"}
                if country_name.lower() in non_country_names:
                    country_code = None
                    for ch_name in channels_list:
                        if ch_name:
                            channel_sources.append({
                                "country_code": country_code,
                                "channel_name": ch_name
                            })
                else:
                    country_code = get_country_code_from_name(country_name)
                    for ch_name in channels_list:
                        if not ch_name:
                            continue
                        cleaned_name = remove_country_from_channel_name(ch_name, country_name)
                        channel_sources.append({
                            "country_code": country_code,
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

# ================== MERGE CÁC TRÙNG NHAU ==================
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
                if base.get('source') == 'footonsat' and isinstance(base['channels'][0], str):
                    base['channels'] = [{"country_code": None, "channel_name": ch} for ch in base['channels']]
                if other.get('source') == 'footonsat' and isinstance(other['channels'][0], str):
                    other_channels = [{"country_code": None, "channel_name": ch} for ch in other['channels']]
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
    current = {}
    extra = []
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            if current.get('name') and current.get('url'):
                if extra:
                    current['extra'] = extra[:]
                channels.append(current)
            current = {}
            extra = []
            params = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
            current['params'] = {k.lower(): v for k, v in params}
            parts = line.split(',')
            if len(parts) > 1:
                current['name'] = parts[-1].strip()
            else:
                current['name'] = "Unknown"
        elif line.startswith('http'):
            if current:
                current['url'] = line
                if extra:
                    current['extra'] = extra[:]
                channels.append(current)
                current = {}
                extra = []
        elif line.startswith('#'):
            extra.append(line)
    if current.get('name') and current.get('url'):
        if extra:
            current['extra'] = extra[:]
        channels.append(current)
    return channels

# ================== STREAM VALIDATION ==================
def is_url_blacklisted(url: str) -> bool:
    """Kiểm tra URL có nằm trong danh sách đen không (dựa theo main.rs)"""
    url_lower = url.lower()
    if "cinehub24.com" in url_lower:
        return True
    if url_lower.endswith(".mp4") or ".mp4?" in url_lower:
        return True
    return False

async def validate_url(session: ClientSession, url: str, timeout_sec: int = VALIDATION_TIMEOUT) -> Tuple[bool, Optional[str]]:
    """Kiểm tra một URL stream có hoạt động không. Trả về (is_valid, error_message)."""
    if url.startswith("udp://"):
        return True, None
    if is_url_blacklisted(url):
        return False, "Blacklisted (cinehub24/.mp4)"
    try:
        timeout = ClientTimeout(total=timeout_sec)
        # Dùng GET với Range: bytes=0-1024 để chỉ tải đầu file
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "video/*, application/vnd.apple.mpegurl, */*",
            "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
            "Range": "bytes=0-1024"
        }
        async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as resp:
            status = resp.status
            # Đọc một phần body để kiểm tra nội dung lỗi
            body = await resp.text() if resp.content_length and resp.content_length < 20000 else ""
            # Kiểm tra status thành công
            if status in (200, 206):
                # Với HLS, cần kiểm tra nội dung có phải playlist không
                if ".m3u8" in url:
                    if "#EXTM3U" in body or "#EXTINF" in body:
                        return True, None
                    else:
                        return False, "Invalid HLS playlist"
                else:
                    # Kiểm tra body có chứa HTML lỗi không
                    if "<html" in body.lower() or "<body" in body.lower():
                        # Tìm thông báo lỗi
                        error_msg = extract_html_error(body)
                        if error_msg:
                            return False, error_msg
                        else:
                            return False, "Server returned HTML instead of stream"
                    else:
                        return True, None
            else:
                # Status lỗi
                error_msg = extract_error_from_body(body)
                if not error_msg:
                    error_msg = f"HTTP {status}"
                return False, error_msg
    except asyncio.TimeoutError:
        return False, "Timeout"
    except Exception as e:
        return False, f"Request error: {str(e)}"

def extract_error_from_body(body: str) -> Optional[str]:
    lower_body = body.lower()
    error_keywords = [
        "access denied", "geo-blocked", "geo blocked", "unauthorized",
        "forbidden", "not authorized", "401", "403", "this page isn’t working",
        "http error 401", "error", "invalid request", "not found"
    ]
    if any(kw in lower_body for kw in error_keywords):
        for line in body.splitlines():
            l = line.lower()
            if any(kw in l for kw in error_keywords):
                return line.strip()
        return "Access denied/Geo-blocked"
    return None

def extract_html_error(body: str) -> Optional[str]:
    lower = body.lower()
    if "401" in lower or "unauthorized" in lower or "access denied" in lower:
        for line in body.splitlines():
            l = line.lower()
            if "401" in l or "unauthorized" in l or "access denied" in l:
                return line.strip()
        return "HTTP 401 Unauthorized"
    return None

async def validate_events_batch(events: List[Dict]) -> List[Dict]:
    """Kiểm tra tất cả các event (mỗi event chứa channel['url']) và chỉ giữ event có URL hợp lệ."""
    if not events:
        return []
    print(f"\n🔬 Bắt đầu kiểm tra {len(events)} luồng (concurrent={VALIDATION_CONCURRENT}, timeout={VALIDATION_TIMEOUT}s)...")
    connector = aiohttp.TCPConnector(limit=VALIDATION_CONCURRENT, ttl_dns_cache=300)
    async with ClientSession(connector=connector) as session:
        semaphore = asyncio.Semaphore(VALIDATION_CONCURRENT)
        async def check_one(event):
            url = event['channel']['url']
            async with semaphore:
                is_valid, error = await validate_url(session, url)
                return event, is_valid, error
        tasks = [check_one(ev) for ev in events]
        results = await asyncio.gather(*tasks)
    valid_events = []
    for event, is_valid, error in results:
        if is_valid:
            valid_events.append(event)
        else:
            print(f"   ❌ Bỏ kênh: {event['name'][:80]} - {error}")
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

    # Footonsat
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

    # Love4VN
    print("📡 Đang tải Love4VN...")
    love4vn_data = fetch_love4vn_json()
    love4vn_games = parse_love4vn_data(love4vn_data, start_ts_utc, end_ts_utc) if love4vn_data else []
    print(f"   Love4VN: {len(love4vn_games)} trận")
    all_games.extend(love4vn_games)

    # Merge
    all_games = merge_games(all_games)
    print(f"✅ Tổng số trận sau merge: {len(all_games)}")

    if not all_games:
        print("⚠️ Không có trận nào. Thoát.")
        return

    print("   📋 Danh sách trận:")
    for g in all_games:
        print(f"      {g['time']} | {g['league']} | {g['match']} (nguồn: {g.get('source','merged')})")

    # Lọc trận chưa kết thúc quá 2h
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

    # Tải M3U
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

    # Matching
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
            matching = []
            for ch in unique_ch:
                if target_country is not None:
                    if is_channel_match_with_country(ch['name'], target_country, target_name):
                        matching.append(ch)
                else:
                    if is_channel_match(target_name, ch['name']):
                        matching.append(ch)
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

    # Loại trùng kênh (cùng url và league)
    seen = {}
    dedup = []
    for ev in live_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in seen:
            seen[key] = ev
            dedup.append(ev)
    live_events = dedup
    live_events.sort(key=lambda x: x["datetime"])

    # ========== BỔ SUNG: KIỂM TRA LUỒNG TRƯỚC KHI GHI FILE ==========
    print(f"\n📊 Tổng số kênh sau khi match (chưa kiểm tra): {len(live_events)}")
    live_events = await validate_events_batch(live_events)

    # Ghi file M3U chỉ với các kênh hợp lệ
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
