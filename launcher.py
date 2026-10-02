# -*- coding: utf-8 -*-
# OSInt Tracker - Copyright (C) 2024-2026 Andrea Cumini <andrea@osintinfo.net>
# SPDX-License-Identifier: GPL-3.0-only
# GNU GPL v3 with additional terms (author attribution): see LICENSE and NOTICE.
"""Launcher di OSInt Tracker: un pannellino senza bordi, sempre in
primo piano in basso a destra, con tre pulsanti:

    ▶  avvia il server        ■  lo ferma        🌐  apre il browser

Il pallino indica lo stato: grigio = fermo, giallo = in avvio, verde = il
server risponde. All'apertura del launcher il server parte da solo e, appena
risponde, si apre il browser su URL. Il pannello si sposta trascinandolo dalla
maniglia a sinistra; ✕ chiude tutto (anche il server, se l'ha avviato lui).

Cosa avvia:
  - in sviluppo: app.py accanto al launcher, con il Python del progetto (.venv) se c'e';
  - nell'eseguibile PyInstaller: l'exe stesso con l'opzione --server (vedi build.py).

Porta: variabile PORT o opzione --port (default 5000, come app.py).
L'output del server finisce in launcher.log, accanto al launcher.

Uso:   .venv\\Scripts\\pythonw.exe launcher.py      (senza finestra console)
"""
import os
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser

FROZEN = getattr(sys, "frozen", False)
ROOT = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
IS_WIN = os.name == "nt"


def _port():
    argv = sys.argv[1:]
    if "--port" in argv:
        i = argv.index("--port")
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            return int(argv[i + 1])
    p = os.environ.get("PORT", "5000")
    return int(p) if p.isdigit() else 5000


PORT = _port()
URL = f"http://127.0.0.1:{PORT}"
LOG = os.path.join(ROOT, "launcher.log")

# Codice d'uscita con cui il server termina quando l'utente non accetta
# l'avviso legale mostrato all'apertura (app.py: TERMS_DECLINED_EXIT)
TERMS_DECLINED_EXIT = 3

# colori del pannello
BG, FG, MUTED, HOVER = "#0f172a", "#e2e8f0", "#64748b", "#1e293b"
DOT = {"stopped": "#64748b", "starting": "#f59e0b", "running": "#22c55e"}


def server_command():
    """Comando che avvia il server (vedi l'ordine nella docstring)."""
    if FROZEN:
        return [sys.executable, "--server"]        # l'exe fa anche da server
    app = os.path.join(ROOT, "app.py")
    if not os.path.isfile(app):
        return None
    venv = os.path.join(ROOT, ".venv", "Scripts" if IS_WIN else "bin",
                        "python.exe" if IS_WIN else "python")
    py = venv if os.path.isfile(venv) else sys.executable
    if IS_WIN and py.lower().endswith("pythonw.exe"):
        py = py[:-5] + ".exe"                     # serve l'output per il log
    return [py, app]


def server_alive(timeout=0.6):
    """Il server accetta connessioni sulla porta? (semplice connessione TCP:
    a differenza di una richiesta HTTP non riempie il log del server)"""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout):
            return True
    except OSError:
        return False


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.proc = None
        self.logf = None
        self.state = "stopped"
        self.open_when_ready = False
        self._drag = (0, 0)

        self.overrideredirect(True)          # senza bordi né barra del titolo
        self.attributes("-topmost", True)
        self.configure(bg=BG)

        bar = tk.Frame(self, bg=BG, padx=4, pady=3)
        bar.pack(fill="both", expand=True)

        grip = tk.Label(bar, text="⋮⋮", bg=BG, fg=MUTED, cursor="fleur",
                        font=("Segoe UI", 9))
        grip.pack(side="left", padx=(2, 4))
        self.dot = tk.Canvas(bar, width=10, height=10, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=DOT["stopped"], outline="")
        self.dot.pack(side="left", padx=(0, 6))

        self.b_start = self._btn(bar, "▶", self.start, "Start the server")
        self.b_stop = self._btn(bar, "■", self.stop, "Stop the server")
        self.b_open = self._btn(bar, "🌐", self.open_browser, f"Open {URL}")
        tk.Frame(bar, width=1, bg=HOVER).pack(side="left", fill="y", padx=4, pady=2)
        self._btn(bar, "✕", self.quit_app, "Close all")

        # trascinamento dalla maniglia e dal pallino
        for w in (grip, self.dot, bar):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.tip = None
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{sw - w - 24}+{sh - h - 64}")    # in basso a destra

        self._refresh_buttons()
        self._poll()
        self.after(200, self.autostart)

    # ---------------------------------------------------------------- widget
    def _btn(self, parent, text, cmd, tip):
        b = tk.Label(parent, text=text, bg=BG, fg=FG, width=2, cursor="hand2",
                     font=("Segoe UI Symbol", 11))
        b.pack(side="left", padx=1)
        b.enabled = True
        b.bind("<Enter>", lambda e: (b.enabled and b.configure(bg=HOVER), self._show_tip(b, tip)))
        b.bind("<Leave>", lambda e: (b.configure(bg=BG), self._hide_tip()))
        b.bind("<ButtonRelease-1>", lambda e: b.enabled and cmd())
        return b

    def _enable(self, b, on):
        b.enabled = on
        b.configure(fg=FG if on else MUTED, cursor="hand2" if on else "arrow")

    def _show_tip(self, w, text):
        self._hide_tip()
        self.tip = tk.Toplevel(self)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        tk.Label(self.tip, text=text, bg="#334155", fg=FG, padx=6, pady=2,
                 font=("Segoe UI", 8)).pack()
        self.tip.update_idletasks()
        x = w.winfo_rootx() + w.winfo_width() // 2 - self.tip.winfo_reqwidth() // 2
        y = self.winfo_rooty() - self.tip.winfo_reqheight() - 4
        self.tip.geometry(f"+{x}+{y}")

    def _hide_tip(self):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    # ---------------------------------------------------------------- stato
    def _set_state(self, st):
        self.state = st
        self.dot.itemconfigure(self.dot_id, fill=DOT[st])
        self._refresh_buttons()

    def _refresh_buttons(self):
        ours = self.proc is not None and self.proc.poll() is None
        self._enable(self.b_start, self.state == "stopped")
        self._enable(self.b_stop, ours)
        self._enable(self.b_open, self.state == "running")

    def _poll(self):
        """Ogni secondo controlla se il server risponde (anche se avviato
        altrove) e se il processo avviato dal launcher e' ancora vivo."""
        def check():
            alive = server_alive()
            self.after(0, lambda: self._apply_poll(alive))
        threading.Thread(target=check, daemon=True).start()
        self.after(1000, self._poll)

    def _apply_poll(self, alive):
        ours = self.proc is not None and self.proc.poll() is None
        if alive:
            if self.state != "running":
                self._set_state("running")
            if self.open_when_ready:              # avvio automatico: browser appena pronto
                self.open_when_ready = False
                self.open_browser()
        elif ours:
            if self.state != "starting":
                self._set_state("starting")
        else:
            if self.proc is not None:                 # il server e' terminato da solo
                declined = self.proc.poll() == TERMS_DECLINED_EXIT
                self._close_log()
                self.proc = None
                self.open_when_ready = False
                if declined:                          # avviso legale rifiutato: si chiude tutto
                    self.destroy()
                    return
            if self.state != "stopped":
                self._set_state("stopped")
        self._refresh_buttons()

    # ---------------------------------------------------------------- azioni
    def autostart(self):
        """All'apertura: avvia il server (se non risponde gia') e poi apre il browser"""
        self.open_when_ready = True
        if not server_alive():
            self.start()

    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        cmd = server_command()
        if not cmd:
            self._show_tip(self.b_start, "app.py not found")
            self.after(2500, self._hide_tip)
            return
        env = dict(os.environ, PORT=str(PORT), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        self.logf = open(LOG, "a", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=self.logf,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=flags,
                                     start_new_session=not IS_WIN)
        self._set_state("starting")

    def stop(self):
        p = self.proc
        if p is None or p.poll() is not None:
            return
        # chiude tutto l'albero del processo, non solo quello avviato
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                import signal
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        self.proc = None
        self._close_log()
        self._set_state("stopped")

    def open_browser(self):
        webbrowser.open(URL)                     # browser predefinito del sistema

    def _close_log(self):
        if self.logf is not None:
            try:
                self.logf.close()
            except Exception:
                pass
            self.logf = None

    def quit_app(self):
        self.stop()
        self.destroy()


def main():
    if IS_WIN:
        try:                                     # testo nitido sugli schermi HiDPI
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    Launcher().mainloop()


if __name__ == "__main__":
    main()
