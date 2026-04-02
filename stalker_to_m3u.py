import requests
import json
import time
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
import sys
import os

class StalkerLite:
    def __init__(self, url: str, mac: str, model: str = 'MAG250', extras: Optional[Dict] = None, existing_token: str = ''):
        self.mac = mac.upper().strip()
        self.model = model
        self.token = existing_token
        self.extras = extras or {}
        self.clean_url = self.sanitize_url(url)
        self.server_url = self.build_server_url(self.clean_url)
        self.portal_base = self.build_portal_base(self.clean_url)
        self.device_info = self.make_device_info()
        self.headers = self.make_headers()
        self.session = requests.Session()

    def sanitize_url(self, url: str) -> str:
        url = url.rstrip('/')
        url = re.sub(r'/c/?$', '', url)
        url = re.sub(r'/stalker_portal/?$', '', url)
        return url

    def build_server_url(self, clean: str) -> str:
        if '/stalker_portal' in clean:
            return clean + '/server/load.php'
        else:
            return clean + '/stalker_portal/server/load.php'

    def build_portal_base(self, clean: str) -> str:
        if '/stalker_portal' in clean:
            return clean + '/c/'
        else:
            return clean + '/stalker_portal/c/'

    def make_device_info(self) -> Dict[str, str]:
        mac = self.mac
        import hashlib
        sn = hashlib.md5(mac.encode()).hexdigest().upper()
        sn_cut = self.extras.get('sn_cut', sn[:13])
        device_id = self.extras.get('device_id', hashlib.sha256(mac.encode()).hexdigest().upper())
        device_id2 = self.extras.get('device_id2', device_id)
        signature = self.extras.get('signature', hashlib.sha256((sn_cut + mac).encode()).hexdigest().upper())
        return {
            'mac': mac,
            'sn': sn,
            'snCut': sn_cut,
            'deviceId': device_id,
            'deviceId2': device_id2,
            'signature': signature,
            'model': self.model
        }

    def make_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3',
            'X-User-Agent': f'Model: {self.model}; Link: WiFi',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'Keep-Alive',
            'Cookie': f'mac={self.mac}; stb_lang=en; timezone=GMT',
            'Referer': self.portal_base,
        }

    def auth_headers(self) -> Dict[str, str]:
        h = self.headers.copy()
        if self.token:
            h['Authorization'] = f'Bearer {self.token}'
        return h

    def _get(self, url: str, timeout: int = 20, use_auth: bool = True) -> Optional[Dict]:
        headers = self.auth_headers() if use_auth else self.headers
        try:
            resp = self.session.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return None
            # decode json; but response may be JSONP-like? They use JsHttpRequest, but response is JSON.
            data = resp.json()
            # The data may have 'js' key
            if 'js' in data:
                return data['js']
            return data
        except Exception as e:
            return None

    def handshake(self) -> Dict[str, Any]:
        url = f"{self.server_url}?type=stb&action=handshake&prehash={self.mac}&token=&JsHttpRequest=1-xml"
        data = self._get(url)
        if not data:
            return {'success': False, 'error': 'Handshake failed'}
        token = data.get('token') or ''
        if not token:
            return {'success': False, 'error': 'No token received', 'raw': data}
        self.token = token
        return {'success': True, 'token': token, 'random': data.get('random', '')}

    def get_profile(self) -> Dict[str, str]:
        if not self.token:
            return {}
        di = self.device_info
        params = {
            'type': 'stb',
            'action': 'get_profile',
            'hd': '1',
            'sn': di['snCut'],
            'stb_type': di['model'],
            'device_id': di['deviceId'],
            'device_id2': di['deviceId2'],
            'signature': di['signature'],
            'timestamp': int(time.time()),
            'metrics': json.dumps({'mac': di['mac'], 'sn': di['sn'], 'model': di['model'], 'type': 'STB'}),
            'JsHttpRequest': '1-xml'
        }
        url = f"{self.server_url}?{requests.compat.urlencode(params)}"
        data = self._get(url)
        if not data:
            return {}
        return {
            'login': data.get('login', ''),
            'id': str(data.get('id', '')),
            'name': data.get('name') or data.get('fname', ''),
            'expiry': data.get('expire_billing_date', '') or data.get('phone', ''),
            'tariff': data.get('tariff_plan', {}).get('name', '') if isinstance(data.get('tariff_plan'), dict) else ''
        }

    def ensure_token(self) -> bool:
        if self.token:
            # verify token by calling get_profile
            prof = self.get_profile()
            if prof.get('id') or prof.get('login') or prof.get('name'):
                return True
            self.token = ''
        hs = self.handshake()
        if hs['success']:
            self.get_profile()
            return True
        return False

    def get_genres(self) -> Dict[str, str]:
        if not self.ensure_token():
            return {}
        endpoints = [
            '?type=itv&action=get_genres&JsHttpRequest=1-xml',
            '?type=itv&action=get_all_genres&JsHttpRequest=1-xml'
        ]
        for ep in endpoints:
            data = self._get(self.server_url + ep, timeout=30)
            if data:
                genres_list = data.get('data') or data
                if isinstance(genres_list, list):
                    out = {}
                    for g in genres_list:
                        if isinstance(g, dict):
                            gid = str(g.get('id') or g.get('genre_id', '0'))
                            title = g.get('title') or g.get('name', 'General')
                            out[gid] = title
                    return out
        return {}

    def get_channels(self) -> List[Dict[str, Any]]:
        if not self.ensure_token():
            return []
        genres = self.get_genres()
        # try get_all_channels
        data = self._get(self.server_url + '?type=itv&action=get_all_channels&JsHttpRequest=1-xml', timeout=120)
        raw_channels = []
        if data:
            # The data may be directly the list or under 'data'
            if 'data' in data:
                raw_channels = data['data']
            elif isinstance(data, list):
                raw_channels = data
            else:
                # try to find list
                for v in data.values():
                    if isinstance(v, list):
                        raw_channels = v
                        break
        if not raw_channels:
            # fallback to paginated
            raw_channels = self.fetch_channels_paginated()
        channels = []
        for i, ch in enumerate(raw_channels):
            if not isinstance(ch, dict):
                continue
            gid = str(ch.get('tv_genre_id') or ch.get('genre_id', '0'))
            name = ch.get('name') or ch.get('title', f'Channel {i+1}')
            cmd = ch.get('cmd', '')
            logo = ch.get('logo', '')
            number = ch.get('number', i)
            channels.append({
                'id': str(ch.get('id') or ch.get('channel_id', i)),
                'name': name.strip(),
                'cmd': cmd,
                'logo': self.build_logo_url(logo),
                'genre_id': gid,
                'genre_name': genres.get(gid, 'General'),
                'number': int(number)
            })
        return channels

    def fetch_channels_paginated(self) -> List[Dict]:
        all_channels = []
        page = 0
        page_size = 500
        while True:
            params = {
                'type': 'itv',
                'action': 'get_ordered_list',
                'genre': '*',
                'force_ch_link_check': '',
                'fav': '0',
                'sortby': 'number',
                'p': page,
                'JsHttpRequest': '1-xml'
            }
            url = f"{self.server_url}?{requests.compat.urlencode(params)}"
            data = self._get(url, timeout=60)
            if not data:
                break
            ch_list = data.get('data', [])
            if not ch_list:
                break
            all_channels.extend(ch_list)
            total = int(data.get('total_items') or data.get('max_page_items', 0))
            if total and len(all_channels) >= total:
                break
            page += 1
            if page > 100:
                break
        return all_channels

    def create_link(self, cmd: str) -> str:
        cmd = cmd.strip()
        # Strip ffmpeg prefix
        if cmd.lower().startswith('ffmpeg '):
            cmd = cmd[7:].strip()
        # If it's already an HTTP URL (and not ffrt), return as is
        if re.match(r'^https?://', cmd, re.I) and not cmd.lower().startswith('ffrt'):
            # extract the URL (remove any trailing quotes or spaces)
            m = re.search(r'(https?://[^\s"\']+)', cmd, re.I)
            if m:
                return m.group(1)
            return cmd
        # Call create_link API
        params = {
            'type': 'itv',
            'action': 'create_link',
            'cmd': cmd,
            'forced_storage': 'undefined',
            'disable_ad': '1',
            'JsHttpRequest': '1-xml'
        }
        url = f"{self.server_url}?{requests.compat.urlencode(params)}"
        data = self._get(url, timeout=15)
        if data:
            stream = data.get('cmd') or data.get('url', '')
            if stream:
                if stream.lower().startswith('ffmpeg '):
                    stream = stream[7:].strip()
                m = re.search(r'(https?://[^\s"\']+)', stream, re.I)
                if m:
                    return m.group(1)
                return stream
        return ''

    def build_logo_url(self, logo: str) -> str:
        if not logo:
            return ''
        if re.match(r'^https?://', logo, re.I):
            return logo
        base = re.sub(r'/server/load\.php$', '', self.server_url).rstrip('/')
        return f"{base}/misc/logos/320/{logo.lstrip('/')}"

    def connect(self) -> Dict[str, Any]:
        hs = self.handshake()
        if not hs['success']:
            return {'success': False, 'error': hs.get('error', 'Handshake failed')}
        profile = self.get_profile()
        return {
            'success': True,
            'token': hs['token'],
            'random': hs.get('random', ''),
            'device': self.device_info,
            'server_url': self.server_url,
            'portal_base': self.portal_base,
            'profile': profile,
            'saved_at': datetime.now().isoformat()
        }

# Helper functions

def parse_mac_list(filename: str) -> List[tuple]:
    """Parse mac_list.txt, each line: url,mac"""
    portals = []
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                url = parts[0].strip()
                mac = parts[1].strip()
                portals.append((url, mac))
    return portals

def get_expiry_date(profile: dict) -> Optional[datetime]:
    expiry_str = profile.get('expiry', '')
    if not expiry_str:
        return None
    # Try to parse common formats: "2025-12-31", "31/12/2025", timestamp?
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(expiry_str, fmt)
        except:
            continue
    # If it's a Unix timestamp (int)
    try:
        return datetime.fromtimestamp(int(expiry_str))
    except:
        pass
    return None

def test_portal(url: str, mac: str) -> Optional[dict]:
    """Test portal, return dict with token, profile, expiry date if valid"""
    stalker = StalkerLite(url, mac)
    try:
        result = stalker.connect()
        if not result['success']:
            return None
        expiry_dt = get_expiry_date(result['profile'])
        if expiry_dt and expiry_dt < datetime.now():
            return None  # expired
        return {
            'url': url,
            'mac': mac,
            'stalker': stalker,
            'profile': result['profile'],
            'expiry_date': expiry_dt
        }
    except Exception as e:
        print(f"Error testing {url} {mac}: {e}")
        return None

def generate_playlist(portals: List[dict], output_file: str):
    """Generate M3U from the list of portals (already tested and have stalker instance)"""
    # Keywords for filtering
    SPORTS_KEYWORDS = [
        "sport", "sports", "football", "soccer", "tennis", "golf",
        "motorsport", "formula 1", "f1", "hub premier", "premier league",
        "monomax", "astro arena", "spotv", "epl", "tsn", "la liga", "laliga", "bundesliga",
        "seriea", "serie a", "uefa"
    ]
    EXCLUDE_KEYWORDS = [
        "baseball", "cricket", "nfl", "nhl", "rugby", "basketball", "bóng rổ",
        "handball", "bóng ném", "hockey", "khúc côn cầu", "bóng bầu dục",
        "u23", "u21", "u19", "youth", "junior", "reserve",
        "second division", "liga 2", "serie b", "2. bundesliga", "championship"
    ]
    # We'll just include channels that match any SPORTS_KEYWORDS and not EXCLUDE_KEYWORDS
    # We'll also prioritize HD, but that's optional.
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        f.write('# Generated by Stalker to M3U converter\n')
        f.write(f'# Generated at {datetime.now().isoformat()}\n')
        f.write('\n')
        for portal in portals:
            print(f"Processing portal {portal['url']}")
            stalker = portal['stalker']
            try:
                channels = stalker.get_channels()
                print(f"  Total channels: {len(channels)}")
                sport_channels = []
                for ch in channels:
                    name = ch['name'].lower()
                    # Check exclude first
                    if any(kw.lower() in name for kw in EXCLUDE_KEYWORDS):
                        continue
                    if any(kw.lower() in name for kw in SPORTS_KEYWORDS):
                        sport_channels.append(ch)
                print(f"  Sport channels: {len(sport_channels)}")
                for ch in sport_channels:
                    # Get stream URL
                    stream_url = stalker.create_link(ch['cmd'])
                    if not stream_url:
                        print(f"    Failed to create link for {ch['name']}")
                        continue
                    # Write #EXTINF line
                    # tvg-id, tvg-name, tvg-logo, group-title, tvg-chno
                    tvg_id = ch['id']
                    tvg_name = ch['name']
                    tvg_logo = ch['logo']
                    group_title = "Sports"  # or use ch['genre_name'] if it's sports related, but we already filtered
                    # We can set group_title to something like "Sports - {portal['url']}" to differentiate
                    group_title = f"Sports ({portal['url']})"
                    tvg_chno = ch['number']
                    # Escape special characters in attributes
                    def esc(s):
                        return s.replace('"', '&quot;')
                    f.write(f'#EXTINF:-1 tvg-id="{esc(tvg_id)}" tvg-name="{esc(tvg_name)}" tvg-logo="{esc(tvg_logo)}" group-title="{esc(group_title)}" tvg-chno="{tvg_chno}",{esc(tvg_name)}\n')
                    f.write(f'{stream_url}\n')
            except Exception as e:
                print(f"Error processing portal {portal['url']}: {e}")
        # Done

def main():
    if len(sys.argv) > 1:
        mac_file = sys.argv[1]
    else:
        mac_file = 'Mac_list.txt'
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
            expiry = res['expiry_date'].strftime('%Y-%m-%d') if res['expiry_date'] else 'unknown'
            print(f"  -> Active, expiry: {expiry}")
        else:
            print("  -> Failed or expired")
    # Sort by expiry date descending (longest remaining)
    valid_portals.sort(key=lambda x: x['expiry_date'] if x['expiry_date'] else datetime.min, reverse=True)
    # Take top 3
    top_three = valid_portals[:3]
    print(f"Selected top {len(top_three)} portals:")
    for p in top_three:
        print(f"  {p['url']} - expiry: {p['expiry_date']}")
    # Generate playlist
    output = 'Mac_playlist.m3u'
    generate_playlist(top_three, output)
    print(f"Playlist saved to {output}")

if __name__ == '__main__':
    main()
