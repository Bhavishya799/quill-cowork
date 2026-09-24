import ipaddress
import os
from urllib.parse import urlparse
from typing import Tuple


DEFAULT_ALLOWED = {
    "api.github.com", "github.com", "raw.githubusercontent.com",
    "www.googleapis.com", "oauth2.googleapis.com", "accounts.google.com",
    "gmail.googleapis.com",
    "wikipedia.org", "en.wikipedia.org",
    "slack.com", "api.slack.com", "api.notion.com",
    "api.tavily.com", "api.search.brave.com", "html.duckduckgo.com",
}

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}


def allowlist() -> set:
    extra = os.getenv("ALLOWED_DOMAINS", "")
    return DEFAULT_ALLOWED | {d.strip().lower() for d in extra.split(",") if d.strip()}


def check_egress(url: str) -> Tuple[bool, str]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False, "invalid url"
    if not host:
        return False, "no host"
    if host in BLOCKED_HOSTS:
        return False, f"blocked host: {host}"
    if _is_private(host):
        return False, "private network"
    allow = allowlist()
    if host in allow or any(host.endswith("." + a) for a in allow):
        return True, ""
    return False, f"not in allowlist: {host}"


def _is_private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        parts = host.split(".")
        if len(parts) == 4:
            try:
                o = [int(p) for p in parts]
                if all(0 <= x <= 255 for x in o):
                    return (
                        o[0] == 10
                        or (o[0] == 192 and o[1] == 168)
                        or (o[0] == 172 and 16 <= o[1] <= 31)
                        or (o[0] == 169 and o[1] == 254)
                        or o[0] == 127
                        or o[0] == 0
                    )
            except ValueError:
                pass
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast
    )