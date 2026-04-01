#!/usr/bin/env python3
"""
Stalker Portal to M3U Converter for Sports Channels
Reads Mac_list.txt, selects the portal with longest expiry,
generates M3U playlist with sports channels excluding specific sports.
"""

import requests
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlencode, quote
import os

# Default values for device parameters (can be customized)
DEFAULT_SERIAL = "0000000000000000"
DEFAULT_DEVICE_ID1 = "0000000000000000"
DEFAULT_DEVICE_ID2 = "0000000000000000"
DEFAULT_SIGNATURE = "0000000000000000"

# Headers mimicking MAG device
HEADERS = {
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "X-User-Agent": "Model: MAG250; Link: WiFi",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest"
}

# Sports keywords to include (case-insensitive)
SPORTS_KEYWORDS = ["sport", "sports", "football", "soccer", "tennis", "golf", "motorsport", "formula 1", "f1", "boxing", "ufc", "mma", "cricket", "baseball", "nfl", "nhl", "rugby", "basketball", "bóng đá", "thể thao"]
# Exclude sports (case-insensitive)
EXCLUDE_SPORTS = ["baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ"]

def clean_url(base_url):
    """Ensure base URL ends with /c/ and convert to server/load.php endpoint"""
    base_url = base_url.rstrip('/')
    if not base_url.endswith('/c'):
        base_url += '/c'
    # Convert to server/load.php
    server_url = base_url.replace('/c', '/server/load.php')
    return server_url

def handshake(server_url, mac):
    """Perform handshake to get token and random"""
    params = {
        "type": "stb",
        "action": "handshake",
        "token": "",
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    url = server_url
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Response format: {"js": {"token": "...", "random": "..."}}
        if "js" in data:
            token = data["js"].get("token", "")
            random = data["js"].get("random", "")
            return token, random
        else:
            print("Handshake: Unexpected response", data)
            return None, None
    except Exception as e:
        print(f"Handshake error: {e}")
        return None, None

def get_profile(server_url, mac, token, random, serial, device_id1, device_id2, signature):
    """Get profile info including expiry date"""
    params = {
        "type": "stb",
        "action": "get_profile",
        "hd": "1",
        "ver": quote("ImageDescription: 0.2.18-r14-pub-250; ImageDate: Fri Jan 15 15:20:44 EET 2016; PORTAL version: 5.1.0; API Version: JS API version: 328; STB API version: 134; Player Engine version: 0x566"),
        "num_banks": "2",
        "sn": serial,
        "stb_type": "MAG250",
        "image_version": "218",
        "video_out": "hdmi",
        "device_id": device_id1,
        "device_id2": device_id2,
        "signature": signature,
        "auth_second_step": "1",
        "hw_version": "1.7-BD-00",
        "not_valid_token": "0",
        "client_type": "STB",
        "hw_version_2": "36da041e6358ee8f8801105e36a63474",
        "timestamp": int(time.time()),
        "api_signature": "263",
        "metrics": json.dumps({"mac": mac, "sn": serial, "model": "MAG250", "type": "STB", "uid": "", "random": random}),
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    url = server_url
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data:
            expiry = data["js"].get("expirydate") or data["js"].get("expire_billing_date")
            if expiry:
                return expiry
        else:
            print("Profile: Unexpected response", data)
        return None
    except Exception as e:
        print(f"Profile error: {e}")
        return None

def get_channels(server_url, mac, token):
    """Get all channels list"""
    params = {
        "type": "itv",
        "action": "get_all_channels",
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    url = server_url
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data and "data" in data["js"]:
            return data["js"]["data"]
        else:
            print("Channels: Unexpected response", data)
            return []
    except Exception as e:
        print(f"Channels error: {e}")
        return []

def get_genres(server_url, mac, token):
    """Get genres mapping"""
    params = {
        "type": "itv",
        "action": "get_genres",
        "JsHttpRequest": "1-xml"
    }
    headers = HEADERS.copy()
    headers["Referer"] = server_url.replace("/server/load.php", "/c/")
    headers["Cookie"] = f"mac={mac}; stb_lang=en; timezone=GMT"
    headers["Authorization"] = f"Bearer {token}"
    url = server_url
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        genres = {}
        if "js" in data and isinstance(data["js"], list):
            for g in data["js"]:
                if "id" in g and "title" in g:
                    genres[str(g["id"])] = g["title"]
        return genres
    except Exception as e:
        print(f"Genres error: {e}")
        return {}

def create_link(server_url, mac, token, cmd):
    """Get stream URL from cmd"""
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
    url = server_url
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "js" in data and "cmd" in data["js"]:
            return data["js"]["cmd"]
        else:
            return None
    except Exception as e:
        print(f"Create link error: {e}")
        return None

def is_sports_channel(channel, genres):
    """Determine if channel is sports and not excluded"""
    title = channel.get("name", "").lower()
    genre_id = str(channel.get("tv_genre_id", ""))
    genre_title = genres.get(genre_id, "").lower()
    # Combine title and genre for matching
    text = title + " " + genre_title
    # Check if it's sports
    sports = any(kw in text for kw in SPORTS_KEYWORDS)
    if not sports:
        return False
    # Exclude specific sports
    excluded = any(ex in text for ex in EXCLUDE_SPORTS)
    return not excluded

def main():
    # Read Mac_list.txt
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
                url = parts[0].strip()
                mac = parts[1].strip()
                portals.append((url, mac))
            else:
                print(f"Skipping invalid line: {line}")
    
    if not portals:
        print("No portals found in Mac_list.txt")
        sys.exit(1)
    
    # For each portal, try to get expiry
    best_portal = None
    best_expiry_date = None
    best_days_left = -1
    
    for url, mac in portals:
        print(f"Checking portal: {url} - MAC: {mac}")
        server_url = clean_url(url)
        # Handshake
        token, random = handshake(server_url, mac)
        if not token:
            print("  Handshake failed, skipping.")
            continue
        # Get profile expiry
        expiry_str = get_profile(server_url, mac, token, random,
                                 DEFAULT_SERIAL, DEFAULT_DEVICE_ID1,
                                 DEFAULT_DEVICE_ID2, DEFAULT_SIGNATURE)
        if not expiry_str:
            print("  Failed to get expiry, skipping.")
            continue
        # Parse expiry (format: YYYY-MM-DD or similar)
        try:
            expiry_date = datetime.strptime(expiry_str.split()[0], "%Y-%m-%d")
            days_left = (expiry_date - datetime.now()).days
            print(f"  Expiry: {expiry_str}, days left: {days_left}")
            if days_left > best_days_left:
                best_days_left = days_left
                best_portal = (url, mac, token, random, server_url)
                best_expiry_date = expiry_str
        except Exception as e:
            print(f"  Error parsing expiry: {e}")
            continue
    
    if not best_portal:
        print("No valid portal found.")
        sys.exit(1)
    
    url, mac, token, random, server_url = best_portal
    print(f"Selected portal: {url} (expires {best_expiry_date}, {best_days_left} days left)")
    
    # Get channels and genres
    channels = get_channels(server_url, mac, token)
    if not channels:
        print("No channels retrieved.")
        sys.exit(1)
    genres = get_genres(server_url, mac, token)
    print(f"Retrieved {len(channels)} channels, {len(genres)} genres.")
    
    # Filter sports channels
    sports_channels = []
    for ch in channels:
        if is_sports_channel(ch, genres):
            sports_channels.append(ch)
    print(f"Found {len(sports_channels)} sports channels after filtering.")
    
    # Generate M3U
    m3u_content = "#EXTM3U\n"
    for ch in sports_channels:
        # Get stream URL
        cmd = ch.get("cmd", "")
        if not cmd:
            continue
        # Try to get real stream URL via create_link
        stream_url = create_link(server_url, mac, token, cmd)
        if not stream_url:
            # Fallback to cmd if create_link fails (maybe it's already a URL)
            if cmd.startswith("http"):
                stream_url = cmd
            else:
                continue
        # Clean URL (remove ffmpeg prefix if any)
        stream_url = stream_url.replace("ffmpeg ", "").replace("ffrt ", "")
        # Prepare metadata
        tvg_id = ch.get("id", "")
        tvg_name = ch.get("name", "")
        tvg_logo = ch.get("logo", "")
        genre_id = str(ch.get("tv_genre_id", ""))
        group_title = genres.get(genre_id, "Sports")
        # Write EXTINF line
        m3u_content += f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" group-title="{group_title}",{tvg_name}\n'
        m3u_content += f"{stream_url}\n"
    
    # Write to file
    with open("Mac_playlist.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)
    print("Playlist generated: Mac_playlist.m3u")

if __name__ == "__main__":
    main()
