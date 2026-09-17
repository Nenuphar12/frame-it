"""TLS identity: a persistent self-signed certificate whose SHA-256 is the LocalSend fingerprint.

LocalSend clients pin the receiver certificate to the fingerprint learned during discovery
(uppercase hex SHA-256 of the DER certificate), so the certificate must never change silently.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True, slots=True)
class Identity:
    cert_path: Path
    key_path: Path
    fingerprint: str


def fingerprint_of(cert_pem: bytes) -> str:
    der = x509.load_pem_x509_certificate(cert_pem).public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest().upper()


def ensure_identity(directory: Path) -> Identity:
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    if not (cert_path.is_file() and key_path.is_file()):
        directory.mkdir(parents=True, exist_ok=True)
        cert_pem, key_pem = _generate()
        key_path.touch(mode=0o600)
        key_path.write_bytes(key_pem)
        cert_path.write_bytes(cert_pem)
    return Identity(cert_path, key_path, fingerprint_of(cert_path.read_bytes()))


def _generate() -> tuple[bytes, bytes]:
    # RSA-2048 and a long validity, like the certificates LocalSend apps generate.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "the_frame_v2")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365 * 100))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem
