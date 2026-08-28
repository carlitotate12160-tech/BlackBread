import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_256_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
MIN_ENCRYPTED_PAYLOAD_BYTES = AES_GCM_NONCE_BYTES + 1
SHA256_HEX_LENGTH = 64


class ArtifactIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    digest: str
    size: int
    path: Path


class EncryptedArtifactStore:
    def __init__(self, root: Path, encoded_key: str) -> None:
        self._root = root
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise ValueError("artifact key must be URL-safe base64") from error
        if len(key) != AES_256_KEY_BYTES:
            raise ValueError("artifact key must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def put(self, content: bytes) -> StoredArtifact:
        digest = hashlib.sha256(content).hexdigest()
        path = self._path_for(digest)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            nonce = os.urandom(AES_GCM_NONCE_BYTES)
            encrypted = nonce + self._cipher.encrypt(nonce, content, digest.encode("ascii"))
            temporary_path = path.with_suffix(".tmp")
            temporary_path.write_bytes(encrypted)
            temporary_path.chmod(0o600)
            temporary_path.replace(path)
        return StoredArtifact(digest=digest, size=len(content), path=path)

    def get(self, digest: str) -> bytes:
        self._validate_digest(digest)
        payload = self._path_for(digest).read_bytes()
        if len(payload) < MIN_ENCRYPTED_PAYLOAD_BYTES:
            raise ArtifactIntegrityError("encrypted artifact is truncated")
        nonce = payload[:AES_GCM_NONCE_BYTES]
        encrypted = payload[AES_GCM_NONCE_BYTES:]
        try:
            content = self._cipher.decrypt(nonce, encrypted, digest.encode("ascii"))
        except InvalidTag as error:
            raise ArtifactIntegrityError("artifact authentication failed") from error
        if hashlib.sha256(content).hexdigest() != digest:
            raise ArtifactIntegrityError("artifact digest does not match content")
        return content

    def _path_for(self, digest: str) -> Path:
        self._validate_digest(digest)
        return self._root / digest[:2] / digest[2:4] / f"{digest}.enc"

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if len(digest) != SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("artifact digest must be a lowercase SHA-256 hex value")
