#!/usr/bin/env python3
"""
Stalker to M3U converter – Reads a list of portals (URL, MAC) from Mac_list.txt,
tests each, picks the three with the longest remaining subscription, fetches
sports channels, and outputs a playlist (Mac_playlist.m3u).
"""

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import requests


# ----------------------------------------------------------------------
# StalkerLite – Minimal Stalker Portal Engine (PHP‑like translation)
# ----------------------------------------------------------------------
class StalkerLite:
    def __init__(self, url: str, mac: str, model: str = "MAG250",
                 extras: Optional[Dict] = None, existing_token: str = ""):
        self.mac = mac.upper().strip()
        self.model = model
        self.token = existing_token
        self.extras = extras or {}

        clean_url = self._sanitize_url(url)
        self.server_url = self._build_server_url(clean_url)
        self.portal_base = self._build_portal_base(clean_url)
        self.device_info = self._make_device_info()
        self.headers = self._make_headers()
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _sanitize_url(self, url: str) -> str:
        url = url.rstrip("/")
        url = re.sub(r"/c/?$", "", url)
        url = re.sub(r"/stalker_portal/?$", "", url)
        return url

    def _build_server_url(self, clean: str) -> str:
        if "/stalker_portal" in clean:
            return clean + "/server/load.php"
        return clean + "/stalker_portal/server/load.php"

    def _build_portal_base(self, clean: str) -> str:
        if "/stalker_portal" in clean:
            return clean + "/c/"
        return clean + "/stalker_portal/c/"

    def _make_device_info(self) -> Dict[str, str]:
        mac = self.mac
        sn = hashlib.md5(mac.encode()).hexdigest().upper()
        sn_cut = self.extras.get("sn_cut", sn[:13])
        device_id = self.extras.get(
            "device_id", hashlib.sha256(mac.encode()).hexdigest().upper()
        )
        device_id2 = self.extras.get("device_id2", device_id)
        signature = self.extras.get(
            "signature", hashlib.sha256((sn_cut + mac).encode()).hexdigest().upper()
        )
        return {
            "mac": mac,
            "sn": sn,
            "snCut": sn_cut,
            "deviceId": device_id,
            "deviceId2": device_id2,
            "signature": signature,
            "model": self.model,
        }

    def _make_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
                          "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
            "X-User-Agent": f"Model: {self.model}; Link: WiFi",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "Keep-Alive",
            "Cookie": f"mac={self.mac}; stb_lang=en; timezone=GMT",
            "Referer": self.portal_base,
        }

    def _auth_headers(self) -> Dict[str, str]:
        h = self.headers.copy()
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str, timeout: int = 20, use_auth: bool = True) -> Optional[Any]:
        headers = self._auth_headers() if use_auth else self.headers
        try:
            resp = self.session.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return None
            data = resp.json()
            # Many Stalker responses wrap data in a "js" object
            if isinstance(data, dict) and "js" in data:
                return data["js"]
            return data
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handshake(self) -> Dict[str, Any]:
        url = f"{self.server_url}?type=stb&action=handshake&prehash={self.mac}&token=&JsHttpRequest=1-xml"
        data = self._get(url)
        if not data:
            return {"success": False, "error": "Handshake failed"}
        token = data.get("token", "")
        if not token:
            return {"success": False, "error": "No token received", "raw": data}
        self.token = token
        return {"success": True, "token": token, "random": data.get("random", "")}

    def get_profile(self) -> Dict[str, str]:
        if not self.token:
            return {}
        di = self.device_info
        params = {
            "type": "stb",
            "action": "get_profile",
            "hd": "1",
            "sn": di["snCut"],
            "stb_type": di["model"],
            "device_id": di["deviceId"],
            "device_id2": di["deviceId2"],
            "signature": di["signature"],
            "timestamp": int(time.time()),
            "metrics": json.dumps(
                {"mac": di["mac"], "sn": di["sn"], "model": di["model"], "type": "STB"}
            ),
            "JsHttpRequest": "1-xml",
        }
        url = f"{self.server_url}?{requests.compat.urlencode(params)}"
        data = self._get(url)
        if not data:
            return {}
        return {
            "login": data.get("login", ""),
            "id": str(data.get("id", "")),
            "name": data.get("name") or data.get("fname", ""),
            "expiry": data.get("expire_billing_date", "") or data.get("phone", ""),
            "tariff": data.get("tariff_plan", {}).get("name", "")
            if isinstance(data.get("tariff_plan"), dict)
            else "",
        }

    def ensure_token(self) -> bool:
        if self.token:
            prof = self.get_profile()
            if prof.get("id") or prof.get("login") or prof.get("name"):
                return True
            self.token = ""
        hs = self.handshake()
        if hs["success"]:
            self.get_profile()
            return True
        return False

    def get_genres(self) -> Dict[str, str]:
        if not self.ensure_token():
            return {}
        endpoints = [
            "?type=itv&action=get_genres&JsHttpRequest=1-xml",
            "?type=itv&action=get_all_genres&JsHttpRequest=1-xml",
        ]
        for ep in endpoints:
            data = self._get(self.server_url + ep, timeout=30)
            if data:
                genres_list = data.get("data") or data
                if isinstance(genres_list, list):
                    out = {}
                    for g in genres_list:
                        if isinstance(g, dict):
                            gid = str(g.get("id") or g.get("genre_id", "0"))
                            title = g.get("title") or g.get("name", "General")
                            out[gid] = title
                    return out
        return {}

    def get_channels(self) -> List[Dict[str, Any]]:
        if not self.ensure_token():
            return []
        genres = self.get_genres()

        # try the fast all‑channels endpoint
        data = self._get(
            self.server_url + "?type=itv&action=get_all_channels&JsHttpRequest=1-xml",
            timeout=120,
        )
        raw_channels = []
        if data:
            if "data" in data:
                raw_channels = data["data"]
            elif isinstance(data, list):
                raw_channels = data
            else:
                # fallback: search for any list in the data
                for v in data.values():
                    if isinstance(v, list):
                        raw_channels = v
                        break

        if not raw_channels:
            raw_channels = self._fetch_channels_paginated()

        channels = []
        for i, ch in enumerate(raw_channels):
            if not isinstance(ch, dict):
                continue
            gid = str(ch.get("tv_genre_id") or ch.get("genre_id", "0"))
            name = ch.get("name") or ch.get("title", f"Channel {i+1}")
            cmd = ch.get("cmd", "")
            logo = ch.get("logo", "")
            number = ch.get("number", i)
            channels.append(
                {
                    "id": str(ch.get("id") or ch.get("channel_id", i)),
                    "name": name.strip(),
                    "cmd": cmd,
                    "logo": self._build_logo_url(logo),
                    "genre_id": gid,
                    "genre_name": genres.get(gid, "General"),
                    "number": int(number),
                }
            )
        return channels

    def _fetch_channels_paginated(self) -> List[Dict]:
        all_channels = []
        page = 0
        page_size = 500
        while True:
            params = {
                "type": "itv",
                "action": "get_ordered_list",
                "genre": "*",
                "force_ch_link_check": "",
                "fav": "0",
                "sortby": "number",
                "p": page,
                "JsHttpRequest": "1-xml",
            }
            url = f"{self.server_url}?{requests.compat.urlencode(params)}"
            data = self._get(url, timeout=60)
            if not data:
                break
            ch_list = data.get("data", [])
            if not ch_list:
                break
            all_channels.extend(ch_list)
            total = int(data.get("total_items") or data.get("max_page_items", 0))
            if total and len(all_channels) >= total:
                break
            page += 1
            if page > 100:  # safety
                break
        return all_channels

    def create_link(self, cmd: str) -> str:
        cmd = cmd.strip()
        # strip ffmpeg prefix
        if cmd.lower().startswith("ffmpeg "):
            cmd = cmd[7:].strip()
        # if it is already a direct HTTP URL (and not ffrt)
        if re.match(r"^https?://", cmd, re.I) and not cmd.lower().startswith("ffrt"):
            m = re.search(r"(https?://[^\s\"']+)", cmd, re.I)
            return m.group(1) if m else cmd

        # call create_link API
        params = {
            "type": "itv",
            "action": "create_link",
            "cmd": cmd,
            "forced_storage": "undefined",
            "disable_ad": "1",
            "JsHttpRequest": "1-xml",
        }
        url = f"{self.server_url}?{requests.compat.urlencode(params)}"
        data = self._get(url, timeout=15)
        if data:
            stream = data.get("cmd") or data.get("url", "")
            if stream:
                if stream.lower().startswith("ffmpeg "):
                    stream = stream[7:].strip()
                m = re.search(r"(https?://[^\s\"']+)", stream, re.I)
                if m:
                    return m.group(1)
                return stream
        return ""

    def _build_logo_url(self, logo: str) -> str:
        if not logo:
            return ""
        if re.match(r"^https?://", logo, re.I):
            return logo
        base = re.sub(r"/server/load\.php$", "", self.server_url).rstrip("/")
        return f"{base}/misc/logos/320/{logo.lstrip('/')}"

    def connect(self) -> Dict[str, Any]:
        hs = self.handshake()
        if not hs["success"]:
            return {"success": False, "error": hs.get("error", "Handshake failed")}
        profile = self.get_profile()
        return {
            "success": True,
            "token": hs["token"],
            "random": hs.get("random", ""),
            "device": self.device_info,
            "server_url": self.server_url,
            "portal_base": self.portal_base,
            "profile": profile,
            "saved_at": datetime.now().isoformat(),
        }


# ----------------------------------------------------------------------
# Portal testing helpers (robust handshake detection)
# ----------------------------------------------------------------------
def parse_mac_list(filename: str) -> List[Tuple[str, str]]:
    """Read Mac_list.txt, each line: url,mac"""
    portals = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                url = parts[0].strip()
                mac = parts[1].strip()
                portals.append((url, mac))
    return portals


def get_expiry_date(profile: dict) -> Optional[datetime]:
    expiry_str = profile.get("expiry", "")
    if not expiry_str:
        return None
    # try common date formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(expiry_str, fmt)
        except ValueError:
            continue
    # try as Unix timestamp (seconds)
    try:
        return datetime.fromtimestamp(int(expiry_str))
    except (ValueError, TypeError):
        pass
    return None


def get_token_and_server(url: str, mac: str) -> Tuple[Optional[str], Optional[str]]:
    """Try multiple handshake endpoints to obtain a token and return (token, base_url) or (None, None)."""
    base = url.rstrip('/')
    # Common handshake patterns
    patterns = [
        ('/stalker_portal/server/load.php', 
         f"{base}/stalker_portal/server/load.php?type=stb&action=handshake&prehash={mac}&token=&JsHttpRequest=1-xml"),
        ('/server/load.php', 
         f"{base}/server/load.php?type=stb&action=handshake&prehash={mac}&token=&JsHttpRequest=1-xml"),
        ('/portal.php', 
         f"{base}/portal.php?type=stb&action=handshake&prehash={mac}&token=&JsHttpRequest=1-xml"),
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
        'X-User-Agent': 'Model: MAG250; Link: WiFi',
        'Cookie': f'mac={mac}; stb_lang=en; timezone=Europe/Kiev'
    }
    for path, handshake_url in patterns:
        try:
            resp = requests.get(handshake_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                token = data.get('js', {}).get('token') or data.get('token')
                if token:
                    # Return token and the original base URL
                    return token, base
        except Exception:
            continue
    return None, None


def test_portal(url: str, mac: str) -> Optional[Dict]:
    """Test a portal; if active, return dict with stalker instance and expiry date."""
    token, base = get_token_and_server(url, mac)
    if not token:
        return None

    stalker = StalkerLite(url, mac, existing_token=token)

    try:
        channels = stalker.get_channels()
        if not channels:
            return None
    except Exception as e:
        print(f"Channel fetch failed for {url}: {e}")
        return None

    profile = stalker.get_profile()
    expiry_dt = get_expiry_date(profile)

    return {
        "url": url,
        "mac": mac,
        "stalker": stalker,
        "profile": profile,
        "expiry_date": expiry_dt,
    }


# ----------------------------------------------------------------------
# Playlist generation
# ----------------------------------------------------------------------
def generate_playlist(portals: List[Dict], output_file: str):
    """Generate M3U playlist from the selected portals."""
    SPORTS_KEYWORDS = [
        "sport", "sports", "football", "soccer", "tennis", "golf",
        "motorsport", "formula 1", "f1", "hub premier", "premier league",
        "monomax", "astro arena", "spotv", "epl", "tsn", "la liga", "laliga",
        "bundesliga", "seriea", "serie a", "uefa"
    ]
    EXCLUDE_KEYWORDS = [
        "baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ",
        "handball", "bóng ném", "hockey", "khúc côn cầu", "bóng bầu dục",
        "u23", "u21", "u19", "youth", "junior", "reserve",
        "second division", "liga 2", "serie b", "2. bundesliga", "championship"
    ]

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write(f"# Generated at {datetime.now().isoformat()}\n\n")

        for portal in portals:
            print(f"Processing portal: {portal['url']}")
            stalker = portal["stalker"]
            try:
                channels = stalker.get_channels()
                print(f"  Total channels: {len(channels)}")
                sport_channels = []
                for ch in channels:
                    name_lower = ch["name"].lower()
                    # Exclude
                    if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
                        continue
                    # Include
                    if any(kw.lower() in name_lower for kw in SPORTS_KEYWORDS):
                        sport_channels.append(ch)

                print(f"  Sport channels: {len(sport_channels)}")
                for ch in sport_channels:
                    stream_url = stalker.create_link(ch["cmd"])
                    if not stream_url:
                        print(f"    Failed to get stream URL for {ch['name']}")
                        continue

                    def esc(s: str) -> str:
                        return s.replace('"', "&quot;")

                    group_title = f"Sports ({portal['url']})"
                    f.write(
                        f'#EXTINF:-1 tvg-id="{esc(ch["id"])}" '
                        f'tvg-name="{esc(ch["name"])}" '
                        f'tvg-logo="{esc(ch["logo"])}" '
                        f'group-title="{esc(group_title)}" '
                        f'tvg-chno="{ch["number"]}",{esc(ch["name"])}\n'
                    )
                    f.write(f"{stream_url}\n")
            except Exception as e:
                print(f"  Error while processing portal: {e}")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    if len(sys.argv) > 1:
        mac_file = sys.argv[1]
    else:
        mac_file = "Mac_list.txt"

    if not os.path.exists(mac_file):
        print(f"Error: {mac_file} not found.")
        sys.exit(1)

    portals = parse_mac_list(mac_file)
    print(f"Found {len(portals)} portals in {mac_file}")

    # Test each portal
    valid_portals = []
    for url, mac in portals:
        print(f"Testing {url} {mac}")
        res = test_portal(url, mac)
        if res:
            valid_portals.append(res)
            expiry = res["expiry_date"].strftime("%Y-%m-%d") if res["expiry_date"] else "unknown"
            print(f"  -> Active, expiry: {expiry}")
        else:
            print("  -> Failed or expired")

    # Sort by remaining time (longest first)
    valid_portals.sort(
        key=lambda x: x["expiry_date"] if x["expiry_date"] else datetime.min, reverse=True
    )
    top_three = valid_portals[:3]
    print(f"\nSelected {len(top_three)} portal(s):")
    for p in top_three:
        expiry_str = p["expiry_date"].strftime("%Y-%m-%d") if p["expiry_date"] else "unknown"
        print(f"  {p['url']} – expires {expiry_str}")

    if not top_three:
        print("No active portals found. Exiting.")
        sys.exit(0)

    # Generate playlist
    output = "Mac_playlist.m3u"
    generate_playlist(top_three, output)
    print(f"\nPlaylist saved to {output}")


if __name__ == "__main__":
    main()
