"""Recon Sniper Night Shell — pywebview HUD over the standalone engine."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from mark2.config import Mark2Config, load_config, SETTINGS_PATH, local_app_settings_path
from mark2.product import apply_product, product_key
from mark2.licensing.paths import frontend_dir
from mark2.logger import local_app_log_path
from mark2.runtime import Mark2Runtime

FRONTEND = frontend_dir()


def _hud_log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    try:
        path = local_app_log_path("hud_runtime.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line, end="", flush=True)


def _for_bridge(value):
    """pythonnet/WebView2 dies on NaN, inf, and odd CLR types (c0000005)."""
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, allow_nan=False, default=str))
    except (TypeError, ValueError) as exc:
        _hud_log(f"bridge marshal failed: {exc}")
        return {}


def _safe_api(fn):
    """Keep Python exceptions off the pywebview .NET bridge (c0000005)."""

    def wrap(*args, **kwargs):
        try:
            return _for_bridge(fn(*args, **kwargs))
        except Exception as exc:
            _hud_log(f"api {fn.__name__} failed: {exc}")
            return None

    return wrap


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def log_message(self, format, *args):  # noqa: A003
        return


class Mark2Api:
    def __init__(self, runtime: Mark2Runtime) -> None:
        self.rt = runtime

    @_safe_api
    def snapshot(self) -> dict:
        return self.rt.engine.hud_snapshot()

    @_safe_api
    def set_mode(self, mode: str) -> str:
        return self.rt.engine.set_mode(str(mode or "LIVE"))

    @_safe_api
    def set_enabled(self, on: bool) -> bool:
        ok = self.rt.engine.set_enabled(bool(on))
        _hud_log(f"api set_enabled {on} -> {ok}")
        return ok

    @_safe_api
    def arm(self) -> dict:
        ok = self.rt.engine.set_enabled(True)
        _hud_log(f"api arm -> {ok}")
        return {"ok": bool(ok), "enabled": bool(self.rt.engine.cfg.MARK2_ENABLED)}

    @_safe_api
    def disarm(self) -> dict:
        ok = self.rt.engine.set_enabled(False)
        _hud_log(f"api disarm -> {ok}")
        return {"ok": True, "enabled": False}

    @_safe_api
    def set_contracts(self, n) -> int:
        return self.rt.engine.set_contracts(n)

    @_safe_api
    def set_daily_goal(self, dollars) -> dict:
        return self.rt.engine.set_daily_goal(dollars)

    @_safe_api
    def set_goal_enabled(self, on) -> dict:
        return self.rt.engine.set_goal_enabled(bool(on))

    @_safe_api
    def set_goal_window_hours(self, hours) -> dict:
        return self.rt.engine.set_goal_window_hours(hours)

    @_safe_api
    def set_stop_points(self, pts) -> float:
        return self.rt.engine.set_stop_points(pts)

    @_safe_api
    def set_entry_strictness(self, value) -> dict:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 50.0
        return self.rt.engine.set_entry_strictness(v)

    @_safe_api
    def set_entry_gate(self, name: str, value) -> dict:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        return self.rt.engine.set_entry_gate(str(name or ""), v)

    @_safe_api
    def set_entry_toggles(self, toggles: dict) -> dict:
        return self.rt.engine.set_entry_toggles(dict(toggles or {}))

    @_safe_api
    def reset_entry_tuning(self) -> dict:
        return self.rt.engine.reset_entry_tuning()

    @_safe_api
    def set_strategy(self, payload: dict) -> dict:
        data = payload
        if isinstance(data, str):
            import json
            data = json.loads(data)
        return self.rt.engine.set_strategy(dict(data or {}))

    @_safe_api
    def flatten(self) -> str:
        self.rt.engine.flatten_now("HUD_FLAT")
        return "FLAT"

    @_safe_api
    def exit_trade(self) -> str:
        return self.flatten()

    @_safe_api
    def buy(self) -> dict:
        return self.rt.engine.manual_order("BUY")

    @_safe_api
    def sell(self) -> dict:
        return self.rt.engine.manual_order("SELL")

    @_safe_api
    def short(self) -> dict:
        return self.rt.engine.manual_order("SHORT")

    @_safe_api
    def clear_session(self) -> dict:
        return self.rt.engine.clear_session()

    @_safe_api
    def reset_pnl(self) -> dict:
        """HUD alias — zero session PnL / ledger / goal lock."""
        return self.clear_session()


def _serve() -> tuple[str, ThreadingHTTPServer]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/index.html", httpd


def run_hud(
    *,
    headless: bool = False,
    cfg: Mark2Config | None = None,
    persist_path=None,
    title: str | None = None,
    on_ready=None,
) -> int:
    persist = persist_path
    if persist is None and product_key() == "TIANTE":
        persist = local_app_settings_path()
    persist = persist or SETTINGS_PATH
    cfg = cfg or load_config(persist)
    apply_product(cfg)
    rt = Mark2Runtime(cfg, persist_path=persist)
    rt.start()
    try:
        from mark2.dongle_host import ensure_started
        from mark2.impulse_lead import leader_enabled

        if leader_enabled(cfg):
            if ensure_started(cfg):
                import webbrowser

                from mark2 import dongle_host

                site = "http://127.0.0.1:%d" % int(dongle_host.hub_port())
                threading.Timer(2.5, lambda: webbrowser.open(site)).start()
    except Exception:
        pass
    window_title = str(title or cfg.PRODUCT_NAME or "RECON SNIPER")
    if not title and product_key() == "RECON":
        window_title = "IRONBOT"
    if headless:
        print(
            f"{window_title} headless · mode={cfg.mode().value} · port={cfg.BRIDGE_PORT}",
            flush=True,
        )
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            rt.stop()
        return 0

    url, httpd = _serve()
    try:
        import webview
    except Exception as exc:
        print(f"pywebview missing ({exc}). HUD at {url}", flush=True)
        print("Install: py -3 -m pip install pywebview", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        rt.stop()
        httpd.shutdown()
        return 1

    api = Mark2Api(rt)
    webview_data = local_app_log_path("hud_runtime.log").parent.parent / "WebView2-ctrl"
    try:
        webview_data.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(webview_data))
    except OSError:
        pass
    os.environ.setdefault(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--autoplay-policy=no-user-gesture-required "
        "--disable-features=CalculateNativeWinOcclusion",
    )
    tiante_hud = product_key() == "TIANTE"
    win_kw = dict(
        js_api=api,
        width=1680,
        height=980,
        background_color="#121214" if tiante_hud else "#080100",
        text_select=False,
        easy_drag=False,
        confirm_close=False,
        transparent=False,
    )
    icon_path = ROOT / "assets" / "icons" / "iron-bot.ico"
    if not tiante_hud and icon_path.is_file():
        win_kw["icon"] = str(icon_path)
    try:
        window = webview.create_window(window_title, url, **win_kw)
    except TypeError:
        win_kw.pop("transparent", None)
        win_kw.pop("easy_drag", None)
        try:
            window = webview.create_window(window_title, url, **win_kw)
        except TypeError:
            win_kw.pop("icon", None)
            window = webview.create_window(window_title, url, **win_kw)
    gui = "edgechromium" if sys.platform == "win32" else None

    def _max() -> None:
        time.sleep(1.0)
        try:
            window.maximize()
        except Exception as exc:
            _hud_log(f"maximize failed: {exc}")
        try:
            window.evaluate_js(
                "document.querySelectorAll('canvas').forEach(function(c){"
                "c.style.pointerEvents='none';c.style.display='none';});"
                "['btn-enable','btn-enable-hero'].forEach(function(id){"
                "var el=document.getElementById(id);if(!el)return;"
                "el.onpointerdown=function(e){"
                "if(e){e.preventDefault();e.stopPropagation();}"
                "if(window.reconArm)window.reconArm(e);"
                "else if(window.pywebview&&window.pywebview.api&&window.pywebview.api.arm)"
                "window.pywebview.api.arm();"
                "return false;};"
                "});"
            )
        except Exception as exc:
            _hud_log(f"canvas click-through failed: {exc}")
        if on_ready:
            try:
                on_ready()
            except Exception as exc:
                _hud_log(f"on_ready failed: {exc}")

    _hud_log(f"{window_title} start url={url} port={cfg.BRIDGE_PORT}")
    try:
        try:
            webview.start(func=_max, gui=gui, debug=False, http_server=False)
        except TypeError:
            webview.start(func=_max, gui=gui, debug=False)
        _hud_log(f"{window_title} webview.start returned (window closed)")
    except Exception as exc:
        _hud_log(f"{window_title} webview crashed: {exc}")
    finally:
        rt.stop()
        try:
            httpd.shutdown()
        except Exception:
            pass
    return 0


def main() -> int:
    _hud_log("main() entered")
    headless = "--headless" in sys.argv or os.environ.get("MARK2_NO_WINDOW") == "1"
    try:
        return run_hud(headless=headless)
    except Exception as exc:
        _hud_log(f"HUD failed to open: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
