"""External 8TCM board. Iron Man red HUD with rolling BRENTS TRADING BOT."""

from __future__ import annotations

import os
import sys
import time

from .tcm8_font import FONT_FAMILY, IRON_BG, IRON_GOLD, IRON_RED, IRON_RED_DIM, register_ironman_font
from .tcm8_status import (
    STEPS,
    STEP_TARGET,
    format_tcm8_cmd_tables,
    read_tcm8_ledger,
    read_tcm8_status,
    tcm8_status_path,
)

MARQUEE = "BRENTS TRADING BOT"
RED = "\033[38;2;225;6;0m"
GOLD = "\033[38;2;255;179;71m"
DIM = "\033[38;2;122;12;16m"
RESET = "\033[0m"


def _enable_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        return


def _cls() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def marquee_slice(text: str, offset: int, width: int = 42) -> str:
    pad = "    •    "
    loop = (text.strip() + pad) * 8
    n = len(loop)
    if n <= 0:
        return text
    i = int(offset) % n
    doubled = loop + loop
    return doubled[i : i + max(8, int(width))]


def _mark(i: int, current: int, blocked: bool) -> str:
    if i < current:
        return "[x]"
    if i == current:
        return "[!]" if blocked else "[>]"
    return "[ ]"


def _with_ledger(board: dict) -> dict:
    """Blotter always comes from the live ledger, never from a stale status file."""
    data = read_tcm8_ledger()
    out = dict(board or {})
    out["session"] = data.get("session") or {}
    out["trades"] = list(data.get("trades") or [])
    out["date"] = data.get("date") or out.get("date") or ""
    if not out.get("open_trade"):
        out["open_trade"] = data.get("open")
    return out


def render(board: dict, *, offset: int = 0) -> str:
    lines: list[str] = []
    path = tcm8_status_path()
    lines.append(f"  {marquee_slice(MARQUEE, offset, 48)}")
    lines.append("  8TCM STATE MACHINE")
    lines.append("")
    if not board:
        lines.append("  waiting for bot status file:")
        lines.append(f"  {path}")
        lines.append("")
        lines.append("  Start Recon Sniper. This window stays open.")
        lines.append("")
        lines.append(format_tcm8_cmd_tables(_with_ledger({})))
        return "\n".join(lines)
    age = time.time() - float(board.get("ts") or 0)
    stale = age > 8.0
    if not board.get("enabled"):
        lines.append("  8TCM PACK: OFF")
        lines.append("  Turn on 8TCM in Settings, then this board will move.")
        if stale:
            lines.append(f"  last update {age:.0f}s ago")
        lines.append("")
        lines.append(format_tcm8_cmd_tables(_with_ledger(board)))
        return "\n".join(lines)

    current = int(board.get("step_index") or 0)
    reason = str(board.get("reason") or "")
    blocked = (not board.get("accept")) and reason.startswith("REJECT") and not board.get("in_trade")
    for i, label in enumerate(STEPS):
        mark = _mark(i, current, blocked and i == current)
        extra = ""
        if i == current:
            extra = "  <=="
            if blocked:
                extra += f"  {reason}"
        lines.append(f"  {mark}  {label}{extra}")
        if label == STEP_TARGET:
            note = str(board.get("target_note") or "")
            if note:
                lines.append(f"           {note}")
            else:
                lines.append("           runner off  ->  flatten 8TCM_KEY_LEVEL_TARGET")
                lines.append("           runner on   ->  RUNNER_ACTIVE (trail after target)")
    lines.append("")
    trend = str(board.get("trend") or "—")
    seq = str(board.get("sequence") or "")
    lines.append(f"  TREND     {trend}  {seq}")
    src = str(board.get("source") or "")
    if src:
        lines.append(f"  SOURCE    {src}")
    swings = str(board.get("swings") or "")
    if swings:
        lines.append(f"  STRUCTURE {swings}")
    lines.append(
        f"  PRICE     {board.get('price')}    EMA8 {board.get('ema8')}    "
        f"distATR {board.get('distance_ema_atr')}    close {board.get('close_side') or '—'}"
    )
    lines.append(
        f"  RETRACE   {bool(board.get('retracement'))}    TEST {bool(board.get('tested'))}    "
        f"REJ {board.get('rejection') or '—'}"
    )
    tgt = board.get("target") or 0
    lines.append(
        f"  ENTRY     {board.get('entry') or '—'}    STOP {board.get('stop') or '—'}    "
        f"PRIMARY {tgt or '—'} {board.get('target_type') or ''}    R {board.get('target_r') or '—'}"
    )
    gates = dict(board.get("gates") or {})

    def g(name: str) -> str:
        return "OK" if gates.get(name, True) else "FAIL"

    lines.append(
        f"  GATES     ARM {g('arm')}   NT {g('nt')}   FLAT {g('flat')}   "
        f"ROOM {g('room')}   CHASE {g('chase')}   STOP {g('stop')}"
    )
    lines.append(
        f"  MODE      {board.get('mode') or '—'}    "
        f"1H {board.get('htf_1h') or '—'} (context)"
    )
    if board.get("in_trade"):
        hold = "RUNNER ACTIVE" if board.get("runner") else "INITIAL STOP ONLY"
        lines.append(f"  TRADE     {board.get('direction') or ''} {hold}")
    elif reason:
        lines.append(f"  LAST      {reason}")
    if stale:
        lines.append(f"  STALE     last bot write {age:.0f}s ago")
    lines.append("")
    lines.append(format_tcm8_cmd_tables(_with_ledger(board)))
    lines.append("")
    lines.append("  Close this window anytime. It does not stop the bot.")
    return "\n".join(lines)


def _paint_console(text: str) -> None:
    _cls()
    colored = []
    for line in text.splitlines():
        if "BRENTS TRADING BOT" in line or "•" in line[:20]:
            colored.append(f"{GOLD}{line}{RESET}")
        elif "<==" in line or "[>]" in line:
            colored.append(f"{GOLD}{line}{RESET}")
        elif "[!]" in line:
            colored.append(f"{RED}{line}{RESET}")
        elif "SESSION" in line or "LAST EXIT" in line or "OPEN  " in line or "NET " in line:
            colored.append(f"{GOLD}{line}{RESET}")
        elif "+$" in line:
            colored.append(f"{GOLD}{line}{RESET}")
        else:
            colored.append(f"{RED}{line}{RESET}")
    print("\n".join(colored), flush=True)


def _run_console() -> int:
    _enable_ansi()
    try:
        os.system("title BRENTS TRADING BOT")
        os.system("color 0C")
    except Exception:
        pass
    offset = 0
    while True:
        try:
            _paint_console(render(read_tcm8_status(), offset=offset))
            offset += 1
            time.sleep(0.12)
        except KeyboardInterrupt:
            print(f"\n{RED}  watcher stopped.{RESET}", flush=True)
            return 0
        except Exception as exc:
            print(f"{RED}  watch error: {exc}{RESET}", flush=True)
            time.sleep(1.0)


def _run_hud() -> int:
    import tkinter as tk
    from tkinter import font as tkfont

    family = register_ironman_font()
    root = tk.Tk()
    root.title("BRENTS TRADING BOT")
    root.configure(bg=IRON_BG)
    root.geometry("1080x760")
    root.minsize(820, 560)
    try:
        hud_font = tkfont.Font(root=root, family=family, size=13)
        title_font = tkfont.Font(root=root, family=family, size=22)
        data_font = tkfont.Font(root=root, family=family, size=14)
        if hud_font.actual("family").lower() in {"tkdefaultfont", "segoe ui", "arial", "ms sans serif"}:
            hud_font.configure(family=family)
    except tk.TclError:
        hud_font = title_font = data_font = None

    marquee = tk.Canvas(root, bg=IRON_BG, height=58, highlightthickness=0)
    marquee.pack(fill="x", padx=8, pady=(10, 0))
    body = tk.Text(
        root,
        bg=IRON_BG,
        fg=IRON_RED,
        insertbackground=IRON_RED,
        selectbackground="#3a0000",
        relief="flat",
        wrap="none",
        borderwidth=0,
        padx=18,
        pady=12,
    )
    if data_font is not None:
        body.configure(font=data_font)
    body.pack(fill="both", expand=True, padx=8, pady=8)
    body.tag_configure("gold", foreground=IRON_GOLD)
    body.tag_configure("red", foreground=IRON_RED)
    body.tag_configure("dim", foreground=IRON_RED_DIM)
    body.configure(state="disabled")

    state = {"mx": 40, "offset": 0}

    def draw_marquee() -> None:
        marquee.delete("all")
        w = max(marquee.winfo_width(), 200)
        text = (MARQUEE + "     •     ") * 12
        state["mx"] -= 4
        x = state["mx"]
        font = title_font or ("Arial", 22, "bold")
        marquee.create_text(x, 30, text=text, fill=IRON_RED, font=font, anchor="w")
        marquee.create_rectangle(0, 54, w, 56, fill=IRON_GOLD, outline="")
        if state["mx"] < -900:
            state["mx"] = 40
        root.after(40, draw_marquee)

    def refresh_board() -> None:
        text = render(read_tcm8_status(), offset=state["offset"])
        state["offset"] += 1
        body.configure(state="normal")
        body.delete("1.0", "end")
        lines = text.splitlines()
        if lines and "BRENTS TRADING BOT" in lines[0]:
            lines = lines[1:]
        for line in lines:
            tag = "red"
            if "<==" in line or "[>]" in line:
                tag = "gold"
            elif line.strip().startswith("[x]"):
                tag = "dim"
            body.insert("end", line + "\n", tag)
        body.configure(state="disabled")
        root.after(350, refresh_board)

    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.after(1500, lambda: root.attributes("-topmost", False))
        root.focus_force()
    except Exception:
        pass

    root.after(50, draw_marquee)
    root.after(80, refresh_board)
    root.mainloop()
    return 0


def main() -> int:
    register_ironman_font()
    try:
        return _run_hud()
    except Exception:
        return _run_console()


if __name__ == "__main__":
    sys.exit(main())
