#!/usr/bin/env python3
"""
Stalker Portal to M3U Converter for Sports Channels
Reads Mac_list.txt, selects portal with longest expiry,
generates M3U playlist with sports channels (excluding specified sports).
"""

import requests
import json
import sys
import time
from datetime import datetime
from urllib.parse import quote
import os

# ==================== CONFIGURATION ====================
REQUEST_TIMEOUT = 10
SESSION = requests.Session()

# Device parameters (có thể tùy chỉnh theo portal)
DEFAULT_SERIAL = "0000000000000000"
DEFAULT_DEVICE_ID1 = "0000000000000000"
DEFAULT_DEVICE_ID2 = "0000000000000000"
DEFAULT_SIGNATURE = "0000000000000000"

# Headers giả lập MAG device
HEADERS = {
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "X-User-Agent": "Model: MAG250; Link: WiFi",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest"
}

# Từ khóa thể thao (giữ lại)
SPORTS_KEYWORDS = [
    "sport", "sports", "football", "soccer", "tennis", "golf",
    "motorsport", "formula 1", "f1", "boxing", "ufc", "mma",
    "bóng đá", "thể thao", "champions league", "europa league"
]

# Từ khóa thể thao cần loại trừ
EXCLUDE_SPORTS = [
    "baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ"
]

# ==================== CÁC HÀM CHÍNH ====================
def clean_url(base_url):
    """Chuyển URL portal về endpoint /server/load.php"""
    base_url = base_url.rstrip('/')
    if not base_url.endswith('/c'):
        base_url += '/c'
    return base_url.replace('/c', '/server/load.php')

def handshake(server_url, mac):
    """Bắt tay lấy token và random"""
    params = {
        "type": "stb",
        "action": "handshake",
        "token": "",
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    try:
        resp = SESSION.get(server_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data:
            return data["js"].get("token"), data["js"].get("random")
    except Exception as e:
        print(f"  Handshake error: {e}")
    return None, None

def get_profile(server_url, mac, token, random):
    """Lấy thông tin profile (hạn sử dụng)"""
    params = {
        "type": "stb",
        "action": "get_profile",
        "hd": "1",
        "ver": quote("ImageDescription: 0.2.18-r14-pub-250; ImageDate: Fri Jan 15 15:20:44 EET 2016; PORTAL version: 5.1.0; API Version: JS API version: 328; STB API version: 134; Player Engine version: 0x566"),
        "num_banks": "2",
        "sn": DEFAULT_SERIAL,
        "stb_type": "MAG250",
        "image_version": "218",
        "video_out": "hdmi",
        "device_id": DEFAULT_DEVICE_ID1,
        "device_id2": DEFAULT_DEVICE_ID2,
        "signature": DEFAULT_SIGNATURE,
        "auth_second_step": "1",
        "hw_version": "1.7-BD-00",
        "not_valid_token": "0",
        "client_type": "STB",
        "hw_version_2": "36da041e6358ee8f8801105e36a63474",
        "timestamp": int(time.time()),
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
    except Exception as e:
        print(f"  Profile error: {e}")
    return None

def get_channels(server_url, mac, token):
    """Lấy danh sách tất cả kênh"""
    params = {
        "type": "itv",
        "action": "get_all_channels",
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
        if "js" in data and "data" in data["js"]:
            return data["js"]["data"]
    except Exception as e:
        print(f"  Channels error: {e}")
    return []

def get_genres(server_url, mac, token):
    """Lấy danh sách thể loại"""
    params = {
        "type": "itv",
        "action": "get_genres",
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
        genres = {}
        if "js" in data and isinstance(data["js"], list):
            for g in data["js"]:
                if "id" in g and "title" in g:
                    genres[str(g["id"])] = g["title"]
        return genres
    except Exception as e:
        print(f"  Genres error: {e}")
    return {}

def create_link(server_url, mac, token, cmd):
    """Tạo URL stream từ cmd"""
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
    except Exception as e:
        print(f"  Create link error: {e}")
    return None

def parse_expiry(expiry_str):
    """Chuyển chuỗi ngày hết hạn thành đối tượng datetime"""
    if not expiry_str or expiry_str.strip() == "":
        return None
    expiry_str = expiry_str.strip()
    if expiry_str.startswith("0000-00-00"):
        return None
    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]:
        try:
            return datetime.strptime(expiry_str, fmt)
        except ValueError:
            continue
    return None

def is_sports_channel(channel, genres):
    """Kiểm tra kênh có phải thể thao và không thuộc danh sách loại trừ"""
    title = channel.get("name", "").lower()
    genre_id = str(channel.get("tv_genre_id", ""))
    genre_title = genres.get(genre_id, "").lower()
    text = title + " " + genre_title
    sports = any(kw in text for kw in SPORTS_KEYWORDS)
    if not sports:
        return False
    excluded = any(ex in text for ex in EXCLUDE_SPORTS)
    return not excluded

def clean_stream_url(url):
    """Loại bỏ các tiền tố không mong muốn (ffmpeg, ffrt)"""
    if not url:
        return url
    # Loại bỏ ffmpeg, ffrt và khoảng trắng
    url = url.replace("ffmpeg ", "").replace("ffrt ", "").strip()
    # Nếu URL bắt đầu bằng "http" thì giữ nguyên, nếu không thì thêm http? (thực tế nó sẽ là http)
    return url

# ==================== HÀM CHÍNH ====================
def main():
    start_total = time.time()

    # Đọc danh sách portal từ file
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

    # Kiểm tra từng portal, lấy thời hạn
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
            days_left = 999999   # coi như vô hạn
            print(f"  Expiry: {expiry_str} (unlimited)")
        else:
            days_left = (expiry_date - datetime.now()).days
            if days_left < 0:
                print(f"  Expiry: {expiry_str} (expired, {days_left} days)")
                continue
            print(f"  Expiry: {expiry_str} ({days_left} days left)")

        valid_portals.append({
            "url": url,
            "mac": mac,
            "token": token,
            "random": random,
            "server_url": server_url,
            "expiry_str": expiry_str,
            "days_left": days_left,
            "check_time": time.time() - t0
        })

    if not valid_portals:
        print("No valid portal found.")
        sys.exit(1)

    # Chọn portal có thời gian sống lâu nhất
    best = max(valid_portals, key=lambda p: p["days_left"])
    print(f"\nSelected portal: {best['url']} (expires {best['expiry_str']}, {best['days_left']} days) - checked in {best['check_time']:.2f}s")

    # Lấy danh sách kênh và thể loại
    t0 = time.time()
    channels = get_channels(best["server_url"], best["mac"], best["token"])
    if not channels:
        print("No channels retrieved.")
        sys.exit(1)
    genres = get_genres(best["server_url"], best["mac"], best["token"])
    print(f"Retrieved {len(channels)} channels, {len(genres)} genres in {time.time()-t0:.2f}s")

    # Lọc kênh thể thao
    sports_channels = [ch for ch in channels if is_sports_channel(ch, genres)]
    print(f"Found {len(sports_channels)} sports channels after filtering.")

    # Tạo M3U playlist (chỉ tạo link cho các kênh thể thao)
    m3u_content = "#EXTM3U\n"
    total_streams = 0
    for idx, ch in enumerate(sports_channels):
        if idx % 10 == 0:
            print(f"Processing stream {idx}/{len(sports_channels)}...")
        cmd = ch.get("cmd")
        if not cmd:
            continue
        stream_url = create_link(best["server_url"], best["mac"], best["token"], cmd)
        if not stream_url:
            # Fallback nếu create_link không trả về URL (có thể cmd đã là URL)
            if cmd.startswith("http"):
                stream_url = cmd
            else:
                continue
        stream_url = clean_stream_url(stream_url)
        if not stream_url.startswith("http"):
            continue  # Bỏ qua nếu không phải URL hợp lệ

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
