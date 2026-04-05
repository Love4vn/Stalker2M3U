"""
footonsat_schedule_live.py
================================
LẤY LỊCH TRỰC TIẾP TỪ footonsat-api
Tích hợp M3U với matching thông minh
Xuất ra live_schedule.m3u
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
from typing import List, Dict, Optional

# ================== CẤU HÌNH ==================
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
M3U_LIST_FILE = "M3U_list.txt"
LIVE_M3U = "live_schedule.m3u"

ALLOWED_LEAGUES = {
    "Premier League": "Live Premier League",
    "Serie A": "Live Serie A",
    "La Liga": "Live La Liga",
    "Bundesliga": "Live Bundesliga",
    "Ligue 1": "Live Ligue 1",
    "UEFA Champions League": "Live UEFA Champions League",
    "UEFA Europa League": "Live UEFA Europa League",
    "UEFA Europa Conference League": "Live UEFA Conference League",
}

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

def normalize_channel_name(name: str) -> str:
    """
    Chuẩn hóa tên kênh:
    - Loại bỏ tiền tố quốc gia (UK:, FR:, NL|, ...)
    - Loại bỏ các từ thừa (HD, UHD, 4K, TV, Channel, ...)
    - Thay thế 'plus' bằng '+', 'and' bằng '&', ...
    - Giữ nguyên số và từ đặc biệt (TNT, SPORT, ...)
    """
    original = name
    name = name.lower()
    # Loại bỏ tiền tố dạng "UK:", "FR:", "NL|", "| TR |", "UK - " ...
    name = re.sub(r'^(uk|fr|de|it|es|nl|no|se|dk|fi|tr|pl|cz|hu|ro|bg|gr|il)[\|\:\-\s]+', '', name)
    name = re.sub(r'^\|[a-z]{2}\|\s*', '', name)
    name = re.sub(r'^\[[^\]]+\]\s*', '', name)
    # Loại bỏ các hậu tố phân giải và từ chung
    name = re.sub(r'\b(hd|uhd|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc|h\.265)\b', '', name)
    # Thay thế 'plus' bằng '+' để đồng nhất
    name = name.replace('plus', '+')
    name = name.replace(' and ', ' & ')
    # Loại bỏ ký tự đặc biệt, chỉ giữ chữ, số, dấu cách, dấu '+'
    name = re.sub(r'[^\w\s\+]', ' ', name)
    # Chuẩn hóa khoảng trắng
    name = ' '.join(name.split())
    # Bỏ dấu
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    if not ch_name or not m3u_name:
        return False
    ch_norm = normalize_channel_name(ch_name)
    m3u_norm = normalize_channel_name(m3u_name)
    # Exact match sau chuẩn hóa
    if ch_norm == m3u_norm:
        return True
    # Nếu độ dài quá ngắn, so sánh exact
    if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
        return ch_norm == m3u_norm
    # Cho phép sai lệch độ dài tối đa 30%
    if abs(len(ch_norm) - len(m3u_norm)) > max(len(ch_norm), len(m3u_norm)) * 0.3:
        return False
    sim = similar(ch_norm, m3u_norm)
    # In debug cho các kênh quan trọng
    if any(x in ch_name.lower() for x in ['tnt', 'sport+', 'bein', 'dazn', 'sports']):
        print(f"      DEBUG: '{ch_name}' -> '{ch_norm}'")
        print(f"             '{m3u_name}' -> '{m3u_norm}'")
        print(f"             similarity: {sim}")
    return sim >= 0.88

# ================== FOOTONSAT API ==================
def fetch_footonsat_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
            except Exception as e:
                print(f"   Lỗi parse thời gian: {e}")
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
            
            if channels:
                games.append({
                    "league": league,
                    "match": match_name,
                    "kick_utc": kick_utc,
                    "time": vn_time(kick_utc),
                    "channels": channels,
                })
            i = j
        else:
            i += 1
    return games

def load_all_footonsat_games(now_ts_utc: int, max_ts_utc: int) -> List[Dict]:
    all_games = []
    for url in FOOTONSAT_URLS:
        print(f"   Đang tải {url}")
        data = fetch_footonsat_json(url)
        if data:
            games = parse_footonsat_data(data)
            for g in games:
                if now_ts_utc <= g['kick_utc'] <= max_ts_utc:
                    all_games.append(g)
            if games:
                kept = len([g for g in games if now_ts_utc <= g['kick_utc'] <= max_ts_utc])
                print(f"      -> Tìm thấy {len(games)} trận, giữ lại {kept} trận trong 24h tới")
            else:
                print(f"      -> Không có trận nào")
        else:
            print(f"      -> Không tải được dữ liệu")
    return all_games

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
            # Lấy tên kênh: phần sau dấu phẩy cuối cùng
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

# ================== MAIN ==================
async def main():
    start = time.time()
    vn_now = datetime.now(TIMEZONE)
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_ts_utc = int(now_utc.timestamp())
    max_ts_utc = now_ts_utc + 86400

    print("🔄 Bắt đầu lấy lịch 24 GIỜ TỚI (theo UTC)...")
    all_games = load_all_footonsat_games(now_ts_utc, max_ts_utc)
    print(f"   ✅ Tổng số trận trong 24h tới (UTC): {len(all_games)}")

    if all_games:
        print("   📋 Danh sách trận đã lấy:")
        for g in all_games:
            print(f"      {g['time']} | {g['league']} | {g['match']}")
    else:
        print("   ⚠️ Không có trận nào.")

    filtered = [g for g in all_games if datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE) > vn_now]
    all_games = filtered
    print(f"   ✅ Sau lọc quá khứ (theo giờ VN): {len(all_games)} trận")

    if not all_games:
        print("⚠️ Không có trận nào trong 24h tới. Thoát.")
        return

    print("📥 Đang tải và phân tích M3U...")
    m3u_links = []
    try:
        with open(M3U_LIST_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('http'):
                    m3u_links.append(line)
        print(f"   📋 Tìm thấy {len(m3u_links)} URL trong M3U_list.txt")
    except Exception as e:
        print(f"   ❌ Lỗi đọc file M3U_list.txt: {e}")
        m3u_links = []

    def fetch_text_sync(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
        print("   ⚠️ Không có link M3U nào để tải.")

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    print(f"   ✅ Đã tải {len(unique_ch)} kênh")

    # In 50 kênh đầu tiên để kiểm tra
    print("   📺 Ví dụ 50 kênh đầu tiên trong M3U (tên gốc):")
    for i, ch in enumerate(unique_ch[:50]):
        print(f"      {i+1}. {ch['name']}")

    print("🔄 Đang match kênh với lịch...")
    live_events = []
    for g in all_games:
        try:
            used_urls = set()
            for ch_name in g.get("channels", []):
                matching = [ch for ch in unique_ch if is_channel_match(ch_name, ch['name'])]
                if matching:
                    print(f"   ✅ Match: {g['match']} - {ch_name} -> {len(matching)} kênh")
                for ch in matching:
                    url = ch['url']
                    if url in used_urls:
                        continue
                    used_urls.add(url)
                    display_name = f"{g['time']} | {g['match']} ({ch_name})"
                    live_events.append({
                        "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                        "name": display_name,
                        "channel": ch,
                        "league": g["league"]
                    })
            if not used_urls and g.get('match'):
                match_norm = normalize(g['match'])
                for ch in unique_ch:
                    if similar(match_norm, normalize_channel_name(ch['name'])) >= 0.85:
                        url = ch['url']
                        if url in used_urls:
                            continue
                        used_urls.add(url)
                        display_name = f"{g['time']} | {g['match']} (M3U: {ch['name']})"
                        live_events.append({
                            "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                            "name": display_name,
                            "channel": ch,
                            "league": g["league"]
                        })
                        break
        except Exception as e:
            print(f"   ❌ Lỗi xử lý trận {g.get('match', '')}: {e}")

    # Xử lý trùng kênh
    seen = {}
    dedup_events = []
    for ev in live_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in seen:
            seen[key] = ev
            dedup_events.append(ev)
    live_events = dedup_events
    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group_title = ALLOWED_LEAGUES.get(ev["league"], None)
            if not group_title:
                continue
            extinf = f'#EXTINF:-1 tvg-id="{ch["params"].get("tvg-id","")}" group-title="{group_title}"'
            if ch["params"].get("tvg-logo"):
                extinf += f' tvg-logo="{ch["params"]["tvg-logo"]}"'
            extinf += f',{ev["name"]}'
            f.write(extinf + "\n")
            if 'extra' in ch:
                for line in ch['extra']:
                    if not line.startswith('#EXTINF'):
                        f.write(line + "\n")
            f.write(ch['url'] + "\n")

    elapsed = time.time() - start
    print(f"\n🎉 HOÀN THÀNH!")
    print(f"   • live_schedule.m3u: {len(live_events)} kênh (matching thông minh)")

if __name__ == "__main__":
    asyncio.run(main())
