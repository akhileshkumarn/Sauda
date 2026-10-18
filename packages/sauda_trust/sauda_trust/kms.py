"""Cloud KMS signer (EC_SIGN_P256_SHA256 over a SHA-256 digest) plus a local in-memory signer for tests.

The active signer is injectable: set_signer(LocalSigner()) in tests; get_signer() defaults to KmsSigner().
"""
from __future__ import annotations

import base64
import threading
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from . import settings


class Signer(Protocol):
    def sign(self, digest: bytes) -> bytes: ...
    def public_key_pem(self) -> str: ...
    def key_version(self) -> str: ...


def verify_digest(digest: bytes, signature: bytes, public_key_pem: str) -> bool:
    """Verify a DER ECDSA P-256 signature over a precomputed SHA-256 digest."""
    try:
        pub = serialization.load_pem_public_key(public_key_pem.encode())
        pub.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class KmsSigner:
    def __init__(self, key_name: str | None = None, version: str | None = None, client=None):
        s = settings.get_settings()
        self._key_name = key_name or s.kms_key_name
        self._version = str(version or s.kms_key_version)
        self._client = client
        self._pem: str | None = None

    @property
    def version_name(self) -> str:
        return f"{self._key_name}/cryptoKeyVersions/{self._version}"

    def _c(self):
        return self._client or settings.kms_client()

    def sign(self, digest: bytes) -> bytes:
        if len(digest) != 32:
            raise ValueError("digest must be 32 bytes (SHA-256)")
        resp = self._c().asymmetric_sign(
            request={"name": self.version_name, "digest": {"sha256": digest}}, timeout=10
        )
        return bytes(resp.signature)  # KMS errors propagate: signing aborts (fail closed)

    def public_key_pem(self) -> str:
        if self._pem is None:
            self._pem = self._c().get_public_key(request={"name": self.version_name}, timeout=10).pem
        return self._pem

    def key_version(self) -> str:
        return self._version

    def verify(self, digest: bytes, signature: bytes) -> bool:
        return verify_digest(digest, signature, self.public_key_pem())


class LocalSigner:
    """In-memory P-256 key; same interface as KmsSigner. For unit tests / offline dev only."""

    def __init__(self, version: str = "local-1"):
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._version = version
        self._pem = (
            self._key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

    def sign(self, digest: bytes) -> bytes:
        return self._key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))

    def public_key_pem(self) -> str:
        return self._pem

    def key_version(self) -> str:
        return self._version

    def verify(self, digest: bytes, signature: bytes) -> bool:
        return verify_digest(digest, signature, self._pem)


_lock = threading.Lock()
_signer: Signer | None = None


def get_signer() -> Signer:
    global _signer
    if _signer is None:
        with _lock:
            if _signer is None:
                _signer = KmsSigner()
    return _signer


def set_signer(signer: Signer | None) -> None:
    global _signer
    with _lock:
        _signer = signer


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)
