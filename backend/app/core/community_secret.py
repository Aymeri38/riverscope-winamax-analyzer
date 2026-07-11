from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import config


class CommunitySecretError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommunitySecrets:
    access_token: str
    client_secret: bytes


class CommunitySecretStore(Protocol):
    def load(self) -> CommunitySecrets | None: ...
    def save(self, value: CommunitySecrets) -> None: ...
    def delete(self) -> None: ...


class DpapiCommunitySecretStore:
    """Encrypt community credentials for the current Windows user with DPAPI."""

    _DESCRIPTION = "Winamax Analyzer community credentials"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.data_dir / "secrets" / "community.dpapi")

    @staticmethod
    def _crypt(data: bytes, *, protect: bool) -> bytes:
        if os.name != "nt":
            raise CommunitySecretError("Le stockage DPAPI est disponible uniquement sous Windows.")

        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        buffer = ctypes.create_string_buffer(data)
        source = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        destination = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
        if protect:
            ok = crypt32.CryptProtectData(
                ctypes.byref(source),
                DpapiCommunitySecretStore._DESCRIPTION,
                None,
                None,
                None,
                flags,
                ctypes.byref(destination),
            )
        else:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(source), None, None, None, None, flags, ctypes.byref(destination)
            )
        if not ok:
            raise CommunitySecretError("DPAPI n'a pas pu traiter les identifiants communautaires.")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            kernel32.LocalFree(destination.pbData)

    def load(self) -> CommunitySecrets | None:
        if not self.path.is_file():
            return None
        try:
            decoded = json.loads(self._crypt(self.path.read_bytes(), protect=False).decode("utf-8"))
            return CommunitySecrets(
                access_token=str(decoded["access_token"]),
                client_secret=bytes.fromhex(str(decoded["client_secret"])),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CommunitySecretError("Identifiants communautaires locaux illisibles.") from exc

    def save(self, value: CommunitySecrets) -> None:
        payload = json.dumps(
            {
                "access_token": value.access_token,
                "client_secret": value.client_secret.hex(),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._crypt(payload, protect=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise CommunitySecretError("Impossible de supprimer les identifiants communautaires.") from exc


class MemoryCommunitySecretStore:
    """Explicit test store; production never selects it from an environment flag."""

    def __init__(self) -> None:
        self.value: CommunitySecrets | None = None

    def load(self) -> CommunitySecrets | None:
        return self.value

    def save(self, value: CommunitySecrets) -> None:
        self.value = value

    def delete(self) -> None:
        self.value = None
