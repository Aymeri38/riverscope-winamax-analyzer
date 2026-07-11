from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.api import AnalyzerSettings


HAND_TIME_RE = re.compile(r"- (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) UTC", re.IGNORECASE)


def detect_active_tournaments(settings: AnalyzerSettings, now: datetime | None = None) -> dict[str, Any]:
    """Conservative, file-only activity detection.

    This second-layer file guard never inspects process memory, windows,
    network traffic or screen contents. The independent process-name interlock
    is implemented in ``app.core.process_guard``.
    """
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reasons: list[dict[str, str]] = []
    checked = 0

    for configured in settings.history_paths:
        root = Path(configured)
        if not root.is_dir():
            continue
        for hand_path in root.glob("*Expresso*.txt"):
            if hand_path.name.endswith("_summary.txt"):
                continue
            checked += 1
            try:
                stat = hand_path.stat()
            except OSError:
                reasons.append({"file": hand_path.name, "reason": "fichier momentanément inaccessible"})
                continue
            age = reference.timestamp() - stat.st_mtime
            if age < settings.active_grace_seconds:
                reasons.append({"file": hand_path.name, "reason": "fichier récemment modifié"})
                continue

            summary_path = hand_path.with_name(f"{hand_path.stem}_summary.txt")
            if not summary_path.is_file():
                reasons.append({"file": hand_path.name, "reason": "résumé final absent"})
                continue
            try:
                summary_text = _read_text(summary_path)
            except OSError:
                reasons.append({"file": hand_path.name, "reason": "résumé momentanément inaccessible"})
                continue
            if "You finished in" not in summary_text:
                reasons.append({"file": hand_path.name, "reason": "classement final absent"})
                continue

            try:
                hand_text = _read_text(hand_path)
            except OSError:
                reasons.append({"file": hand_path.name, "reason": "historique momentanément inaccessible"})
                continue
            timestamps = HAND_TIME_RE.findall(hand_text)
            if timestamps:
                last_hand = datetime.strptime(timestamps[-1], "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if (reference - last_hand).total_seconds() < settings.active_grace_seconds:
                    reasons.append({"file": hand_path.name, "reason": "dernière main trop récente"})

    return {
        "active": bool(reasons),
        "potentially_active": bool(reasons),
        "checked_tournaments": checked,
        "reason_count": len(reasons),
        "reasons": reasons[:20],
        "policy": "Dans le doute, l’import, l’analyse et le replayer attendent.",
    }


def _read_text(path: Path) -> str:
    payload = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")
