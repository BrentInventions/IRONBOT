"""In-process dongle hub inside Recon. Not a cloud. Default off for Willie."""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_started = False
_mod: Any = None
_port = 8790


def _server_path() -> Path:
    return Path(__file__).resolve().parent.parent / "Impulse Pro" / "server" / "app.py"


def _load_mod() -> Any:
    global _mod
    if _mod is not None:
        return _mod
    path = _server_path()
    if not path.is_file():
        raise FileNotFoundError("Impulse Pro hub files missing")
    data = Path(__file__).resolve().parent / "data" / "dongle_host"
    data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("IMPULSE_PRO_DATA", str(data))
    os.environ.setdefault("IMPULSE_PRO_OPEN_BROWSER", "0")
    spec = importlib.util.spec_from_file_location("impulse_pro_hub", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load dongle hub")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod = mod
    return mod


def join_code() -> str:
    try:
        mod = _load_mod()
        return str(getattr(mod.STATE, "join_code", "") or "")
    except Exception:
        return ""


def hub_port() -> int:
    return int(_port)


def ensure_started(cfg: Any | None = None) -> bool:
    """Bind dongle HTTP on this PC. Never raises into Recon trading."""
    global _started, _port
    with _LOCK:
        if _started:
            return True
        try:
            mod = _load_mod()
            mod.STATE.load()
            raw_port = os.environ.get("IMPULSE_PRO_PORT", "8790").strip() or "8790"
            _port = int(raw_port)
            host = os.environ.get("IMPULSE_PRO_BIND", "0.0.0.0")
            httpd = mod.make_server(host, _port)
            _port = int(httpd.server_address[1])
            httpd.daemon_threads = True
            threading.Thread(target=httpd.serve_forever, daemon=True, name="recon-dongle-host").start()
            _started = True
            print(
                "Recon dongle host  http://127.0.0.1:%d  join %s  (no cloud — dongles connect to this bot)"
                % (_port, mod.STATE.join_code),
                flush=True,
            )
            return True
        except Exception as exc:
            print("Recon dongle host skipped: %s" % exc, flush=True)
            return False


def ingest(body: dict[str, Any]) -> bool:
    try:
        ensure_started()
        mod = _load_mod()
        with mod.STATE.lock:
            if not getattr(mod.STATE, "join_code", ""):
                mod.STATE.load()
            mod.STATE.publish(body)
        return True
    except Exception:
        return False
