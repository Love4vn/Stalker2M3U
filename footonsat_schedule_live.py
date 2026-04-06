"""
footonsat_schedule_live.py
================================
LẤY LỊCH TRỰC TIẾP TỪ footonsat-api
Tích hợp M3U với matching thông minh (tách mã quốc gia)
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
from typing import List, Dict, Optional, Tuple

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

COUNTRY_CODES = {
    "uk", "us", "fr", "de", "it", "es", "pt", "nl", "be", "ch", "at",
    "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "bg", "gr", "tr",
    "il", "au", "ca", "nz", "ie", "gb", "en"
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

def extract_prefix_and_name(name: str) -> Tuple[Optional[str], str]:
    """
    Tách mã quốc gia / vùng (nếu có) khỏi tên kênh.
    Trả về (mã, tên_đã_xóa_tiền_tố).
    """
    name_lower = name.lower()
    patterns = [
        (r'^\|\s*([a-z]{2,3})\s*\|\s*', 1),    # | ES |
        (r'^([a-z]{2,3})\:\s*', 1),            # UK:
        (r'^([a-z]{2,3})\s*-\s*', 1),          # FR -
        (r'^([a-z]{2,3})\|\s*', 1),            # NL|
        (r'^\[([a-z]{2,3})\]\s*', 1),          # [UK]
        (r'^\(([a-z]{2,3})\)\s*', 1),          # (UK)
    ]
    for pat, group in patterns:
        m = re.match(pat, name_lower)
        if m:
            code = m.group(group)
            if code in COUNTRY_CODES:
                remaining = name_lower[m.end():]
                remaining = re.sub(r'^[\|\:\-\s]+', '', remaining)
                return code, remaining.strip()
    # Không có tiền tố, loại bỏ ký tự đặc biệt đầu
    cleaned = re.sub(r'^[\|\s\:\-]+', '', name_lower)
    return None, cleaned

def normalize_channel_name(name: str) -> str:
    """Chuẩn hóa tên kênh (không bao gồm mã quốc gia)."""
    _, name = extract_prefix_and_name(name)
    name = re.sub(r'\b(hd|uhd|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc)\b', '', name)
    name = name.replace('plus', '+')
    name = name.replace(' and ', ' & ')
    name = re.sub(r'[^\w\s\+]', ' ', name)
    name = ' '.join(name.split())
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ascii')
    return name

def is_channel_match(ch_name: str, m3u_name: str) -> bool:
    if not ch_name or not m3u_name:
        return False
    ch_code, ch_clean = extract_prefix_and_name(ch_name)
    m3u_code, m3u_clean = extract_prefix_and_name(m3u_name)
    ch_norm = normalize_channel_name(ch_clean)
    m3u_norm = normalize_channel_name(m3u_clean)
    # Nếu cả hai có mã, so sánh mã trước
    if ch_code and m3u_code:
        if ch_code != m3u_code:
            return False
        # Mã giống, so sánh tên
        if ch_norm == m3u_norm:
            return True
        if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
            return ch_norm == m3u_norm
        return similar(ch_norm, m3u_norm) >= 0.9
    else:
        # Một bên không có mã, chỉ so sánh tên
        if ch_norm == m3u_norm:
            return True
        if len(ch_norm) <= 3 or len(m3u_norm) <= 3:
            return ch_norm == m3u_norm
        return similar(ch_norm, m3u_norm) >= 0.9

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

def load_all_footonsat_games(start_ts_utc: int, end_ts_utc: int) -> List[Dict]:
    all_games = []
    for url in FOOTONSAT_URLS:
        print(f"   Đang tải {url}")
        data = fetch_footonsat_json(url)
        if data:
            games = parse_footonsat_data(data)
            for g in games:
                if start_ts_utc <= g['kick_utc'] <= end_ts_utc:
                    all_games.append(g)
            if games:
                kept = len([g for g in games if start_ts_utc <= g['kick_utc'] <= end_ts_utc])
                print(f"      -> Tìm thấy {len(games)} trận, giữ lại {kept} trận (lùi 2h)")
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
    start_ts_utc = now_ts_utc - 7200   # lùi 2 giờ
    end_ts_utc = now_ts_utc + 86400    # 24 giờ tới

    print("🔄 Bắt đầu lấy lịch (lùi 2h đến 24h tới)...")
    all_games = load_all_footonsat_games(start_ts_utc, end_ts_utc)
    print(f"   ✅ Tổng số trận: {len(all_games)}")

    if all_games:
        print("   📋 Danh sách trận:")
        for g in all_games:
            print(f"      {g['time']} | {g['league']} | {g['match']}")
    else:
        print("   ⚠️ Không có trận nào.")

    # Lọc trận đã kết thúc quá 2h
    filtered = []
    for g in all_games:
        kick_vn = datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE)
        if kick_vn > vn_now - timedelta(hours=2):
            filtered.append(g)
    all_games = filtered
    print(f"   ✅ Sau lọc (chưa kết thúc quá 2h): {len(all_games)} trận")

    if not all_games:
        print("⚠️ Không có trận nào. Thoát.")
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
        print("   ⚠️ Không có link M3U")

    unique_ch = list({ch['url']: ch for ch in all_ch if ch.get('url')}.values())
    print(f"   ✅ Đã tải {len(unique_ch)} kênh")

    # In mẫu 50 kênh đầu
    print("   📺 50 kênh đầu tiên:")
    for i, ch in enumerate(unique_ch[:50]):
        print(f"      {i+1}. {ch['name']}")

    print("🔄 Đang match kênh...")
    live_events = []
    for g in all_games:
        try:
            used_urls = set()
            for ch_name in g.get("channels", []):
                matching = [ch for ch in unique_ch if is_channel_match(ch_name, ch['name'])]
                if matching:
                    print(f"   ✅ Match: {g['match']} - {ch_name} -> {len(matching)} kênh")
                for ch in matching:
                    if ch['url'] in used_urls:
                        continue
                    used_urls.add(ch['url'])
                    display_name = f"{g['time']} | {g['match']} ({ch_name})"
                    live_events.append({
                        "datetime": datetime.fromtimestamp(g['kick_utc']).astimezone(TIMEZONE),
                        "name": display_name,
                        "channel": ch,
                        "league": g["league"]
                    })
        except Exception as e:
            print(f"   ❌ Lỗi {g.get('match', '')}: {e}")

    # Loại trùng kênh
    seen = {}
    dedup = []
    for ev in live_events:
        key = (ev['channel']['url'], ev['league'])
        if key not in seen:
            seen[key] = ev
            dedup.append(ev)
    live_events = dedup
    live_events.sort(key=lambda x: x["datetime"])

    with open(LIVE_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ev in live_events:
            ch = ev["channel"]
            group = ALLOWED_LEAGUES.get(ev["league"])
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

    print(f"\n🎉 HOÀN THÀNH! {len(live_events)} kênh trong live_schedule.m3u")

if __name__ == "__main__":
    asyncio.run(main())
