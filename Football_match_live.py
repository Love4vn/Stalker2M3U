"""
Football_match_live.py - Simple football match-based M3U generator.
Matches games by match name only (ignoring JSON channels).
Outputs Football_match_live.m3u.
"""

import asyncio
import json
import re
import unicodedata
import urllib.request
import urllib.error
import time
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Set, Tuple

# ================== CONFIG ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
OUTPUT_M3U = "Football_match_live.m3u"
CACHE_FILE = ".m3u_cache.json"
CACHE_EXPIRY = 3600

VALIDATION_CONCURRENT = 50
VALIDATION_TIMEOUT = 2
USER_AGENT = "Mozilla/5.0"
SKIP_VALIDATION = "--skip-validation" in sys.argv
M3U_FETCH_WORKERS = 40

# ================== FOOTBALL LEAGUES ==================
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup"
}

LEAGUE_MAPPING = {
    "english premier league": "Premier League",
    "serie a": "Serie A",
    "la liga": "La Liga",
    "bundesliga": "Bundesliga",
    "ligue 1": "Ligue 1",
    "uefa champions league": "UEFA Champions League",
    "uefa europa league": "UEFA Europa League",
    "uefa conference league": "UEFA Europa Conference League",
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": {"arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
                       "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
                       "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
                       "west ham united", "wolverhampton"},
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": {"barcelona", "real madrid", "atletico madrid"},
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "olympique marseille", "marseille"},
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

LEAGUE_GROUP_NAME = {
    "Premier League": "⚽️🏴󠁧󠁢󠁥󠁮󠁧󠁿|Live Premier League",
    "Serie A": "⚽️🇮🇹|Live Serie A",
    "Bundesliga": "⚽️🇩🇪|Live Bundesliga",
    "La Liga": "⚽️🇪🇦|Live La Liga",
    "Ligue 1": "⚽️🇨🇵|Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
    "UEFA Euro": "Live Euro",
    "FA Cup": "Live FA, League Cup",
    "League Cup": "Live FA, League Cup",
}

# ================== CACHE ==================
class CacheManager:
    @staticmethod
    def get_cache() -> Optional[List[Dict]]:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if time.time() - data.get('timestamp', 0) < CACHE_EXPIRY:
                        return data.get('channels', [])
        except:
            pass
        return None

    @staticmethod
    def save_cache(channels: List[Dict]):
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': time.time(),
                    'channels': channels
                }, f)
        except:
            pass

# ================== HELPERS ==================
def normalize(s: str) -> str:
    """Remove accents, lower case."""
    s_lower = s.lower()
    s_nfd = unicodedata.normalize("NFD", s_lower)
    return "".join(c for c in s_nfd if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

def is_football_allowed(league: str, match_name: str) -> bool:
    if league not in ALLOWED_FOOTBALL_LEAGUES:
        return False
    if league in ALLOWED_TEAMS_PER_LEAGUE:
        allowed_teams = ALLOWED_TEAMS_PER_LEAGUE[league]
        match_lower = match_name.lower()
        return any(team in match_lower for team in allowed_teams)
    return True

def clean_channel_name_for_match(name: str) -> str:
    """Clean channel name for matching purposes."""
    # Remove quality tags, special chars
    name = re.sub(r'\b(?:hd|fhd|uhd|4k|8k|hevc|sd|full hd|ultra hd|hdr|raw)\b', '', name, flags=re.I)
    name = re.sub(r'[^\w\s]', ' ', name)  # Replace punctuation with space
    name = ' '.join(name.split())
    return name.strip()

def remove_datetime_from_channel_name(channel_name: str) -> str:
    """
    Remove date/time patterns from channel name to avoid redundancy.
    Examples: "Apr 15 8:50 PM", "2026-04-15", "Wed 15 Apr", "@ Apr 15 20:00", etc.
    Also remove leading/trailing separators like "|", ":".
    """
    # Patterns to remove
    patterns = [
        r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',  # Wed 15 Apr
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',  # 15 Apr
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b',  # Apr 15
        r'\b\d{4}-\d{2}-\d{2}\b',  # 2026-04-15
        r'\b\d{2}:\d{2}\s*(?:AM|PM|am|pm)?\b',  # 8:50 PM, 20:00
        r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b',
        r'@\s*\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{2}:\d{2}',  # @ Apr 15 20:00
        r'@\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?',  # @ 8:50 PM
        r'\|\s*\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s*\|',  # | 15 Apr 2026 |
        r'\|\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*\|',
    ]
    cleaned = channel_name
    for pat in patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.I)
    # Remove leftover separators and extra spaces
    cleaned = re.sub(r'\s*[@|:-]\s*', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def channel_priority(channel_name: str) -> int:
    """Priority: UK (0), English (1), others (2)."""
    name_lower = channel_name.lower()
    # UK indicators
    uk_pattern = r'\b(uk|gb|england|united kingdom)\b'
    if re.search(uk_pattern, name_lower) or name_lower.startswith('uk ') or name_lower.startswith('uk:'):
        return 0
    # English language indicators
    english_codes = {'us', 'ca', 'au', 'nz', 'ie', 'en'}
    code_match = re.search(r'(?:^|\|)([a-z]{2,3})(?:\||:|\s|$)', name_lower)
    if code_match:
        code = code_match.group(1)
        if code in english_codes:
            return 1
    if 'english' in name_lower:
        return 1
    return 2

# ================== HTTP ==================
async def fetch_json_async(url: str) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_json_sync, url)

def fetch_json_sync(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode('utf-8'))
    except:
        return None

def fetch_text_sync(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='ignore')
    except:
        return None

# ================== M3U PARSER ==================
def parse_m3u_fast(content: str) -> List[Dict]:
    channels = []
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line.startswith('#EXTINF'):
            if '###' in line:
                i += 1
                continue

            params = {}
            for k, v in re.findall(r'([a-zA-Z-]+)="([^"]*)"', line):
                params[k.lower()] = v

            parts = line.split(',')
            name = parts[-1].strip() if len(parts) > 1 else "Unknown"

            if re.search(r'[#=☰]', name):
                i += 1
                while i < len(lines) and not lines[i].strip().startswith('http'):
                    i += 1
                i += 1
                continue

            extra = []
            i += 1

            while i < len(lines) and not lines[i].strip().startswith('http'):
                extra_line = lines[i].strip()
                if extra_line.startswith('#EXTVLCOPT') or extra_line.startswith('#'):
                    extra.append(extra_line)
                i += 1

            if i < len(lines):
                url = lines[i].strip()
                if url.startswith('http'):
                    channels.append({
                        'name': name,
                        'url': url,
                        'params': params,
                        'extra': extra if extra else None
                    })
            i += 1
        else:
            i += 1

    return channels

# ================== FOOTONSAT PARSER ==================
def parse_footonsat_data(data: dict, start_ts: int, end_ts: int) -> List[Dict]:
    games = []
    if not data or "footonsat" not in data or not isinstance(data["footonsat"], list):
        return games

    items = data["footonsat"]
    i = 0

    while i < len(items):
        item = items[i]
        if not isinstance(item, dict) or "match" not in item:
            i += 1
            continue

        compet = (item.get("compet") or "").lower()
        league = None
        for key, val in LEAGUE_MAPPING.items():
            if key in compet:
                league = val
                break

        if not league or league not in ALLOWED_FOOTBALL_LEAGUES:
            i += 1
            continue

        try:
            date_str = item.get("date")
            time_str = item.get("time")
            if not date_str or not time_str:
                i += 1
                continue

            dt_utc = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
            kick_utc = int(dt_utc.timestamp())

            if kick_utc < start_ts or kick_utc > end_ts:
                i += 1
                continue

            match_name = item.get("match", "").strip()
            if not match_name:
                i += 1
                continue
            if not is_football_allowed(league, match_name):
                i += 1
                continue

            games.append({
                "league": league,
                "match": match_name,
                "kick_utc": kick_utc,
                "time": vn_time(kick_utc),
                "source": "footonsat"
            })
            j = i + 1
            while j < len(items):
                next_item = items[j]
                if isinstance(next_item, dict) and "match" in next_item:
                    break
                j += 1
            i = j
        except:
            i += 1

    return games

# ================== LOVE4VN PARSER ==================
def parse_love4vn_data(data: dict, start_ts: int, end_ts: int) -> List[Dict]:
    games = []
    if not data or "days" not in data:
        return games

    for day_info in data["days"].values():
        for game in day_info.get("games", []):
            kick_utc = game.get("kick_utc")
            if not kick_utc or kick_utc < start_ts or kick_utc > end_ts:
                continue

            league = game.get("league", "")
            match_name = game.get("match", "").strip()
            
            if league not in ALLOWED_FOOTBALL_LEAGUES:
                continue
            if not match_name:
                continue
            if not is_football_allowed(league, match_name):
                continue

            games.append({
                "league": league,
                "match": match_name,
                "kick_utc": kick_utc,
                "time": game.get("time", vn_time(kick_utc)),
                "source": "love4vn"
            })

    return games

# ================== VALIDATION ==================
def validate_url_sync(url: str) -> Tuple[bool, Optional[str]]:
    if url.startswith("udp://"):
        return True, None

    url_lower = url.lower()
    if "cinehub24.com" in url_lower or url_lower.endswith(".mp4"):
        return False, "Blacklisted"

    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', USER_AGENT)
        req.add_header('Range', 'bytes=0-1024')

        with urllib.request.urlopen(req, timeout=VALIDATION_TIMEOUT) as resp:
            if resp.getcode() not in (200, 206):
                return False, f"HTTP {resp.getcode()}"

            if '.m3u8' in url:
                body = resp.read(5000).decode('utf-8', errors='ignore')
                return "#EXTM3U" in body or "#EXTINF" in body, "Invalid HLS"

            return True, None
    except:
        return False, "Error"

async def validate_events_batch(events: List[Dict]) -> List[Dict]:
    if not events:
        return []

    print(f"\n🔬 Kiểm tra {len(events)} kênh (concurrent={VALIDATION_CONCURRENT})...")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=VALIDATION_CONCURRENT) as executor:
        tasks = [
            loop.run_in_executor(executor, validate_url_sync, ev['channel']['url'])
            for ev in events
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid_events = [
            ev for ev, result in zip(events, results)
            if result and result[0] is True
        ]

    print(f"   ✅ {len(valid_events)}/{len(events)} hợp lệ")
    return valid_events

# ================== MATCHING IMPROVED ==================
def build_flexible_match_condition(match_name: str):
    """
    Return a function that checks if a given string contains both teams
    in a flexible way (allowing common separators and word boundaries).
    """
    # Normalize match name
    norm_match = normalize(match_name)
    # Split by common separators
    parts = re.split(r'\s+(?:vs|v|[-@])\s+', norm_match, flags=re.I)
    if len(parts) < 2:
        # Fallback: look for the whole phrase
        def _match(s):
            return norm_match in normalize(s)
        return _match

    team1 = parts[0].strip()
    team2 = parts[1].strip()
    
    # For team2, also allow common suffixes like "CP", "Lisbon" to be optional
    # We'll create patterns that are flexible
    # We'll search for both team names independently with word boundaries
    def _match(s: str) -> bool:
        s_norm = normalize(s)
        # Check if both team1 and team2 appear in s_norm
        # Use word boundaries
        pattern1 = re.compile(r'\b' + re.escape(team1) + r'\b', re.I)
        pattern2 = re.compile(r'\b' + re.escape(team2) + r'\b', re.I)
        return bool(pattern1.search(s_norm) and pattern2.search(s_norm))
    return _match

# ================== MAIN ==================
async def main():
    start = time.time()

    now_utc = datetime.now(ZoneInfo("UTC"))
    now_ts = int(now_utc.timestamp())
    start_ts = now_ts - 7200
    end_ts = now_ts + 86400

    print("🔄 Bắt đầu...")

    print("📡 Tải APIs...")
    footonsat_tasks = [fetch_json_async(url) for url in FOOTONSAT_URLS]
    love4vn_task = fetch_json_async(LOVE4VN_URL)

    footonsat_results = await asyncio.gather(*footonsat_tasks)
    love4vn_data = await love4vn_task

    all_games = []
    for data in footonsat_results:
        if data:
            all_games.extend(parse_footonsat_data(data, start_ts, end_ts))

    if love4vn_data:
        all_games.extend(parse_love4vn_data(love4vn_data, start_ts, end_ts))

    print(f"✅ Tổng: {len(all_games)} trận bóng đá")
    if not all_games:
        print("⚠️ Không có trận nào.")
        return

    print("📥 Tải M3U...")
    cached = CacheManager.get_cache()

    if cached:
        print(f"   Từ cache: {len(cached)} kênh")
        channels = cached
    else:
        m3u_links = []
        try:
            with open(M3U_LIST_FILE, 'r', encoding='utf-8') as f:
                m3u_links = [line.strip() for line in f if line.strip().startswith('http')]
        except:
            pass

        print(f"   {len(m3u_links)} URLs")

        loop = asyncio.get_event_loop()
        all_channels = []

        batch_size = M3U_FETCH_WORKERS
        for i in range(0, len(m3u_links), batch_size):
            batch = m3u_links[i:i+batch_size]
            with ThreadPoolExecutor(max_workers=M3U_FETCH_WORKERS) as ex:
                contents = await asyncio.gather(*[
                    loop.run_in_executor(ex, fetch_text_sync, url)
                    for url in batch
                ])

            for content in contents:
                if content:
                    parsed = parse_m3u_fast(content)
                    all_channels.extend(parsed)

            print(f"      {min(i + batch_size, len(m3u_links))}/{len(m3u_links)}")

        channels = list({ch['url']: ch for ch in all_channels}.values())
        CacheManager.save_cache(channels)

    print(f"   ✅ {len(channels)} kênh")

    # Preprocess channel names for matching
    for ch in channels:
        ch['_clean_match'] = clean_channel_name_for_match(ch['name'])
        # Also store a version without date/time for display
        ch['_display_name'] = remove_datetime_from_channel_name(ch['name'])

    print("\n🔍 QUÁ TRÌNH MATCH THEO TÊN TRẬN:")

    live_events = []
    total_matched = 0

    for game in all_games:
        league = game['league']
        match_name = game['match']
        kick_utc = game['kick_utc']
        kick_time = game['time']

        print(f"\n🏆 [{league}] {match_name} | {kick_time}")

        # Build match condition function
        matcher = build_flexible_match_condition(match_name)

        matched_for_game = []
        seen_urls = set()

        for ch in channels:
            if matcher(ch['_clean_match']):
                url = ch['url']
                if url not in seen_urls:
                    seen_urls.add(url)
                    matched_for_game.append(ch)

        if matched_for_game:
            matched_for_game.sort(key=lambda ch: channel_priority(ch['name']))
            print(f"   ✅ Tìm thấy {len(matched_for_game)} kênh")
            for ch in matched_for_game:
                # Build display name: kick_time | cleaned_channel_name
                display_name = f"{kick_time} | {ch['_display_name']}"
                live_events.append({
                    "datetime": datetime.fromtimestamp(kick_utc).astimezone(TIMEZONE),
                    "name": display_name,
                    "channel": ch,
                    "league": league,
                })
            total_matched += len(matched_for_game)
        else:
            print("   ❌ Không tìm thấy kênh nào")

    print(f"\n📊 TỔNG KẾT: {total_matched} kênh được thêm")

    if not live_events:
        print("⚠️ Không có kênh nào để xuất.")
        return

    live_events.sort(key=lambda x: x["datetime"])

    if not SKIP_VALIDATION:
        live_events = await validate_events_batch(live_events)

    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            league = ev["league"]
            group = LEAGUE_GROUP_NAME.get(league, "Live Football")
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group}"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if ch.get('extra'):
                f.write('\n'.join(ch['extra']) + "\n")
            f.write(ch['url'] + "\n")

    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH! File: {OUTPUT_M3U} - {len(live_events)} kênh trong {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
