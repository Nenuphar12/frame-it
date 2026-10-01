"""Finding TVs on the LAN (`tv/discovery.py`): parsing, the subnet to sweep, merging the searches."""

from __future__ import annotations

from the_frame_v2.tv import normalize_mac
from the_frame_v2.tv.discovery import (
    DiscoveredTv,
    discover,
    find_by_mac,
    normalize_prefix,
    parse_device,
    parse_ssdp_response,
    subnet_prefix,
)

#: The REST answer of the user's Frame, as `tv_probe.py --scan` printed it (2026-09-25).
FRAME_PAYLOAD = {
    "device": {
        "FrameTVSupport": "true",
        "TokenAuthSupport": "true",
        "PowerState": "standby",
        "model": "25_PTM_FTV",
        "modelName": "TQ55LS03FAUXXC",
        "name": '55" The Frame',
        "type": "Samsung SmartTV",
        "wifiMac": "04:CB:88:1A:2B:3C",
    },
    "name": '55" The Frame',
    "type": "Samsung SmartTV",
}


def test_parse_device_reads_a_frame() -> None:
    tv = parse_device("192.168.1.71", FRAME_PAYLOAD)
    assert tv == DiscoveredTv(
        host="192.168.1.71",
        name='55" The Frame',
        model="TQ55LS03FAUXXC",
        model_code="25_PTM_FTV",
        frame_support=True,
        token_auth=True,
        mac="04:cb:88:1a:2b:3c",
        power_state="standby",
    )


def test_parse_device_ignores_what_is_not_a_samsung_tv() -> None:
    assert parse_device("192.168.1.2", {"device": {"type": "Router"}}) is None
    assert parse_device("192.168.1.2", {"status": "ok"}) is None
    # A Samsung TV that is not a Frame is still a TV: listed, just not recommended.
    plain = parse_device("192.168.1.3", {"device": {"type": "Samsung SmartTV", "name": "Kitchen"}})
    assert plain is not None and plain.frame_support is False


def test_normalize_mac() -> None:
    assert normalize_mac("04:CB:88:1A:2B:3C") == "04:cb:88:1a:2b:3c"
    assert normalize_mac("04-cb-88-1a-2b-3c") == "04:cb:88:1a:2b:3c"
    assert normalize_mac("04cb881a2b3c") == "04:cb:88:1a:2b:3c"
    assert normalize_mac("") is None
    assert normalize_mac(None) is None
    assert normalize_mac("04:cb:88") is None


def test_parse_ssdp_response_takes_the_location_host() -> None:
    answer = (
        b"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\n"
        b"LOCATION: http://192.168.1.71:7676/smp_15_\r\n"
        b"ST: urn:samsung.com:device:RemoteControlReceiver:1\r\n\r\n"
    )
    assert parse_ssdp_response(answer) == "192.168.1.71"
    assert parse_ssdp_response(b"HTTP/1.1 200 OK\r\n\r\n") is None


def test_subnet_prefix_prefers_the_setting_then_the_public_url() -> None:
    # Docker: this process sits on the bridge network; the public URL carries the LAN's address.
    assert (
        subnet_prefix(configured=None, public_url="http://192.168.1.179:8765", lan_ip="172.17.0.2")
        == "192.168.1"
    )
    assert (
        subnet_prefix(configured="10.0.4.0/24", public_url=None, lan_ip="192.168.1.5") == "10.0.4"
    )
    # A host name in the public URL says nothing about the subnet: fall back to this host's.
    assert subnet_prefix(configured=None, public_url="http://frame.lan", lan_ip="192.168.0.12") == (
        "192.168.0"
    )
    # Never a public or loopback address.
    assert subnet_prefix(configured=None, public_url="http://8.8.8.8", lan_ip="127.0.0.1") is None


def test_normalize_prefix() -> None:
    assert normalize_prefix("192.168.1") == "192.168.1"
    assert normalize_prefix("192.168.1.") == "192.168.1"
    assert normalize_prefix("192.168.1.42") == "192.168.1"
    assert normalize_prefix("192.168.001.0/24") == "192.168.1"
    assert normalize_prefix("192.168") is None
    assert normalize_prefix("300.1.1") is None


def test_discover_merges_the_sweep_and_ssdp_frames_first() -> None:
    answers = {
        "10.0.0.5": DiscoveredTv(host="10.0.0.5", name="Kitchen", frame_support=False),
        "10.0.0.71": DiscoveredTv(host="10.0.0.71", name="Frame", frame_support=True),
        # Only SSDP knows this one (another subnet, say).
        "10.0.9.9": DiscoveredTv(host="10.0.9.9", name="Bedroom Frame", frame_support=True),
    }
    asked: list[str] = []

    def fetch(host: str, _timeout: float) -> DiscoveredTv | None:
        asked.append(host)
        return answers.get(host)

    found = discover("10.0.0", fetch=fetch, ssdp=lambda _t: {"10.0.0.71", "10.0.9.9"})
    assert [tv.host for tv in found] == ["10.0.0.71", "10.0.9.9", "10.0.0.5"]
    # The /24 is swept once, and an SSDP host already swept is not asked twice.
    assert asked.count("10.0.0.71") == 1
    assert len([h for h in asked if h.startswith("10.0.0.")]) == 254


def test_discover_without_a_subnet_is_ssdp_only() -> None:
    found = discover(
        None,
        fetch=lambda host, _t: DiscoveredTv(host=host, frame_support=True),
        ssdp=lambda _t: {"10.1.1.1"},
    )
    assert [tv.host for tv in found] == ["10.1.1.1"]


def test_find_by_mac() -> None:
    tvs = [
        DiscoveredTv(host="10.0.0.5", mac="aa:aa:aa:aa:aa:aa"),
        DiscoveredTv(host="10.0.0.80", mac="04:cb:88:1a:2b:3c"),
    ]
    assert find_by_mac(lambda _p: tvs, "10.0.0", "04-CB-88-1A-2B-3C") == tvs[1]
    assert find_by_mac(lambda _p: tvs, "10.0.0", "00:00:00:00:00:01") is None
    assert find_by_mac(lambda _p: tvs, "10.0.0", None) is None
