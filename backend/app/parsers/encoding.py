from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias


ParserSource: TypeAlias = str | bytes | bytearray | Path | os.PathLike[str]


@dataclass(slots=True, frozen=True)
class LoadedText:
    text: str
    encoding: str
    source_hash: str
    path: Path | None = None


def load_text(source: ParserSource) -> LoadedText:
    """Load parser input without ever mutating the source file.

    A string containing a newline or a Winamax header is treated as text.  Other
    strings are treated as paths only when that path exists.
    """

    path: Path | None = None
    if isinstance(source, Path) or isinstance(source, os.PathLike):
        path = Path(source)
        data = path.read_bytes()
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    elif isinstance(source, str):
        looks_like_text = "\n" in source or "\r" in source or source.lstrip("\ufeff").startswith("Winamax Poker")
        if not looks_like_text:
            candidate = Path(source)
            try:
                if candidate.exists() and candidate.is_file():
                    path = candidate
                    data = candidate.read_bytes()
                else:
                    data = source.encode("utf-8")
            except (OSError, ValueError):
                data = source.encode("utf-8")
        else:
            data = source.encode("utf-8")
    else:
        raise TypeError(f"Unsupported parser input: {type(source)!r}")

    text, encoding = decode_bytes(data)
    return LoadedText(
        text=text.replace("\r\n", "\n").replace("\r", "\n"),
        encoding=encoding if not isinstance(source, str) or path else "unicode",
        source_hash=hashlib.sha256(data).hexdigest(),
        path=path,
    )


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode Winamax files in UTF-8 (with/without BOM) or Windows-1252."""

    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig"), "utf-8-sig"
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"
