"""Finding Samsung TVs on the LAN — read-only, nothing is sent to the art channel.

Two searches run together and end in the same request:

- **SSDP** `M-SEARCH` for Samsung's remote-control receiver: quick, but multicast does not leave
  a Docker bridge network;
- a **sweep of the /24**, asking every address for `http://<ip>:8001/api/v2/` — what
  `scripts/tv_probe.py --scan` found the user's Frame with (`docs/research/tv-display.md` §2b).

Either way the facts come from that REST answer: the name, the model, whether it is a Frame, and
the Wi-Fi MAC, which is what recognises the TV again once DHCP has given it another address.

The /24 is the **LAN's**, not this process's: inside Docker the container's own address is on the
bridge network, so `subnet_prefix` prefers an explicit setting, then the public URL's address.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from the_frame_v2.tv.client import normalize_mac

log = logging.getLogger(__name__)

SSDP_ADDRESS = ("239.255.255.250", 1900)
#: What Samsung TVs answer to (the second one is the DIAL service every Tizen TV runs).
SSDP_TARGETS = (
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "urn:dial-multiscreen-org:service:dial:1",
)
REST_PORT = 8001


@dataclass(frozen=True, slots=True)
class DiscoveredTv:
    """One TV that answered, as its REST endpoint describes itself."""

    host: str
    name: str | None = None
    model: str | None = None
    """Marketing model (`modelName`, e.g. `TQ55LS03FAUXXC`)."""
    model_code: str | None = None
    """Model group (`model`, e.g. `25_PTM_FTV`)."""
    frame_support: bool = False
    token_auth: bool = False
    mac: str | None = None
    power_state: str | None = None


Discover = Callable[[str | None], list[DiscoveredTv]]
"""`prefix` (`"192.168.1"`, or None when unknown) → the TVs that answered."""


def _flag(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def parse_device(host: str, payload: Mapping[str, Any]) -> DiscoveredTv | None:
    """The REST answer of one address, or None when it is not a Samsung TV."""
    device = payload.get("device")
    if not isinstance(device, Mapping):
        return None
    kind = f"{device.get('type') or ''} {payload.get('type') or ''}".lower()
    if "samsung" not in kind and "FrameTVSupport" not in device:
        return None
    return DiscoveredTv(
        host=host,
        name=str(device.get("name") or payload.get("name") or "") or None,
        model=str(device.get("modelName") or "") or None,
        model_code=str(device.get("model") or "") or None,
        frame_support=_flag(device.get("FrameTVSupport")),
        token_auth=_flag(device.get("TokenAuthSupport")),
        mac=normalize_mac(device.get("wifiMac")),
        power_state=str(device.get("PowerState") or "") or None,
    )


def parse_ssdp_response(data: bytes) -> str | None:
    """The host of an SSDP answer, from its `LOCATION` header."""
    for line in data.decode("utf-8", errors="replace").splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "location":
            host = urlsplit(value.strip()).hostname
            return host or None
    return None


def fetch_device(host: str, timeout: float = 0.8) -> DiscoveredTv | None:
    """Ask one address for `/api/v2/`. Anything that is not a Samsung answer is None."""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{REST_PORT}/api/v2/", timeout=timeout
        ) as response:
            payload = json.loads(response.read(65536).decode("utf-8", errors="replace"))
    except urllib.error.URLError, OSError, ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return parse_device(host, payload)


def ssdp_hosts(timeout: float = 2.0) -> set[str]:
    """Hosts that answer an `M-SEARCH` for a Samsung TV within `timeout` seconds."""
    found: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except OSError:
        return found
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.25)
        for target in SSDP_TARGETS:
            message = (
                "M-SEARCH * HTTP/1.1\r\n"
                f"HOST: {SSDP_ADDRESS[0]}:{SSDP_ADDRESS[1]}\r\n"
                'MAN: "ssdp:discover"\r\n'
                "MX: 1\r\n"
                f"ST: {target}\r\n\r\n"
            )
            sock.sendto(message.encode(), SSDP_ADDRESS)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            host = parse_ssdp_response(data)
            if host:
                found.add(host)
    except OSError:
        log.debug("SSDP search failed", exc_info=True)
    finally:
        sock.close()
    return found


def _private_ipv4(value: str | None) -> ipaddress.IPv4Address | None:
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address) or not address.is_private:
        return None
    if address.is_loopback or address.is_link_local:
        return None
    return address


def normalize_prefix(value: str) -> str | None:
    """`192.168.1`, `192.168.1.`, `192.168.1.0/24` or `192.168.1.17` → `192.168.1`."""
    text = value.strip().split("/", 1)[0].rstrip(".")
    parts = text.split(".")
    if len(parts) == 4:
        parts = parts[:3]
    if len(parts) != 3 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return None
    return ".".join(str(int(p)) for p in parts)


def subnet_prefix(
    *, configured: str | None, public_url: str | None, lan_ip: str | None
) -> str | None:
    """Which /24 to sweep: the setting, else the public URL's address, else this host's.

    Inside Docker, `lan_ip` is the bridge network's address; the public URL (which the user sets
    for phones) carries the LAN's, so it wins.
    """
    if configured:
        return normalize_prefix(configured)
    if public_url:
        address = _private_ipv4(urlsplit(public_url).hostname)
        if address is not None:
            return normalize_prefix(str(address))
    address = _private_ipv4(lan_ip)
    return normalize_prefix(str(address)) if address is not None else None


def _sweep_hosts(prefix: str | None) -> Iterable[str]:
    if prefix is None:
        return []
    return [f"{prefix}.{last}" for last in range(1, 255)]


def _host_key(tv: DiscoveredTv) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in tv.host.split("."))
    except ValueError:
        return (999,)


def discover(
    prefix: str | None,
    *,
    timeout: float = 0.8,
    ssdp_timeout: float = 2.0,
    workers: int = 64,
    fetch: Callable[[str, float], DiscoveredTv | None] = fetch_device,
    ssdp: Callable[[float], set[str]] = ssdp_hosts,
) -> list[DiscoveredTv]:
    """Every Samsung TV that answers: SSDP and the /24 sweep together, Frames first."""
    found: dict[str, DiscoveredTv] = {}
    with ThreadPoolExecutor(max_workers=max(2, workers)) as pool:
        ssdp_future = pool.submit(ssdp, ssdp_timeout)
        futures = [pool.submit(fetch, host, timeout) for host in _sweep_hosts(prefix)]
        for future in as_completed(futures):
            tv = future.result()
            if tv is not None:
                found[tv.host] = tv
        extra = [host for host in ssdp_future.result() if host not in found]
        for future in as_completed([pool.submit(fetch, host, timeout) for host in extra]):
            tv = future.result()
            if tv is not None:
                found[tv.host] = tv
    return sorted(found.values(), key=lambda tv: (not tv.frame_support, _host_key(tv)))


def find_by_mac(discover_fn: Discover, prefix: str | None, mac: str | None) -> DiscoveredTv | None:
    """The TV with this MAC, wherever DHCP put it — or None."""
    wanted = normalize_mac(mac)
    if wanted is None:
        return None
    for tv in discover_fn(prefix):
        if tv.mac == wanted:
            return tv
    return None
