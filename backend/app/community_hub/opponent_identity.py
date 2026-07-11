from __future__ import annotations

import hashlib
import hmac
import os
import unicodedata
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class OpponentIdentityError(ValueError):
    """A deliberately generic identity validation or decryption failure."""


@dataclass(frozen=True, slots=True)
class EncryptedOpponentName:
    identity_key: str
    ciphertext: bytes
    nonce: bytes
    key_version: int


def normalize_opponent_name(value: str) -> tuple[str, str]:
    """Return display and identity forms without fuzzy or homoglyph matching."""
    display = unicodedata.normalize("NFKC", value).strip()
    if not display or len(display) > 200:
        raise OpponentIdentityError("Pseudo adverse invalide.")
    if any(
        not character.isprintable()
        or unicodedata.category(character).startswith("C")
        for character in display
    ):
        raise OpponentIdentityError("Pseudo adverse invalide.")
    return display, display.casefold()


class OpponentIdentityService:
    """Deterministic identity plus authenticated encryption for display names."""

    def __init__(
        self,
        *,
        identity_key: bytes,
        encryption_key: bytes,
        key_version: int = 1,
    ) -> None:
        if len(identity_key) != 32 or len(encryption_key) != 32 or key_version <= 0:
            raise OpponentIdentityError("Configuration du suivi adverse invalide.")
        self._identity_key = identity_key
        self._cipher = AESGCM(encryption_key)
        self.key_version = key_version

    def identity_for(self, value: str) -> tuple[str, str]:
        display, normalized = normalize_opponent_name(value)
        identity = hmac.new(
            self._identity_key,
            normalized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return display, identity

    @staticmethod
    def _aad(identity_key: str, key_version: int) -> bytes:
        return f"wxa-opponent:{identity_key}:v{key_version}".encode("ascii")

    def encrypt(self, value: str) -> EncryptedOpponentName:
        display, identity = self.identity_for(value)
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            display.encode("utf-8"),
            self._aad(identity, self.key_version),
        )
        return EncryptedOpponentName(
            identity_key=identity,
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self.key_version,
        )

    def decrypt(
        self,
        *,
        identity_key: str,
        ciphertext: bytes,
        nonce: bytes,
        key_version: int,
    ) -> str:
        if key_version != self.key_version:
            raise OpponentIdentityError("Version de cle adverse indisponible.")
        try:
            plaintext = self._cipher.decrypt(
                nonce,
                ciphertext,
                self._aad(identity_key, key_version),
            )
            display = plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise OpponentIdentityError("Pseudo adverse indechiffrable.") from exc
        normalized_display, verified_identity = self.identity_for(display)
        if not hmac.compare_digest(identity_key, verified_identity):
            raise OpponentIdentityError("Pseudo adverse indechiffrable.")
        return normalized_display
