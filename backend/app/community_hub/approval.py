from __future__ import annotations

from collections.abc import Mapping


class HubConfigurationError(RuntimeError):
    pass


def require_community_approval(environ: Mapping[str, str]) -> str:
    if environ.get("WXA_COMMUNITY_APPROVAL_ACK") != "YES":
        raise HubConfigurationError(
            "WXA_COMMUNITY_APPROVAL_ACK=YES est requis pour utiliser le hub."
        )
    reference = environ.get("WXA_COMMUNITY_APPROVAL_REFERENCE", "").strip()
    if not reference:
        raise HubConfigurationError(
            "WXA_COMMUNITY_APPROVAL_REFERENCE doit identifier l'accord Winamax obtenu."
        )
    return reference
