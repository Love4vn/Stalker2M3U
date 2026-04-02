#!/usr/bin/env python3
"""
Stalker Portal to M3U Converter for Sports Channels
- Đọc Mac_list.txt, kiểm tra và chọn 3 portal sống tốt nhất
- Lọc kênh thể thao (loại trừ một số môn và giải trẻ, hạng dưới)
- Chỉ lấy kênh Full HD (FHD, 1080p, 4K, UHD) trở lên
- Xuất M3U tổng hợp từ 3 portal
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

# ========== TỪ KHÓA LỌC THỂ THAO ==========
SPORTS_KEYWORDS = [
    "sport", "sports", "football", "soccer", "tennis", "golf",
    "motorsport", "formula 1", "f1", "hub premier", "premier league",
    "mono max", "astro arena", "spotv", "epl", "soccer", "tsn", "la liga", "laliga", "bundesliga",
    "seriea", "serie a", "uefa"
]

# Từ khóa loại trừ (môn không mong muốn, giải trẻ, giải hạng dưới)
EXCLUDE_KEYWORDS = [
    "baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ",
    "handball", "bóng ném", "hockey", "khúc côn cầu", "bóng bầu dục",
    "u23", "u21", "u19", "youth", "junior", "reserve",
    "second division", "liga 2", "serie b", "2. bundesliga", "championship"
]

# Các từ khóa độ phân giải cao
HD_KEYWORDS = ["hd", "fhd", "full hd", "1080p", "1080", "4k", "uhd", "2160p"]

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

    if not any(kw in text for kw in SPORTS_KEYWORDS):
        return False

    for ex in EXCLUDE_KEYWORDS:
        if ex in text:
            return False
    return True

def is_hd_channel(channel):
    name = channel.get("name", "").lower()
    for kw in HD_KEYWORDS:
        if kw in name:
            return True
    return False

def get_stream_url_from_cmd(cmd, portal_url):
    """Chuyển cmd thành URL stream thực tế, thay localhost nếu có"""
    if not cmd:
        return None
    cmd = cmd.replace("ffmpeg ", "").replace("ffrt ", "").strip()
    if not cmd:
        return None
    if cmd.startswith("http"):
        if "localhost" in cmd:
            domain_match = re.search(r'https?://([^/]+)', portal_url)
            if domain_match:
                domain = domain_match.group(1)
                cmd = cmd.replace("localhost", domain)
        return cmd
    else:
        base = portal_url.rstrip('/')
        if not base.endswith('/c'):
            base += '/c'
        return base.rstrip('/') + '/' + cmd.lstrip('/')

def get_portal_info(url, mac):
    """Kiểm tra portal, trả về thông tin và danh sách stream đã lọc thể thao HD"""
    print(f"\nChecking: {url} - MAC: {mac}")
    t0 = time.time()
    server_url = clean_url(url)
    token, random = handshake(server_url, mac)
    if not token:
        print("  Handshake failed")
        return None

    expiry_str = get_profile(server_url, mac, token, random)
    if not expiry_str:
        print("  Could not retrieve expiry")
        return None

    expiry_date = parse_expiry(expiry_str)
    if expiry_date is None:
        days_left = 999999
        print(f"  Expiry: {expiry_str} (unlimited)")
    else:
        days_left = (expiry_date - datetime.now()).days
        if days_left < 0:
            print(f"  Expiry: {expiry_str} (expired, {days_left} days)")
            return None
        print(f"  Expiry: {expiry_str} ({days_left} days left)")

    channels = get_channels(server_url, mac, token)
    genres = get_genres(server_url, mac, token)
    if not channels:
        print("  No channels retrieved")
        return None

    print(f"  Channels total: {len(channels)}, Genres: {len(genres)}")

    # Lọc thể thao
    sports = []
    for ch in channels:
        if is_sports_channel(ch, genres):
            sports.append(ch)
    print(f"  Sports channels: {len(sports)}")

    # Lọc HD
    hd_sports = [ch for ch in sports if is_hd_channel(ch)]
    print(f"  HD sports channels: {len(hd_sports)}")

    # Tạo danh sách stream với URL đã xử lý
    stream_list = []
    for ch in hd_sports:
        cmd = ch.get("cmd")
        if not cmd:
            continue
        stream_url = get_stream_url_from_cmd(cmd, url)
        if not stream_url:
            continue
        stream_list.append({
            "id": ch.get("id", ""),
            "name": ch.get("name", ""),
            "logo": ch.get("logo", ""),
            "genre_id": str(ch.get("tv_genre_id", "")),
            "group_title": genres.get(str(ch.get("tv_genre_id", "")), "Sports"),
            "url": stream_url
        })

    return {
        "url": url,
        "mac": mac,
        "expiry_str": expiry_str,
        "days_left": days_left,
        "channels_count": len(channels),
        "sports_count": len(sports),
        "hd_sports_count": len(hd_sports),
        "streams": stream_list,
        "check_time": time.time() - t0
    }

# ==================== HÀM CHÍNH ====================
def main():
    start_total = time.time()

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

    # Lấy thông tin từng portal
    portal_infos = []
    for url, mac in portals:
        info = get_portal_info(url, mac)
        if info:
            portal_infos.append(info)

    if not portal_infos:
        print("No valid portal found.")
        sys.exit(1)

    # Sắp xếp theo số kênh HD giảm dần, chọn tối đa 3 portal
    portal_infos.sort(key=lambda p: p["hd_sports_count"], reverse=True)
    selected = portal_infos[:3]
    print(f"\nSelected {len(selected)} portals:")
    for p in selected:
        print(f"  {p['url']} - {p['hd_sports_count']} HD sports channels")

    # Hợp nhất streams từ các portal
    all_streams = []
    for p in selected:
        all_streams.extend(p["streams"])

    print(f"Total combined streams: {len(all_streams)}")

    # Tạo M3U
    m3u_content = "#EXTM3U\n"
    for s in all_streams:
        m3u_content += f'#EXTINF:-1 tvg-id="{s["id"]}" tvg-name="{s["name"]}" tvg-logo="{s["logo"]}" group-title="{s["group_title"]}",{s["name"]}\n'
        m3u_content += f"{s['url']}\n"

    with open("Mac_playlist.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Playlist generated: Mac_playlist.m3u with {len(all_streams)} streams.")
    print(f"Total time: {time.time()-start_total:.2f}s")

if __name__ == "__main__":
    main()
