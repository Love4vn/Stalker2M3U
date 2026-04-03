#!/usr/bin/env python3
"""
Stalker Portal to M3U Converter for Sports Channels
- Đọc Mac_list.txt, kiểm tra portal thông qua stream thực tế
- Chọn 3 portal có URL khác nhau và stream hoạt động
- Lọc kênh thể thao theo từ khóa, loại trừ môn không mong muốn
- Chỉ lấy kênh Full HD (FHD, 1080p, 4K, UHD)
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
    "monomax", "astro arena", "spotv", "epl", "tsn", "la liga", "laliga", "bundesliga",
    "seriea", "serie a", "uefa", "arsenal", "aston villa", "bournemouth",
    "brentford", "brighton", "chelsea", "crystal palace", "everton", "fulham", "leeds united", "liverpool",
    "manchester city", "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
    "west ham united", "wolverhampton", "bayern", "bayern munich", "borussia dortmund", "bayer leverkusen", "inter milan",
    "ac milan", "napoli", "barcelona", "real madrid", "atlético", "atletico madrid", "psg", "paris saint-germain", "olympique marseille"
]

# Từ khóa loại trừ (môn không mong muốn, giải trẻ, giải hạng dưới, và group-title)
EXCLUDE_KEYWORDS = [
    "baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ",
    "handball", "bóng ném", "hockey", "khúc côn cầu", "bóng bầu dục",
    "u23", "u21", "u19", "youth", "junior", "reserve", "mma",
    "second division", "liga 2", "serie b", "2. bundesliga", "championship", "national league", "replay", "film", "movie",
    "kurd", "iran", "iraq", "libya", "egypt", "peru", "afghanistan", "kuwait", "saudi", "oman", "cinema", "entertainment", "horse"
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
    group_title = genres.get(genre_id, "").lower()
    text = title + " " + group_title

    if not any(kw in text for kw in SPORTS_KEYWORDS):
        return False

    for ex in EXCLUDE_KEYWORDS:
        if ex in text or ex in group_title:
            return False
    return True

def is_hd_channel(channel):
    name = channel.get("name", "").lower()
    for kw in HD_KEYWORDS:
        if kw in name:
            return True
    return False

def get_stream_url_from_cmd(cmd, portal_url, mac, token=None):
    """
    Tạo URL stream từ cmd.
    Nếu cmd chứa ffmpeg/ffrt, loại bỏ.
    Nếu cmd bắt đầu bằng http, dùng trực tiếp (có thể thay localhost).
    Nếu không, thử gọi create_link để lấy URL có token.
    """
    if not cmd:
        return None
    # Làm sạch cmd
    clean_cmd = cmd.replace("ffmpeg ", "").replace("ffrt ", "").strip()
    if clean_cmd.startswith("http"):
        # Nếu có localhost, thay bằng domain portal
        if "localhost" in clean_cmd:
            domain_match = re.search(r'https?://([^/]+)', portal_url)
            if domain_match:
                domain = domain_match.group(1)
                clean_cmd = clean_cmd.replace("localhost", domain)
        return clean_cmd
    else:
        # Nếu không, cần tạo link qua API (nếu có token)
        if token:
            # Gọi create_link (cần server_url, mac, token)
            # Lưu ý: cần server_url (dạng /server/load.php) và token
            # Hàm này sẽ được gọi từ bên ngoài khi có token
            return None  # Sẽ được xử lý riêng
        else:
            # Fallback: nối với base URL
            base = portal_url.rstrip('/')
            if not base.endswith('/c'):
                base += '/c'
            return base.rstrip('/') + '/' + clean_cmd.lstrip('/')

def create_link(server_url, mac, token, cmd):
    """Gọi API create_link để lấy URL stream thực"""
    params = {
        "type": "itv",
        "action": "create_link",
        "cmd": cmd,
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
        if "js" in data and "cmd" in data["js"]:
            return data["js"]["cmd"]
    except:
        pass
    return None

def test_stream_url(url):
    """Kiểm tra URL stream có trả về video không (HEAD request)"""
    try:
        # Dùng HEAD để kiểm tra content-type
        resp = SESSION.head(url, timeout=5, allow_redirects=True)
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '').lower()
            if any(t in content_type for t in ['video', 'mp2t', 'mpegurl', 'octet-stream']):
                return True
        # Nếu HEAD không đủ, thử GET với range nhỏ
        headers = {'Range': 'bytes=0-1024'}
        resp = SESSION.get(url, headers=headers, timeout=5, stream=True)
        if resp.status_code in (200, 206):
            content_type = resp.headers.get('Content-Type', '').lower()
            if any(t in content_type for t in ['video', 'mp2t', 'mpegurl', 'octet-stream']):
                return True
    except:
        pass
    return False

def get_portal_info(url, mac):
    """Kiểm tra portal, trả về thông tin nếu có ít nhất một stream hoạt động"""
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

    # Lọc thể thao và HD
    sports = []
    for ch in channels:
        if is_sports_channel(ch, genres) and is_hd_channel(ch):
            sports.append(ch)
    print(f"  HD sports channels: {len(sports)}")

    if not sports:
        print("  No HD sports channels found")
        return None

    # Thử lấy stream của kênh đầu tiên để kiểm tra hoạt động
    test_ch = sports[0]
    cmd = test_ch.get("cmd")
    if not cmd:
        print("  No cmd for test channel")
        return None

    # Tạo URL stream (ưu tiên create_link)
    stream_url = create_link(server_url, mac, token, cmd)
    if stream_url:
        stream_url = stream_url.replace("ffmpeg ", "").replace("ffrt ", "").strip()
        if "localhost" in stream_url:
            domain_match = re.search(r'https?://([^/]+)', url)
            if domain_match:
                stream_url = stream_url.replace("localhost", domain_match.group(1))
    else:
        # Fallback: dùng cmd đã làm sạch
        clean_cmd = cmd.replace("ffmpeg ", "").replace("ffrt ", "").strip()
        if clean_cmd.startswith("http"):
            stream_url = clean_cmd
            if "localhost" in stream_url:
                domain_match = re.search(r'https?://([^/]+)', url)
                if domain_match:
                    stream_url = stream_url.replace("localhost", domain_match.group(1))
        else:
            # Tạo URL từ base
            base = url.rstrip('/')
            if not base.endswith('/c'):
                base += '/c'
            stream_url = base.rstrip('/') + '/' + clean_cmd.lstrip('/')

    if not stream_url:
        print("  Could not generate test stream URL")
        return None

    print(f"  Testing stream: {stream_url[:100]}...")
    if not test_stream_url(stream_url):
        print("  Sample stream test failed (not a valid video)")
        return None

    print("  Sample stream OK")

    # Nếu vượt qua, tiến hành lấy tất cả stream
    stream_list = []
    for ch in sports:
        cmd = ch.get("cmd")
        if not cmd:
            continue
        # Tạo URL cho từng kênh
        url_stream = create_link(server_url, mac, token, cmd)
        if url_stream:
            url_stream = url_stream.replace("ffmpeg ", "").replace("ffrt ", "").strip()
            if "localhost" in url_stream:
                domain_match = re.search(r'https?://([^/]+)', url)
                if domain_match:
                    url_stream = url_stream.replace("localhost", domain_match.group(1))
        else:
            # Fallback
            clean_cmd = cmd.replace("ffmpeg ", "").replace("ffrt ", "").strip()
            if clean_cmd.startswith("http"):
                url_stream = clean_cmd
                if "localhost" in url_stream:
                    domain_match = re.search(r'https?://([^/]+)', url)
                    if domain_match:
                        url_stream = url_stream.replace("localhost", domain_match.group(1))
            else:
                base = url.rstrip('/')
                if not base.endswith('/c'):
                    base += '/c'
                url_stream = base.rstrip('/') + '/' + clean_cmd.lstrip('/')
        if not url_stream:
            continue
        genre_id = str(ch.get("tv_genre_id", ""))
        group_title = genres.get(genre_id, "Sports")
        # Kiểm tra lại group_title không bị loại trừ
        if any(ex in group_title.lower() for ex in EXCLUDE_KEYWORDS):
            continue
        stream_list.append({
            "id": ch.get("id", ""),
            "name": ch.get("name", ""),
            "logo": ch.get("logo", ""),
            "group_title": group_title,
            "url": url_stream
        })

    return {
        "url": url,
        "mac": mac,
        "expiry_str": expiry_str,
        "days_left": days_left,
        "channels_count": len(channels),
        "hd_sports_count": len(stream_list),
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

    # Lấy thông tin từng portal (chỉ lấy portal có stream hoạt động)
    portal_infos = []
    for url, mac in portals:
        info = get_portal_info(url, mac)
        if info and info["hd_sports_count"] > 0:
            portal_infos.append(info)

    if not portal_infos:
        print("No valid portal with working streams found.")
        sys.exit(1)

    # Loại bỏ các portal trùng URL (giữ cái có nhiều kênh HD nhất)
    unique_urls = {}
    for p in portal_infos:
        url = p["url"]
        if url not in unique_urls or p["hd_sports_count"] > unique_urls[url]["hd_sports_count"]:
            unique_urls[url] = p
    unique_portals = list(unique_urls.values())

    # Sắp xếp theo số kênh HD giảm dần, chọn tối đa 3 portal
    unique_portals.sort(key=lambda p: p["hd_sports_count"], reverse=True)
    selected = unique_portals[:3]
    print(f"\nSelected {len(selected)} portals (unique URLs) with working streams:")
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
