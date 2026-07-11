from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import uvicorn

from app.community_hub.config import DEFAULT_HUB_PORT, HubConfig, get_hub_config
from app.community_hub.database import HubDatabase
from app.community_hub.approval import HubConfigurationError, require_community_approval
from app.core.process_guard import (
    SAFETY_EXIT_CODE,
    AnalysisForbiddenError,
    AnalysisInterlock,
    ProcessGuardMonitor,
    ProcessProbe,
    require_winamax_absent,
)


logger = logging.getLogger("winamax_analyzer.community_hub")


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_tls_binding(
    host: str,
    certfile: str | None,
    keyfile: str | None,
) -> tuple[str | None, str | None]:
    cert = certfile.strip() if certfile else None
    key = keyfile.strip() if keyfile else None
    if bool(cert) != bool(key):
        raise HubConfigurationError("Le certificat et la cle TLS doivent etre fournis ensemble.")
    if not is_loopback_host(host) and not (cert and key):
        raise HubConfigurationError(
            "Une ecoute hors loopback exige TLS avec --ssl-certfile et --ssl-keyfile."
        )
    for label, value in (("certificat TLS", cert), ("cle TLS", key)):
        if value and not Path(value).expanduser().is_file():
            raise HubConfigurationError(f"{label.capitalize()} introuvable.")
    return cert, key


def _arguments(
    argv: Sequence[str] | None,
    config: HubConfig,
    environ: Mapping[str, str],
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Community hub auto-heberge et protege")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port or DEFAULT_HUB_PORT)
    parser.add_argument("--ssl-certfile", default=environ.get("WXA_HUB_TLS_CERT"))
    parser.add_argument("--ssl-keyfile", default=environ.get("WXA_HUB_TLS_KEY"))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port doit etre compris entre 1 et 65535")
    return args


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    detector: ProcessProbe | None = None,
    database_factory: Callable[[Path], HubDatabase] = HubDatabase,
    server_factory: Callable[[uvicorn.Config], uvicorn.Server] = uvicorn.Server,
) -> int:
    env = environ if environ is not None else os.environ
    interlock = AnalysisInterlock()
    try:
        require_winamax_absent(detector=detector, interlock=interlock)
    except AnalysisForbiddenError as exc:
        print(str(exc), file=sys.stderr)
        print("Hub non demarre; aucune relance automatique.", file=sys.stderr)
        return SAFETY_EXIT_CODE

    try:
        config = get_hub_config(dict(env))
        args = _arguments(argv, config, env)
        require_community_approval(env)
        certfile, keyfile = validate_tls_binding(
            args.host, args.ssl_certfile, args.ssl_keyfile
        )
    except (HubConfigurationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        require_winamax_absent(detector=detector, interlock=interlock)
    except AnalysisForbiddenError as exc:
        print(str(exc), file=sys.stderr)
        return SAFETY_EXIT_CODE

    database = database_factory(config.database_path)
    try:
        database.initialize()
        try:
            require_winamax_absent(detector=detector, interlock=interlock)
        except AnalysisForbiddenError as exc:
            print(str(exc), file=sys.stderr)
            return SAFETY_EXIT_CODE
        from app.community_hub.api import create_hub_app

        app = create_hub_app(
            database,
            docs_enabled=config.docs_enabled,
            trusted_hosts=config.trusted_hosts,
            interlock=interlock,
            hub_config=config,
        )
        server = server_factory(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                reload=False,
                workers=1,
                log_level="info",
                access_log=False,
                ssl_certfile=certfile,
                ssl_keyfile=keyfile,
            )
        )

        def stop_server(reason: str) -> None:
            server.should_exit = True
            logger.critical("%s Hub en cours d'arret; aucune relance.", reason)

        monitor = ProcessGuardMonitor(
            on_trip=stop_server,
            detector=detector,
            interlock=interlock,
        )
        try:
            monitor.start()
            server.run()
        except AnalysisForbiddenError as exc:
            logger.critical("Demarrage du hub refuse par le verrou: %s", exc)
        finally:
            monitor.stop()
        return SAFETY_EXIT_CODE if interlock.blocked else 0
    finally:
        database.dispose()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
