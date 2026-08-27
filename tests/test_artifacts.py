import base64
from pathlib import Path

import pytest

from blackbread.artifacts import ArtifactIntegrityError, EncryptedArtifactStore


def encoded_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


def test_artifact_round_trip_is_content_addressed_and_encrypted(tmp_path: Path) -> None:
    content = b"evidence that must not be stored in plaintext"
    store = EncryptedArtifactStore(tmp_path, encoded_key())

    artifact = store.put(content)

    assert artifact.digest == "9ccf9d19f08057058e4809b909b5f3f346e8ec78b72e698ba9d2a0ee50ae9a33"
    assert artifact.size == len(content)
    assert artifact.path.read_bytes() != content
    assert store.get(artifact.digest) == content


def test_put_deduplicates_identical_content(tmp_path: Path) -> None:
    store = EncryptedArtifactStore(tmp_path, encoded_key())

    first = store.put(b"same evidence")
    second = store.put(b"same evidence")

    assert first == second


def test_tampered_artifact_is_rejected(tmp_path: Path) -> None:
    store = EncryptedArtifactStore(tmp_path, encoded_key())
    artifact = store.put(b"original evidence")
    payload = bytearray(artifact.path.read_bytes())
    payload[-1] ^= 1
    artifact.path.write_bytes(payload)

    with pytest.raises(ArtifactIntegrityError, match="authentication failed"):
        store.get(artifact.digest)


@pytest.mark.parametrize("key", ["not-base64", base64.urlsafe_b64encode(b"short").decode()])
def test_invalid_encryption_key_is_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="artifact key"):
        EncryptedArtifactStore(tmp_path, key)


def test_invalid_digest_is_rejected(tmp_path: Path) -> None:
    store = EncryptedArtifactStore(tmp_path, encoded_key())

    with pytest.raises(ValueError, match="SHA-256"):
        store.get("../escape")
