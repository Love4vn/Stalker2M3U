"""
footonsat_schedule_live_optimized.py - ULTRA OPTIMIZED VERSION
Cải tiến: Parallel M3U parsing, Faster string matching, Batch operations
+ Giữ tất cả kênh M3U khớp cho mỗi yêu cầu (khác link)
+ Phân biệt chống trùng link theo trận (bóng đá) hoặc toàn bộ tennis
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
from functools import lru_cache
from typing import List, Dict, Optional, Tuple, Set
import hashlib

# ================== CONFIG ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
LIVE_M3U = "live_schedule_Optimize.m3u"
CACHE_FILE = ".m3u_cache.json"
CACHE_EXPIRY = 3600

VALIDATION_CONCURRENT = 50
VALIDATION_TIMEOUT = 2
USER_AGENT = "Mozilla/5.0"
SKIP_VALIDATION = "--skip-validation" in sys.argv
M3U_FETCH_WORKERS = 40
REGEX_COMPILE_CACHE = {}

# ================== PRE-COMPILED PATTERNS ==================
PATTERN_COUNTRY_CODE = [
    re.compile(r'^\|\s*([a-z]{2,3})\s*\|\s*', re.I),
    re.compile(r'^([a-z]{2,3})\:\s*', re.I),
    re.compile(r'^([a-z]{2,3})\s*-\s*', re.I),
    re.compile(r'^([a-z]{2,3})\|\s*', re.I),
    re.compile(r'^\[([a-z]{2,3})\]\s*', re.I),
    re.compile(r'^\(([a-z]{2,3})\)\s*', re.I),
]
PATTERN_QUALITY = re.compile(r'\b(hd|uhd|8k|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc|full hd|ultra hd)\b', re.I)
PATTERN_LOW_RES = re.compile(r'(sd|360p|480p|576p|low res|low quality)', re.I)
PATTERN_TIME = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|CET|EST|UTC|GMT)?)\b', re.I)
PATTERN_MONTH = re.compile(r'\b(apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\b', re.I)
PATTERN_TIME_WORD = re.compile(r'\b(?:today|tomorrow|yesterday)\b', re.I)
PATTERN_EXTINF = re.compile(r'#EXTINF:-1\s*(.*)')

# ================== CONSTANTS ==================
ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup"
}

COUNTRY_CODES: Set[str] = {
    "uk", "us", "fr", "de", "it", "es", "pt", "nl", "be", "ch", "at",
    "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "bg", "gr", "tr",
    "il", "au", "ca", "nz", "ie", "gb", "en", "vn", "kr", "jp", "cn",
    "br", "ar", "mx", "in", "za", "ru", "ua", "rs", "hr", "si", "sk", "am"
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
@lru_cache(maxsize=10000)
def normalize(s: str) -> str:
    """Normalize string for comparison (cached)"""
    s_lower = s.lower()
    s_nfd = unicodedata.normalize("NFD", s_lower)
    return "".join(c for c in s_nfd if unicodedata.category(c) != "Mn")

def vn_time(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
    return dt.strftime("%d/%m %I:%M %p")

@lru_cache(maxsize=5000)
def similar(a: str, b: str) -> float:
    """Quick similarity check - optimized Levenshtein"""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    
    len_a, len_b = len(a), len(b)
    if abs(len_a - len_b) > max(len_a, len_b) * 0.3:
        return 0.0
    
    dp = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        new_dp = [i]
        for j in range(1, len_b + 1):
            cost = 0 if a[i-1] == b[j-1] else 1
            new_dp.append(min(dp[j] + 1, new_dp[j-1] + 1, dp[j-1] + cost))
        dp = new_dp
    
    return 1 - (dp[-1] / max(len_a, len_b))

def extract_prefix_and_name(name: str) -> Tuple[Optional[str], str]:
    name_lower = name.lower()
    for pat in PATTERN_COUNTRY_CODE:
        m = pat.match(name_lower)
        if m:
            code = m.group(1)
            if code in COUNTRY_CODES:
                remaining = name_lower[m.end():].lstrip('|:-\\s ')
                return code, remaining.strip()
    cleaned = re.sub(r'^[\|\s\:\-]+', '', name_lower)
    return None, cleaned

def normalize_channel_name(name: str) -> str:
    _, name = extract_prefix_and_name(name)
    name = PATTERN_QUALITY.sub('', name)
    name = name.replace('plus', '+').replace(' and ', ' & ')
    name = re.sub(r'[^\w\s\+]', ' ', name)
    name = ' '.join(name.split())
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name.strip()

def is_low_resolution(name: str) -> bool:
    return bool(PATTERN_LOW_RES.search(name))

def is_channel_match(ch_name: str, m3u_name: str, league: str = None) -> bool:
    if not ch_name or not m3u_name:
        return False
    
    ch_code, ch_clean = extract_prefix_and_name(ch_name)
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    ch_norm = normalize_channel_name(ch_clean)
    m3u_norm = normalize_channel_name(m3u_clean)
    
    if ch_norm == m3u_norm:
        return True
    if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
        return ch_norm == m3u_norm
    if ch_code and m3u_code and ch_code != m3u_code:
        return False
    
    threshold = 0.85 if league == "Tennis" else 0.92
    return similar(ch_norm, m3u_norm) >= threshold

def is_football_allowed(league: str, match_name: str) -> bool:
    if league not in ALLOWED_FOOTBALL_LEAGUES:
        return False
    if league in ALLOWED_TEAMS_PER_LEAGUE:
        allowed_teams = ALLOWED_TEAMS_PER_LEAGUE[league]
        match_lower = match_name.lower()
        return any(team in match_lower for team in allowed_teams)
    return True

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
            
            if '###' in name:
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
        
        if not league:
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
            if not is_football_allowed(league, match_name):
                i += 1
                continue
            
            channels = []
            j = i + 1
            while j < len(items):
                next_item = items[j]
                if isinstance(next_item, dict) and "match" in next_item:
                    break
                if isinstance(next_item, dict) and "channel" in next_item:
                    ch_name = next_item.get("channel", "").replace('📺', '').strip()
                    if ch_name:
                        channels.append({
                            "country_code": None,
                            "channel_name": ch_name
                        })
                j += 1
            
            if channels:
                games.append({
                    "league": league,
                    "match": match_name,
                    "kick_utc": kick_utc,
                    "time": vn_time(kick_utc),
                    "channels": channels,
                    "source": "footonsat"
                })
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
            
            if league != "Tennis" and not is_football_allowed(league, match_name):
                continue
            
            channels = []
            for entry in game.get("tv_channels", []):
                for ch_name in entry.get("channels", []):
                    if ch_name:
                        channels.append({
                            "country_code": None,
                            "channel_name": ch_name
                        })
            
            if channels:
                games.append({
                    "league": league,
                    "match": match_name,
                    "kick_utc": kick_utc,
                    "time": game.get("time", vn_time(kick_utc)),
                    "channels": channels,
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

# ================== MAIN ==================
async def main():
    start = time.time()
    
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_ts = int(now_utc.timestamp())
    start_ts = now_ts - 7200
    end_ts = now_ts + 86400
    
    print("🔄 Bắt đầu...")
    
    # Fetch APIs
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
    
    print(f"✅ Tổng: {len(all_games)} trận")
    if not all_games:
        print("⚠️ Không có trận nào.")
        return
    
    # Load M3U
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
                    all_channels.extend([ch for ch in parsed if not is_low_resolution(ch.get('name', ''))])
            
            print(f"      {min(i + batch_size, len(m3u_links))}/{len(m3u_links)}")
        
        channels = list({ch['url']: ch for ch in all_channels}.values())
        CacheManager.save_cache(channels)
    
    print(f"   ✅ {len(channels)} kênh")
    
    # ================== MATCH WITH NEW RULES ==================
    print("\n🔍 QUÁ TRÌNH MATCH KÊNH (giữ tất cả kênh khớp, chống trùng theo quy tắc):")
    
    # Data structures for duplicate prevention
    used_urls_per_match = defaultdict(set)   # key = match_key (league, match, kick_utc)
    used_urls_tennis = set()                 # for all tennis matches
    
    live_events = []
    total_requested_channels = 0
    total_matched_entries = 0
    
    # Pre-calculate normalized names for all M3U channels to speed up matching
    for ch in channels:
        if '_norm' not in ch:
            _, ch_clean = extract_prefix_and_name(ch['name'])
            ch['_norm'] = normalize_channel_name(ch_clean)
    
    for game in all_games:
        league = game['league']
        match_name = game['match']
        kick_utc = game['kick_utc']
        kick_time = game['time']
        
        # Define match_key (for football, unique per match; for tennis, we'll use a special key)
        if league == "Tennis":
            match_key = "TENNIS_ALL"  # all tennis share same key
        else:
            match_key = (league, match_name, kick_utc)
        
        print(f"\n🏆 [{league}] {match_name} | {kick_time} (UTC {kick_utc})")
        
        channels_from_json = game.get('channels', [])
        if not channels_from_json:
            print("   ⚠️  Không có kênh nào từ JSON")
            continue
        
        for ch_info in channels_from_json:
            target_name = ch_info.get('channel_name')
            if not target_name:
                continue
            
            total_requested_channels += 1
            print(f"   📡 Yêu cầu: {target_name}")
            
            # Find all matching M3U channels (similarity >= threshold)
            matching = []
            target_norm = normalize_channel_name(extract_prefix_and_name(target_name)[1])
            
            for ch in channels:
                if is_channel_match(target_name, ch['name'], league):
                    # Calculate similarity score for logging
                    score = similar(ch['_norm'], target_norm)
                    matching.append((score, ch))
            
            if matching:
                # Sort by similarity descending
                matching.sort(key=lambda x: x[0], reverse=True)
                print(f"      🔍 Tìm thấy {len(matching)} kênh M3U khớp")
                
                for score, ch in matching:
                    url = ch['url']
                    # Check duplicate rule
                    if league == "Tennis":
                        if url in used_urls_tennis:
                            print(f"         ⚠️ Bỏ qua {ch['name']} (score={score:.3f}) - URL đã dùng trong tennis")
                            continue
                        # Add to tennis global set and per-match set
                        used_urls_tennis.add(url)
                        used_urls_per_match[match_key].add(url)
                    else:
                        if url in used_urls_per_match[match_key]:
                            print(f"         ⚠️ Bỏ qua {ch['name']} (score={score:.3f}) - URL đã dùng trong trận này")
                            continue
                        used_urls_per_match[match_key].add(url)
                    
                    # Add event
                    total_matched_entries += 1
                    live_events.append({
                        "datetime": datetime.fromtimestamp(kick_utc).astimezone(TIMEZONE),
                        "name": f"{kick_time} | {match_name} ({ch['name']})",
                        "channel": ch,
                        "league": league
                    })
                    print(f"         ✅ Thêm kênh: {ch['name']} (score={score:.3f})")
            else:
                print("      ❌ Không tìm thấy kênh M3U phù hợp")
    
    print(f"\n📊 TỔNG KẾT MATCH: {total_matched_entries} kênh được thêm từ {total_requested_channels} yêu cầu")
    
    # Sort events
    live_events.sort(key=lambda x: x["datetime"])
    
    # Validate
    if not SKIP_VALIDATION:
        live_events = await validate_events_batch(live_events)
    
    # Write output
    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="Live Football"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if ch.get('extra'):
                f.write('\n'.join(ch['extra']) + "\n")
            f.write(ch['url'] + "\n")
    
    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH! {len(live_events)} kênh trong {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
