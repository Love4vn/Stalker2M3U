#!/usr/bin/env python3
"""
Stalker Portal to M3U Converter for Premium Sports Channels
- Kiểm tra portal, chọn portal có hạn dài nhất
- Lọc kênh: bóng đá các giải cao cấp, tennis, golf, F1, Olympic
- Chỉ lấy kênh Full HD (FHD, 1080p, 4K, UHD) trở lên
- Xuất M3U với URL stream trực tiếp (bỏ tiền tố ffmpeg/ffrt)
"""

import requests
import json
import sys
import time
import re
from datetime import datetime
from urllib.parse import quote
import os

# ==================== CONFIGURATION ====================
REQUEST_TIMEOUT = 10
SESSION = requests.Session()

# Device parameters
DEFAULT_SERIAL = "0000000000000000"
DEFAULT_DEVICE_ID1 = "0000000000000000"
DEFAULT_DEVICE_ID2 = "0000000000000000"
DEFAULT_SIGNATURE = "0000000000000000"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "X-User-Agent": "Model: MAG250; Link: WiFi",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest"
}

# ========== DANH SÁCH TỪ KHÓA LỌC THỂ THAO ==========
# Bóng đá các giải cao cấp (ưu tiên tên giải)
FOOTBALL_LEAGUES = {
    "premier league": ["premier league", "epl", "english premier league"],
    "bundesliga": ["bundesliga", "german bundesliga"],
    "la liga": ["la liga", "laliga", "spanish la liga"],
    "ligue 1": ["ligue 1", "french ligue 1"],
    "serie a": ["serie a", "italian serie a"],
    "champions league": ["champions league", "ucl", "uefa champions league"],
    "europa league": ["europa league", "uel", "uefa europa league"],
    "conference league": ["conference league", "uefa conference league", "europa conference"],
    "euro": ["euro", "european championship", "uefa euro"],
    "world cup": ["world cup", "fifa world cup"],
    "friendly top20": ["friendly", "international friendly", "national team friendly"]
}

# Tennis
TENNIS_KEYWORDS = ["tennis", "wta", "atp", "grand slam", "australian open", "roland garros", "wimbledon", "us open", "davis cup", "billie jean king cup"]

# Golf
GOLF_KEYWORDS = ["golf", "masters", "pga championship", "us open golf", "the open championship", "ryder cup"]

# F1
F1_KEYWORDS = ["f1", "formula 1", "formula one", "grand prix"]

# Olympic
OLYMPIC_KEYWORDS = ["olympic", "olympics"]

# Các từ khóa độ phân giải cao
HD_KEYWORDS = ["fhd", "full hd", "1080p", "1080", "4k", "uhd", "2160p"]

# Từ khóa loại trừ (giải trẻ, cấp thấp)
EXCLUDE_LEVELS = ["u23", "u21", "u19", "youth", "junior", "reserve", "second division", "liga 2", "serie b", "2. bundesliga", "championship"]

# ==================== CÁC HÀM CHÍNH ====================
def clean_url(base_url):
    base_url = base_url.rstrip('/')
    if not base_url.endswith('/c'):
        base_url += '/c'
    return base_url.replace('/c', '/server/load.php')

def handshake(server_url, mac):
    params = {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    try:
        resp = SESSION.get(server_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data:
            return data["js"].get("token"), data["js"].get("random")
    except:
        pass
    return None, None

def get_profile(server_url, mac, token, random):
    params = {
        "type": "stb", "action": "get_profile", "hd": "1",
        "ver": quote("ImageDescription: 0.2.18-r14-pub-250; ImageDate: Fri Jan 15 15:20:44 EET 2016; PORTAL version: 5.1.0; API Version: JS API version: 328; STB API version: 134; Player Engine version: 0x566"),
        "num_banks": "2", "sn": DEFAULT_SERIAL, "stb_type": "MAG250", "image_version": "218",
        "video_out": "hdmi", "device_id": DEFAULT_DEVICE_ID1, "device_id2": DEFAULT_DEVICE_ID2,
        "signature": DEFAULT_SIGNATURE, "auth_second_step": "1", "hw_version": "1.7-BD-00",
        "not_valid_token": "0", "client_type": "STB",
        "hw_version_2": "36da041e6358ee8f8801105e36a63474", "timestamp": int(time.time()),
        "api_signature": "263",
        "metrics": json.dumps({"mac": mac, "sn": DEFAULT_SERIAL, "model": "MAG250", "type": "STB", "uid": "", "random": random}),
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    try:
        resp = SESSION.get(server_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data:
            return data["js"].get("expirydate") or data["js"].get("expire_billing_date")
    except:
        pass
    return None

def get_channels(server_url, mac, token):
    params = {"type": "itv", "action": "get_all_channels", "JsHttpRequest": "1-xml"}
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    try:
        resp = SESSION.get(server_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data and "data" in data["js"]:
            return data["js"]["data"]
    except:
        pass
    return []

def get_genres(server_url, mac, token):
    params = {"type": "itv", "action": "get_genres", "JsHttpRequest": "1-xml"}
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    try:
        resp = SESSION.get(server_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        genres = {}
        if "js" in data and isinstance(data["js"], list):
            for g in data["js"]:
                if "id" in g and "title" in g:
                    genres[str(g["id"])] = g["title"]
        return genres
    except:
        pass
    return {}

def get_categories(server_url, mac, token):
    return get_genres(server_url, mac, token)

def parse_expiry(expiry_str):
    if not expiry_str or expiry_str.strip() == "":
        return None
    expiry_str = expiry_str.strip()
    if expiry_str.startswith("0000-00-00"):
        return None
    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]:
        try:
            return datetime.strptime(expiry_str, fmt)
        except:
            continue
    return None

def is_sports_channel(channel, genres):
    title = channel.get("name", "").lower()
    genre_id = str(channel.get("tv_genre_id", ""))
    genre_title = genres.get(genre_id, "").lower()
    text = title + " " + genre_title
    
    # Loại trừ các giải trẻ, cấp thấp
    for ex in EXCLUDE_LEVELS:
        if ex in text:
            return False
    
    # Bóng đá theo giải
    for league, patterns in FOOTBALL_LEAGUES.items():
        if any(p in text for p in patterns):
            # Với giao hữu top20, tạm thời giữ lại tất cả friendly
            if league == "friendly top20":
                return True
            return True
    
    # Tennis
    if any(kw in text for kw in TENNIS_KEYWORDS):
        return True
    # Golf
    if any(kw in text for kw in GOLF_KEYWORDS):
        return True
    # F1
    if any(kw in text for kw in F1_KEYWORDS):
        return True
    # Olympic
    if any(kw in text for kw in OLYMPIC_KEYWORDS):
        return True
    
    return False

def is_hd_channel(channel):
    name = channel.get("name", "").lower()
    for kw in HD_KEYWORDS:
        if kw in name:
            return True
    return False

def get_stream_url_from_cmd(cmd, base_url):
    if not cmd:
        return None
    cmd = cmd.replace("ffmpeg ", "").replace("ffrt ", "").strip()
    if cmd.startswith("http"):
        return cmd
    else:
        return base_url.rstrip('/') + '/' + cmd.lstrip('/')

# ==================== HÀM CHÍNH ====================
def main():
    start_total = time.time()
    
    # Đọc danh sách portal
    if not os.path.exists("Mac_list.txt"):
        print("Error: Mac_list.txt not found.")
        sys.exit(1)
    
    portals = []
    with open("Mac_list.txt", "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                portals.append((parts[0].strip(), parts[1].strip()))
            else:
                print(f"Skipping invalid line: {line}")
    
    if not portals:
        print("No portals found in Mac_list.txt")
        sys.exit(1)
    
    valid_portals = []
    for url, mac in portals:
        print(f"\nChecking: {url} - MAC: {mac}")
        t0 = time.time()
        server_url = clean_url(url)
        token, random = handshake(server_url, mac)
        if not token:
            print("  Handshake failed")
            continue
        
        expiry_str = get_profile(server_url, mac, token, random)
        if not expiry_str:
            print("  Could not retrieve expiry")
            continue
        
        expiry_date = parse_expiry(expiry_str)
        if expiry_date is None:
            days_left = 999999
            print(f"  Expiry: {expiry_str} (unlimited)")
        else:
            days_left = (expiry_date - datetime.now()).days
            if days_left < 0:
                print(f"  Expiry: {expiry_str} (expired, {days_left} days)")
                continue
            print(f"  Expiry: {expiry_str} ({days_left} days left)")
        
        # Lấy thông tin chi tiết
        channels = get_channels(server_url, mac, token)
        categories = get_categories(server_url, mac, token)
        print(f"  Channels: {len(channels)}, Categories: {len(categories)}")
        
        valid_portals.append({
            "url": url,
            "mac": mac,
            "token": token,
            "random": random,
            "server_url": server_url,
            "expiry_str": expiry_str,
            "days_left": days_left,
            "channels_count": len(channels),
            "categories_count": len(categories),
            "check_time": time.time() - t0
        })
    
    if not valid_portals:
        print("No valid portal found.")
        sys.exit(1)
    
    # Chọn portal có thời gian sống dài nhất
    best = max(valid_portals, key=lambda p: p["days_left"])
    print(f"\nSelected portal: {best['url']} (expires {best['expiry_str']}, {best['days_left']} days)")
    print(f"Channels: {best['channels_count']}, Categories: {best['categories_count']}")
    print(f"Check time: {best['check_time']:.2f}s")
    
    # Lấy danh sách kênh và thể loại chi tiết
    channels = get_channels(best["server_url"], best["mac"], best["token"])
    genres = get_genres(best["server_url"], best["mac"], best["token"])
    print(f"Retrieved {len(channels)} channels, {len(genres)} genres")
    
    # Lọc kênh thể thao
    sports_candidates = []
    for ch in channels:
        if is_sports_channel(ch, genres):
            sports_candidates.append(ch)
    print(f"Found {len(sports_candidates)} sports channels before HD filter")
    
    # Lọc kênh Full HD
    hd_sports = [ch for ch in sports_candidates if is_hd_channel(ch)]
    print(f"Found {len(hd_sports)} sports channels after HD filter")
    
    # Tạo M3U (không kiểm tra stream)
    m3u_content = "#EXTM3U\n"
    total_streams = 0
    base_url = best['url'].rstrip('/')
    for idx, ch in enumerate(hd_sports):
        if idx % 10 == 0:
            print(f"Processing stream {idx}/{len(hd_sports)}...")
        cmd = ch.get("cmd")
        if not cmd:
            continue
        stream_url = get_stream_url_from_cmd(cmd, base_url)
        if not stream_url:
            continue
        
        tvg_id = ch.get("id", "")
        tvg_name = ch.get("name", "")
        tvg_logo = ch.get("logo", "")
        genre_id = str(ch.get("tv_genre_id", ""))
        group_title = genres.get(genre_id, "Sports")
        m3u_content += f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" group-title="{group_title}",{tvg_name}\n'
        m3u_content += f"{stream_url}\n"
        total_streams += 1
    
    # Ghi file
    with open("Mac_playlist.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)
    
    print(f"Playlist generated: Mac_playlist.m3u with {total_streams} streams.")
    print(f"Total time: {time.time()-start_total:.2f}s")

if __name__ == "__main__":
    main()
