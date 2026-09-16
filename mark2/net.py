"""Minimal JSON-line TCP client for ReconSniperBridge. Not brain.BridgeClient."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Callable, Optional

MessageHandler = Callable[[dict], None]


class Mark2Net:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 5564,
        on_message: Optional[MessageHandler] = None,
        on_connection: Optional[Callable[[bool], None]] = None,
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Recon Sniper only connects locally")
        self.host = host
        self.port = int(port)
        self.on_message = on_message
        self.on_connection = on_connection
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.connected = False

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, name="mark2-net", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def send(self, msg: dict) -> None:
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        with self._lock:
            if self._sock is None:
                return
            try:
                self._sock.sendall(data)
            except OSError:
                self._close()

    def send_order(
        self,
        action: str,
        *,
        quantity: int = 1,
        stop_loss: float | None = None,
        reason: str = "",
        take_profit: float | None = None,
    ) -> None:
        payload: dict = {
            "type": "order",
            "action": str(action).upper(),
            "quantity": int(quantity),
            "reason": reason,
        }
        if stop_loss is not None:
            payload["stop_loss"] = float(stop_loss)
        if take_profit is not None:
            payload["take_profit"] = float(take_profit)
        self.send(payload)

    def send_flat(self, reason: str = "") -> None:
        self.send({"type": "order", "action": "CLOSE", "reason": reason})

    def send_levels(
        self,
        *,
        side: str = "",
        entry: float = 0.0,
        stop: float = 0.0,
        target: float = 0.0,
        trail: float = 0.0,
        trail_active: bool = False,
        simulate: bool = True,
        clear: bool = False,
    ) -> None:
        if clear:
            self.send({"type": "levels", "clear": True})
            self.send({"type": "bracket_lines", "clear": True})
            return
        payload = {
            "type": "levels",
            "side": str(side),
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target),
            "trail": float(trail),
            "trail_active": bool(trail_active),
            "simulate": bool(simulate),
        }
        self.send(payload)
        self.send(
            {
                "type": "bracket_lines",
                "side": str(side),
                "entry": float(entry),
                "stop": float(stop),
                "target": float(target),
                "trail": float(trail),
                "trail_active": bool(trail_active),
                "preview": bool(simulate),
                "live": not bool(simulate),
                "clear": False,
            }
        )

    def send_ema_overlay(
        self,
        *,
        enabled: bool,
        ema9: float = 0.0,
        ema20: float = 0.0,
        ema50: float = 0.0,
    ) -> None:
        self.send(
            {
                "type": "ema_overlay",
                "enabled": bool(enabled),
                "ema9": float(ema9),
                "ema20": float(ema20),
                "ema50": float(ema50),
            }
        )

    def send_barrier_overlay(
        self,
        *,
        enabled: bool,
        pdh: float = 0.0,
        pdl: float = 0.0,
        next_long: float = 0.0,
        next_short: float = 0.0,
    ) -> None:
        self.send(
            {
                "type": "barriers",
                "enabled": bool(enabled),
                "pdh": float(pdh or 0),
                "pdl": float(pdl or 0),
                "next_long": float(next_long or 0),
                "next_short": float(next_short or 0),
            }
        )

    def send_tcm8_overlay(
        self,
        *,
        enabled: bool,
        ema1m: float = 0.0,
        ema1h: float = 0.0,
        ema4h: float = 0.0,
    ) -> None:
        self.send(
            {
                "type": "tcm8_overlay",
                "enabled": bool(enabled),
                "ema1m": float(ema1m or 0),
                "ema1h": float(ema1h or 0),
                "ema4h": float(ema4h or 0),
            }
        )

    def send_stop(self, stop: float, reason: str = "trail") -> None:
        if float(stop) <= 0:
            return
        self.send({"type": "set_stop", "stop": float(stop), "reason": reason})

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=3.0)
                sock.settimeout(1.0)
                with self._lock:
                    self._sock = sock
                self.connected = True
                self._notify_connection(True)
                self._read(sock)
            except OSError:
                pass
            finally:
                was = self.connected
                self._close()
                if was:
                    self._notify_connection(False)
            self._stop.wait(1.0)

    def _notify_connection(self, ok: bool) -> None:
        cb = self.on_connection
        if cb is None:
            return
        try:
            cb(ok)
        except Exception:
            pass

    def _read(self, sock: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if self.on_message:
                    try:
                        self.on_message(msg)
                    except Exception:
                        continue

    def _close(self) -> None:
        self.connected = False
        with self._lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        time.sleep(0)
