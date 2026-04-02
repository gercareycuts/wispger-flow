#!/usr/bin/env python3
"""WispGer Flow — Hold Ctrl+Win to record, release to transcribe and paste."""

import ctypes
import math
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import numpy as np
import pyperclip
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard

# -- Paths --
APP_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
MODEL_DIR = APP_DIR / "models" / "base-ct2"

# -- Font (private load, app-only) --
for ttf in (APP_DIR / "fonts").glob("*.ttf"):
    ctypes.windll.gdi32.AddFontResourceExW(str(ttf), 0x10, 0)
F = "Poppins"

# -- Theme --
BG      = "#0f0f1a"
BG2     = "#161625"
CARD    = "#1c1c30"
ACCENT  = "#e67e22"
ACCENTH = "#f39c12"
TEAL    = "#00b894"
GREEN   = "#2ecc71"
RED     = "#ff4757"
REDDIM  = "#cc3040"
AMBER   = "#ffa502"
TXT     = "#e8e8f0"
TXT2    = "#8888a8"
DIM     = "#555570"
BORDER  = "#2a2a45"

# -- DPI-aware screen metrics --
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
_screen = ctypes.windll.user32.GetSystemMetrics


class AudioRecorder:
    def __init__(self, rate=16000):
        self.rate = rate
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self.level = 0.0

    def start(self):
        with self._lock:
            self._frames.clear()
        self.level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.rate, channels=1, blocksize=self.rate // 10, callback=self._cb,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level = 0.0
        with self._lock:
            out = np.concatenate(self._frames) if self._frames else None
            self._frames.clear()
            return out

    def _cb(self, indata, *_):
        with self._lock:
            self._frames.append(indata.copy())
        self.level = float(np.sqrt(np.mean(indata ** 2)))


class RecordingOverlay(tk.Toplevel):
    W, H, BARS, GAP = 180, 56, 20, 2

    def __init__(self, parent, rec):
        super().__init__(parent)
        self._rec = rec
        self._active = False
        self._heights = [0.0] * self.BARS
        self._phase = 0.0

        self.overrideredirect(True)
        self.attributes("-topmost", True, "-alpha", 0.90)
        self.configure(bg="#010101")
        self.wm_attributes("-transparentcolor", "#010101")

        self._c = tk.Canvas(self, width=self.W, height=self.H, bg="#010101", highlightthickness=0, bd=0)
        self._c.pack(fill="both", expand=True)
        self._reposition()
        self.withdraw()

    def _reposition(self):
        x = (_screen(0) - self.W) // 2
        y = _screen(1) - self.H - 50
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _rrect(self, x0, y0, x1, y1, r, **kw):
        c = self._c
        c.create_arc(x0, y0, x0+2*r, y0+2*r, start=90, extent=90, style="pieslice", **kw)
        c.create_arc(x1-2*r, y0, x1, y0+2*r, start=0, extent=90, style="pieslice", **kw)
        c.create_arc(x0, y1-2*r, x0+2*r, y1, start=180, extent=90, style="pieslice", **kw)
        c.create_arc(x1-2*r, y1-2*r, x1, y1, start=270, extent=90, style="pieslice", **kw)
        c.create_rectangle(x0+r, y0, x1-r, y1, **kw)
        c.create_rectangle(x0, y0+r, x1, y1-r, **kw)

    def show(self):
        self._active = True
        self._phase = 0.0
        self._heights = [0.0] * self.BARS
        self._reposition()
        self.deiconify()
        self.lift()
        self._tick()

    def hide(self):
        self._active = False
        self.withdraw()

    def _tick(self):
        if not self._active:
            return
        self._c.delete("b")
        self._rrect(0, 0, self.W, self.H, 14, fill="#333338", outline="", tags="b")

        level = min(self._rec.level * 50, 1.0)
        self._phase += 0.25
        bw = (self.W - 20) / self.BARS - self.GAP
        mh, cx = self.H - 8, self.BARS / 2

        for i in range(self.BARS):
            d = abs(i - cx) / cx
            t = level * (math.sin(self._phase + i * 0.5) * 0.4 + 0.6) * (1 - d * 0.4) * mh
            self._heights[i] += (max(t, 2) - self._heights[i]) * 0.7
            h = self._heights[i]
            x0 = 10 + i * (bw + self.GAP)
            y0 = (self.H - h) / 2
            br = 1 - d * 0.35
            self._c.create_rectangle(
                x0, y0, x0 + bw, y0 + h, tags="b", outline="",
                fill=f"#{int(230*br):02x}{int(126*br):02x}{int(34*br):02x}",
            )
        self.after(25, self._tick)


class TranscriptionCard(ctk.CTkFrame):
    def __init__(self, parent, text, duration, ts):
        super().__init__(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        self._text = text

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(hdr, text="\u223f", font=(F, 16, "bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(hdr, text=ts.strftime("%I:%M %p"), font=(F, 11), text_color=TXT2).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(hdr, text=f"{duration:.1f}s", font=(F, 11, "bold"), text_color="#fff", fg_color=TEAL, corner_radius=8, width=50, height=24).pack(side="right")

        ctk.CTkLabel(self, text=text, font=(F, 13), text_color=TXT, wraplength=340, justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        self._btn = ctk.CTkButton(self, text="\u2398  Copy", width=95, height=32, corner_radius=8, font=(F, 12, "bold"), fg_color=ACCENT, hover_color=ACCENTH, command=self._copy)
        self._btn.pack(anchor="e", padx=16, pady=(0, 14))

    def _copy(self):
        pyperclip.copy(self._text)
        self._btn.configure(text="\u2713  Copied!", fg_color=GREEN)
        self.after(1500, lambda: self._btn.configure(text="\u2398  Copy", fg_color=ACCENT))


class StatusDot(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._dot = ctk.CTkLabel(self, text="\u25cf", font=(F, 10), text_color=TEAL, width=16)
        self._dot.pack(side="left")
        self._lbl = ctk.CTkLabel(self, text="Ready", font=(F, 11), text_color=TXT2)
        self._lbl.pack(side="left", padx=(4, 0))
        self._pulsing = False
        self._on = True

    def ready(self):
        self._pulsing = False
        self._dot.configure(text_color=TEAL)
        self._lbl.configure(text="Ready", text_color=TXT2)

    def recording(self):
        self._pulsing = True
        self._lbl.configure(text="Recording", text_color=RED)
        self._pulse()

    def processing(self):
        self._pulsing = False
        self._dot.configure(text_color=AMBER)
        self._lbl.configure(text="Processing...", text_color=AMBER)

    def _pulse(self):
        if not self._pulsing:
            return
        self._on = not self._on
        self._dot.configure(text_color=RED if self._on else REDDIM)
        self.after(500, self._pulse)


class WispGerFlow(ctk.CTk):
    def __init__(self, model_dir=str(MODEL_DIR), lang="en", rate=16000):
        super().__init__()
        self.title("WispGer Flow")
        self.geometry("460x680+80+60")
        self.minsize(400, 500)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        ctk.set_appearance_mode("dark")

        print(f"Loading model from {model_dir}...")
        self._model = WhisperModel(model_dir, device="cpu", compute_type="int8")
        self._lang = lang
        print("Model loaded.")

        self._rec = AudioRecorder(rate)
        self._kb = keyboard.Controller()
        self._recording = False
        self._ctrl = self._win = False
        self._t0 = None
        self._cards: list[TranscriptionCard] = []
        self._lock = threading.Lock()

        self._build_ui()
        self._overlay = RecordingOverlay(self, self._rec)
        keyboard.Listener(on_press=self._press, on_release=self._release, daemon=True).start()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color=BG2, corner_radius=0, height=60)
        top.pack(fill="x")
        top.pack_propagate(False)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(brand, text="\u223f", font=(F, 26, "bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(brand, text="WispGer Flow", font=(F, 16, "bold"), text_color=TXT).pack(side="left", padx=(10, 0))

        self._status = StatusDot(top)
        self._status.pack(side="right", padx=20, pady=12)

        hint = ctk.CTkFrame(self, fg_color=BG2, corner_radius=0, height=36)
        hint.pack(fill="x")
        hint.pack_propagate(False)
        ctk.CTkFrame(hint, fg_color=BORDER, height=1).pack(fill="x", side="top")
        ctk.CTkLabel(hint, text="Hold  Ctrl + Win  to record   \u2022   Release to transcribe & paste", font=(F, 10), text_color=DIM).pack(expand=True)

        self._content = ctk.CTkScrollableFrame(self, fg_color=BG, scrollbar_button_color=BORDER, corner_radius=0)
        self._content.pack(fill="both", expand=True)

        self._empty = ctk.CTkFrame(self._content, fg_color="transparent")
        self._empty.pack(fill="x", pady=80)
        ctk.CTkLabel(self._empty, text="\u223f", font=(F, 56, "bold"), text_color=DIM).pack()
        ctk.CTkLabel(self._empty, text="No transcriptions yet", font=(F, 16, "bold"), text_color=DIM).pack(pady=(16, 4))
        ctk.CTkLabel(self._empty, text="Hold Ctrl+Win and start speaking.\nYour transcriptions will appear here.", font=(F, 11), text_color=DIM, justify="center").pack()

        bot = ctk.CTkFrame(self, fg_color=BG2, corner_radius=0, height=32)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)
        ctk.CTkFrame(bot, fg_color=BORDER, height=1).pack(fill="x", side="top")
        ctk.CTkLabel(bot, text="faster-whisper (int8)", font=(F, 9), text_color=DIM).pack(side="left", padx=16)
        self._count = ctk.CTkLabel(bot, text="0 transcriptions", font=(F, 9), text_color=DIM)
        self._count.pack(side="right", padx=16)

    def _add_card(self, text, dur):
        if self._empty:
            self._empty.destroy()
            self._empty = None
        card = TranscriptionCard(self._content, text, dur, datetime.now())
        if self._cards:
            card.pack(fill="x", padx=12, pady=(8, 0), before=self._cards[0])
        else:
            card.pack(fill="x", padx=12, pady=(8, 0))
        self._cards.insert(0, card)
        n = len(self._cards)
        self._count.configure(text=f"{n} transcription{'s' if n != 1 else ''}")

    def _press(self, key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._ctrl = True
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r):
            self._win = True
        if self._ctrl and self._win and not self._recording:
            self._recording = True
            self._t0 = time.time()
            self._rec.start()
            self.after(0, self._status.recording)
            self.after(0, self._overlay.show)

    def _release(self, key):
        both = self._ctrl and self._win
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._ctrl = False
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r):
            self._win = False
        if both and self._recording and not (self._ctrl and self._win):
            self._recording = False
            dur = time.time() - self._t0 if self._t0 else 0.0
            audio = self._rec.stop()
            self.after(0, self._overlay.hide)
            self.after(0, self._status.processing)
            if audio is not None and len(audio) > 0:
                threading.Thread(target=self._transcribe, args=(audio, dur), daemon=True).start()
            else:
                self.after(0, self._status.ready)

    def _transcribe(self, audio, dur):
        if not self._lock.acquire(blocking=False):
            return
        try:
            segs, _ = self._model.transcribe(audio.flatten().astype(np.float32), language=self._lang, beam_size=1, vad_filter=True)
            text = "".join(s.text for s in segs).strip()
            if not text:
                self.after(0, self._status.ready)
                return
            print(f"[{dur:.1f}s] {text}")
            pyperclip.copy(text)
            time.sleep(0.05)
            self._kb.press(keyboard.Key.ctrl)
            self._kb.press("v")
            self._kb.release("v")
            self._kb.release(keyboard.Key.ctrl)
            self.after(0, lambda: self._add_card(text, dur))
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self._lock.release()
            self.after(0, self._status.ready)


if __name__ == "__main__":
    print("\n  WispGer Flow\n  Ctrl+Win to record. Release to paste.\n")
    WispGerFlow().mainloop()
