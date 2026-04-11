"""
Text parsing utilities for extracting portal/MAC pairs and cleaning URLs.
"""

import re
from typing import List, Tuple, Optional


def extract_portal_mac_pairs(text: str) -> List[Tuple[str, str]]:
    """
    Extract portal URL and MAC address pairs from text.

    Handles various formats including:
    - Labeled: PORTAL : http://... MAC : 00:1A:...
    - CSV: http://example.com/c/,00:1A:79:xx:xx:xx
    - Space-separated: http://example.com/c/ 00:1A:79:xx:xx:xx

    Args:
        text: Text containing portal URLs and MAC addresses

    Returns:
        List of tuples (url, mac_address)
    """
    pairs = []

    # Pattern 1: Labeled format (PORTAL/MAC with separators)
    url_pattern = r"(?:PORTAL|Panel|Server|Host|URL|🛰|╭─•)\s*[:➤\- ]+\s*(https?://\S+)"
    mac_pattern = r"(?:MAC|Mac|ID|✅|├─•)\s*[:➤\- ]+\s*([0-9A-Fa-f:]{17}|(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})"

    url_matches = list(re.finditer(url_pattern, text, re.IGNORECASE))
    mac_matches = list(re.finditer(mac_pattern, text, re.IGNORECASE))

    if url_matches and mac_matches:
        for u_idx, u_match in enumerate(url_matches):
            u_start = u_match.start()
            url = u_match.group(1).rstrip("/")
            block_start = u_start
            block_end = (
                url_matches[u_idx + 1].start()
                if u_idx + 1 < len(url_matches)
                else len(text)
            )
            look_back = 200

            found_for_this_url = False
            for m_match in mac_matches:
                m_start = m_match.start()
                if (m_start >= block_start and m_start < block_end) or (
                    m_start < block_start and m_start >= max(0, block_start - look_back)
                ):
                    mac = m_match.group(1).upper().replace("-", ":")
                    pairs.append((url, mac))
                    found_for_this_url = True

            if not found_for_this_url:
                best_mac = None
                min_dist = 500
                for m_match in mac_matches:
                    dist = abs(m_match.start() - u_start)
                    if dist < min_dist:
                        best_mac = m_match.group(1).upper().replace("-", ":")
                        min_dist = dist
                if best_mac:
                    pairs.append((url, best_mac))

    # Pattern 2: CSV or space-separated on each line (supports comments)
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Try CSV: URL,MAC
        if ',' in line:
            parts = line.split(',', 1)
            if len(parts) == 2:
                url_part = parts[0].strip()
                mac_part = parts[1].strip()
                if url_part.startswith('http') and re.match(r'^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$', mac_part.replace(':', '')):
                    mac_clean = mac_part.upper().replace('-', ':').replace(':', '')
                    if len(mac_clean) == 12:
                        mac_formatted = ':'.join(mac_clean[i:i+2] for i in range(0, 12, 2))
                        pairs.append((url_part.rstrip('/'), mac_formatted))

        # Try space-separated: URL MAC
        else:
            parts = line.split()
            if len(parts) >= 2:
                url_part = parts[0]
                mac_part = parts[1]
                if url_part.startswith('http') and re.match(r'^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$', mac_part.replace(':', '')):
                    mac_clean = mac_part.upper().replace('-', ':').replace(':', '')
                    if len(mac_clean) == 12:
                        mac_formatted = ':'.join(mac_clean[i:i+2] for i in range(0, 12, 2))
                        pairs.append((url_part.rstrip('/'), mac_formatted))

    # Remove duplicates while preserving order
    seen = set()
    unique_pairs = []
    for url, mac in pairs:
        key = f"{url}:{mac}"
        if key not in seen:
            seen.add(key)
            unique_pairs.append((url, mac))

    return unique_pairs


def clean_stalker_url(raw_url: str, portal_url: Optional[str] = None) -> Optional[str]:
    """
    Clean a Stalker URL by removing prefixes like 'ffmpeg', 'ffrt', 'solution'.

    If portal_url is provided and the URL contains 'localhost', it will be
    replaced with the portal's hostname to handle older Stalker portals that
    return local network commands like 'ffmpeg http://localhost/ch/123'.

    Args:
        raw_url: Raw URL string that may contain prefixes
        portal_url: Optional portal base URL for localhost replacement

    Returns:
        Cleaned URL string or None if input is invalid
    """
    if not raw_url:
        return None
    u = str(raw_url).strip(" '\"")
    u = re.sub(r"^(ffmpeg|ffrt|solution)\s+", "", u)

    # Replace localhost with portal hostname if provided and URL contains localhost
    if portal_url and "localhost" in u.lower():
        from urllib.parse import urlparse

        try:
            parsed_portal = urlparse(portal_url)
            portal_hostname = parsed_portal.netloc or parsed_portal.path.split("/")[0]
            if portal_hostname:
                u = re.sub(
                    r"localhost(?=[:/]|$)", portal_hostname, u, flags=re.IGNORECASE
                )
        except Exception:
            pass  # Keep original URL if parsing fails

    return u
