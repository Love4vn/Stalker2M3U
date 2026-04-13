#!/usr/bin/env python3
"""
generate_playlist.py - Tạo M3U playlist từ danh sách Stalker portal trong Mac_list.txt

Sử dụng:
    python generate_playlist.py [--input Mac_list.txt] [--output S_playlist.m3u] 
                              [--proxy-base https://your-proxy.com] [--no-proxy]
                              [--concurrency 5] [--sports-only]
"""

import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import List, Dict, Optional, Set
import argparse

sys.path.insert(0, str(Path(__file__).parent))

from app.services.stalker_async import StalkerClient
from app.services.text_parser import extract_portal_mac_pairs, clean_stalker_url
from app.services.base import normalize_mac, MAG200_USER_AGENT, MAG250_XUA
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Từ khóa nhận diện kênh thể thao (không phân biệt hoa thường)
SPORTS_KEYWORDS = [
    "sport", "espn", "sky sports", "bt sport", "bein", "dazn", "nba", "nfl", "mlb",
    "nhl", "premier league", "la liga", "serie a", "bundesliga", "champions league",
    "europa league", "world cup", "tennis", "atp", "wta", "grand slam", "f1", "motogp",
    "nascar", "ufc", "wwe", "boxing", "golf", "olympic", "thể thao", "bóng đá",
    "vtc", "k+", "fox sports", "star sports", "arena sport", "sport tv"
]

def is_sports_channel(name: str, group: str) -> bool:
    """Kiểm tra xem kênh có phải thể thao dựa trên tên hoặc nhóm."""
    text = f"{name} {group}".lower()
    return any(keyword in text for keyword in SPORTS_KEYWORDS)


class M3UGenerator:
    def __init__(self, proxy_base_url: Optional[str] = None, use_proxy: bool = True,
                 concurrency: int = 5, sports_only: bool = False):
        self.proxy_base = proxy_base_url.rstrip("/") if proxy_base_url else None
        self.use_proxy = use_proxy
        self.concurrency = concurrency
        self.sports_only = sports_only
        self.semaphore = asyncio.Semaphore(concurrency)

        if self.use_proxy and not self.proxy_base:
            raise ValueError("PROXY_BASE_URL is required when using proxy mode")

    async def process_portal(self, url: str, mac: str) -> Optional[Dict]:
        mac_norm = normalize_mac(mac)
        async with StalkerClient(url, mac_norm, timeout=settings.request_timeout) as client:
            try:
                if not await client.handshake():
                    logger.warning(f"Handshake failed: {url} ({mac})")
                    return None

                # Lấy token và cookies để dùng cho header khi không dùng proxy
                portal_headers = {}
                if not self.use_proxy:
                    # Lấy token từ client (đã có sau handshake)
                    token = client._token
                    # Lấy cookie từ session cookie jar
                    cookies = {}
                    if client._session and client._session.cookie_jar:
                        for cookie in client._session.cookie_jar:
                            cookies[cookie.key] = cookie.value
                    # Build header options
                    portal_headers["token"] = token
                    portal_headers["cookies"] = cookies

                exp_info = await client.get_expiration_info()
                expiry = exp_info.expiration or "Unlimited"

                # Lấy danh sách kênh
                itv_info = await client.get_itv_info()
                channels_raw = None
                if isinstance(itv_info, dict):
                    channels_raw = itv_info.get("channels") or itv_info.get("data") or itv_info.get("itv_items")
                if not channels_raw:
                    channels_raw = await client.get_channels()

                all_channels = []
                if isinstance(channels_raw, dict) and "data" in channels_raw:
                    all_channels = channels_raw["data"]
                elif isinstance(channels_raw, list):
                    all_channels = channels_raw

                if not all_channels:
                    logger.warning(f"No channels found for {url}")
                    return None

                # Lấy genres (không bắt buộc)
                genres_raw = await client.get_genres() or await client.get_itv_groups()
                genres = []
                if isinstance(genres_raw, dict) and "data" in genres_raw:
                    genres = genres_raw["data"]
                elif isinstance(genres_raw, list):
                    genres = genres_raw

                genre_map = {}
                for g in genres:
                    if isinstance(g, dict):
                        gid = str(g.get("id", ""))
                        title = str(g.get("title") or g.get("name") or gid)
                        if gid:
                            genre_map[gid] = title

                processed_channels = []
                for ch in all_channels:
                    if not isinstance(ch, dict):
                        continue

                    name = str(ch.get("name", "Unknown")).strip()
                    cmd = ch.get("cmd", "")
                    logo = ch.get("logo", "")

                    cat_id = "0"
                    for key in ["tv_genre_id", "category_id", "genre_id", "group_id"]:
                        val = ch.get(key)
                        if val is not None and str(val) != "":
                            cat_id = str(val)
                            break
                    group_title = genre_map.get(cat_id, "Uncategorized")

                    # Lọc kênh thể thao nếu yêu cầu
                    if self.sports_only and not is_sports_channel(name, group_title):
                        continue

                    # Tạo stream link (proxy hoặc trực tiếp)
                    stream_info = await self._build_stream_info(client, cmd, url, mac_norm, portal_headers)
                    if not stream_info:
                        continue

                    logo_url = None
                    if logo and not logo.startswith("data:"):
                        if logo.startswith("/"):
                            logo = url.rstrip("/") + logo
                        elif not logo.startswith("http"):
                            logo = url.rstrip("/") + "/" + logo

                        if self.proxy_base:
                            logo_b64 = base64.b64encode(logo.encode()).decode()
                            logo_url = f"{self.proxy_base}/api/proxy_logo?target={logo_b64}"
                        else:
                            logo_url = logo

                    processed_channels.append({
                        "name": name,
                        "stream_url": stream_info["url"],
                        "logo": logo_url,
                        "group": group_title,
                        "extvlc_opts": stream_info.get("extvlc_opts", [])
                    })

                logger.info(f"✅ {url}: {len(processed_channels)} channels (filtered), expiry: {expiry}")
                return {
                    "url": url,
                    "mac": mac_norm,
                    "expiry": expiry,
                    "channels": processed_channels
                }

            except Exception as e:
                logger.error(f"Error processing {url}: {e}")
                return None

    async def _build_stream_info(self, client: StalkerClient, cmd: str, portal_url: str,
                                 mac: str, portal_headers: Dict) -> Optional[Dict]:
        """
        Trả về dict với 'url' và danh sách 'extvlc_opts' nếu không dùng proxy.
        """
        if not cmd:
            return None

        if cmd.startswith("http://") or cmd.startswith("https://"):
            stream_target = cmd
        else:
            link_res = await client.create_link(cmd)
            if isinstance(link_res, str):
                stream_target = link_res
            elif isinstance(link_res, dict) and "cmd" in link_res:
                stream_target = link_res["cmd"]
            else:
                return None

        clean_target = clean_stalker_url(stream_target, portal_url)
        if not clean_target:
            return None

        if self.use_proxy:
            target_b64 = base64.b64encode(clean_target.encode()).decode()
            origin_b64 = base64.b64encode(portal_url.encode()).decode()
            return {"url": f"{self.proxy_base}/api/proxy_stream?target={target_b64}&mac={mac}&origin={origin_b64}"}
        else:
            # Xây dựng các EXTVLCOPT
            extvlc_opts = []
            # User-Agent
            extvlc_opts.append(f"#EXTVLCOPT:http-user-agent={MAG200_USER_AGENT}")
            # X-User-Agent (nếu cần, nhưng VLC có thể không hỗ trợ custom header khác)
            # Ta có thể thêm bằng http-header (VLC 3.0+)
            # X-User-Agent không bắt buộc, nhưng thêm vào cũng không sao
            extvlc_opts.append(f"#EXTVLCOPT:http-header=X-User-Agent: {MAG250_XUA}")
            # Cookie
            cookie_parts = []
            if portal_headers.get("cookies"):
                for k, v in portal_headers["cookies"].items():
                    cookie_parts.append(f"{k}={v}")
            if cookie_parts:
                cookie_str = "; ".join(cookie_parts)
                extvlc_opts.append(f"#EXTVLCOPT:http-cookie={cookie_str}")
            # Authorization
            if portal_headers.get("token"):
                extvlc_opts.append(f"#EXTVLCOPT:http-header=Authorization: Bearer {portal_headers['token']}")
            # Referer
            extvlc_opts.append(f"#EXTVLCOPT:http-referrer={portal_url.rstrip('/')}/")

            return {"url": clean_target, "extvlc_opts": extvlc_opts}

    async def generate(self, input_file: Path, output_file: Path):
        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            return

        text = input_file.read_text(encoding="utf-8")
        pairs = extract_portal_mac_pairs(text)
        if not pairs:
            logger.error("No portal/MAC pairs found in input file.")
            return

        logger.info(f"Found {len(pairs)} pairs. Starting checks (concurrency={self.concurrency})...")

        tasks = [self.process_portal(url, mac) for url, mac in pairs]
        results = []
        for coro in asyncio.as_completed(tasks):
            res = await coro
            if res and res.get("channels"):
                results.append(res)

        logger.info(f"Successfully processed {len(results)} portals with channels.")

        if not results:
            logger.warning("No working portals with channels. M3U not created.")
            return

        with output_file.open("w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for portal in results:
                for ch in portal["channels"]:
                    # Dòng thông tin kênh
                    f.write(f'#EXTINF:-1 tvg-logo="{ch["logo"] or ""}" group-title="{ch["group"]}",{ch["name"]}\n')
                    # Thêm các EXTVLCOPT nếu có
                    if not self.use_proxy and ch.get("extvlc_opts"):
                        for opt in ch["extvlc_opts"]:
                            f.write(opt + "\n")
                    f.write(f"{ch['stream_url']}\n")

        logger.info(f"M3U playlist saved to {output_file}")


async def main():
    parser = argparse.ArgumentParser(description="Generate M3U playlist from Stalker portals")
    parser.add_argument("--input", default="Mac_list.txt")
    parser.add_argument("--output", default="S_playlist.m3u")
    parser.add_argument("--proxy-base", help="Base URL of the STBcheck proxy server")
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy streaming")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--sports-only", action="store_true", help="Only include sports channels")
    args = parser.parse_args()

    use_proxy = not args.no_proxy
    proxy_base = args.proxy_base or getattr(settings, "proxy_base_url", None)

    if use_proxy and not proxy_base:
        logger.error("PROXY_BASE_URL is required when using proxy mode.")
        sys.exit(1)

    generator = M3UGenerator(
        proxy_base_url=proxy_base,
        use_proxy=use_proxy,
        concurrency=args.concurrency,
        sports_only=args.sports_only
    )
    await generator.generate(Path(args.input), Path(args.output))


if __name__ == "__main__":
    asyncio.run(main())
