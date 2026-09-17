"""Outgoing HTTP(S) connections to LocalSend apps (register, messages)."""

from __future__ import annotations

import http.client
import ssl

from the_frame_v2.localsend.identity import Identity


def connect(
    identity: Identity, host: str, port: int, protocol: str, timeout: float
) -> http.client.HTTPConnection:
    """Connection presenting our certificate as client certificate (apps check it matches the
    announced fingerprint). Peers are self-signed and not verified: they pin us, not we them."""
    if protocol != "https":
        return http.client.HTTPConnection(host, port, timeout=timeout)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(identity.cert_path, identity.key_path)
    return http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
