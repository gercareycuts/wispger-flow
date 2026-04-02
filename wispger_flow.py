#!/usr/bin/env python3
"""WispGer Flow — Voice to text, refined. Hold Ctrl+Win to record, release to paste."""

import array, ctypes, io, json, math, os, sys, threading, time, tkinter as tk, wave
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import pyperclip, requests, sounddevice as sd
from pynput import keyboard

# -- Paths & Font --
APP_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
CFG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WispGer"
CFG_FILE = CFG_DIR / "config.json"
for ttf in (APP_DIR / "fonts").glob("*.ttf"):
    ctypes.windll.gdi32.AddFontResourceExW(str(ttf), 0x10, 0)
F = "Poppins"

# -- Theme --
DARK = {"bg": "#0f0f1a", "bg2": "#161625", "card": "#1c1c30", "txt": "#e8e8f0",
        "txt2": "#8888a8", "dim": "#555570", "border": "#2a2a45", "overlay": "#333338", "sidebar": "#12121f"}
LIGHT = {"bg": "#f0f0f5", "bg2": "#e4e4ec", "card": "#ffffff", "txt": "#1a1a2e",
         "txt2": "#555570", "dim": "#8888a8", "border": "#d0d0dd", "overlay": "#e0e0e8", "sidebar": "#dcdce8"}
ACCENT, ACCENTH, TEAL, GREEN = "#e67e22", "#f39c12", "#00b894", "#2ecc71"
RED, REDDIM, AMBER = "#ff4757", "#cc3040", "#ffa502"

# -- DPI --
try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception: pass
_scr = ctypes.windll.user32.GetSystemMetrics

# -- API --
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"

# -- Fillers & Achievements --
FILLERS = {"um","uh","er","ah","like","you know","i mean","sort of","kind of",
           "basically","actually","literally","honestly","right","well","anyway","so"}

ACHIEVEMENTS = [
    ("w2000","words",2000,"\U0001f399","First Words","Everyone starts somewhere","bronze"),
    ("w5000","words",5000,"\U0001f4ac","Chatterbox","You clearly have opinions","silver"),
    ("w10000","words",10000,"\U0001f4dd","Wordsmith","Shakespeare is quaking","gold"),
    ("w20000","words",20000,"\U0001f4da","Novelist","That's a short book right there","gold"),
    ("w30000","words",30000,"\U0001f3c6","Marathon Speaker","Do you ever stop talking?","diamond"),
    ("w100000","words",100000,"\U0001f30d","War & Peace","Tolstoy would be proud","diamond"),
    ("t25","txns",25,"\U0001f3af","Getting Started","Welcome aboard","bronze"),
    ("t100","txns",100,"\u26a1","Power User","Keyboard? Never heard of it","silver"),
    ("t250","txns",250,"\U0001f4af","Centurion","A hundred and counting","gold"),
    ("t500","txns",500,"\U0001f916","Voice Addict","Your keyboard is collecting dust","diamond"),
    ("like500","like",500,"\U0001f644","Like, Totally","Are you in high school?","roast"),
    ("um200","um",200,"\U0001f914","The Thinker","Uhhhhhhhhhhhh...","roast"),
    ("dup3","dupes",3,"\U0001f99c","Broken Record","You said the same thing 3x","roast"),
    ("night10","night",10,"\U0001f319","Night Owl","Go to bed already","roast"),
    ("speed200","speed",1,"\U0001f407","Speed Demon","Slow down, auctioneer","roast"),
    ("tiny5","tiny",5,"\U0001f90f","One Word Wonder","Could've just typed it","roast"),
    ("long60","long",1,"\U0001f4d6","Monologue King","Sir, this is a Wendy's","roast"),
    ("morning10","morning",10,"\u2615","Morning Person","Rise and grind","roast"),
]
TIER_COL = {"bronze":"#cd7f32","silver":"#8a8a9a","gold":"#f39c12","diamond":TEAL,"roast":RED}

# -- Tooltip --
class Tooltip:
    def __init__(self, widget, text):
        self._w, self._text, self._tw, self._after_id = widget, text, None, None
        self._mx, self._my = 0, 0
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<Motion>", self._motion)
        for child in widget.winfo_children():
            child.bind("<Enter>", self._enter)
            child.bind("<Leave>", self._leave)
            child.bind("<Motion>", self._motion)

    def _enter(self, e):
        self._mx, self._my = e.x_root, e.y_root
        if not self._after_id:
            self._after_id = self._w.after(100, self._show)

    def _leave(self, e):
        if self._after_id: self._w.after_cancel(self._after_id); self._after_id = None
        if self._tw: self._tw.destroy(); self._tw = None

    def _motion(self, e):
        self._mx, self._my = e.x_root, e.y_root
        if self._tw: self._tw.geometry(f"+{self._mx+14}+{self._my+18}")

    def _show(self):
        self._after_id = None
        if self._tw: return
        self._tw = tw = tk.Toplevel(self._w)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.wm_attributes("-disabled", True)
        tw.configure(bg="#1a1a2e")
        tk.Label(tw, text=self._text, bg="#1a1a2e", fg="#e8e8f0", font=(F, 8),
                 padx=8, pady=4, wraplength=200, justify="left").pack()
        tw.update_idletasks()
        tw.geometry(f"+{self._mx+14}+{self._my+18}")

# -- Achievement hover descriptions --
ACH_HINTS = {
    "words": "Transcribe {target:,} words to unlock this achievement",
    "txns": "Complete {target:,} transcriptions to unlock this achievement",
    "like": "Say the word 'like' {target:,} times across your transcriptions",
    "um": "Say 'um' or 'uh' {target:,} times across your transcriptions",
    "dupes": "Transcribe the same thing {target} times",
    "night": "Transcribe after midnight {target} times",
    "speed": "Transcribe 200+ words in a single recording",
    "tiny": "Transcribe just 1 word {target} times",
    "long": "Record for 60+ seconds in a single session",
    "morning": "Transcribe before 7am {target} times",
}

# -- Config --
def _load_cfg():
    try: return json.loads(CFG_FILE.read_text()) if CFG_FILE.exists() else {}
    except Exception: return {}

def _save_cfg(data):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(); cfg.update(data)
    CFG_FILE.write_text(json.dumps(cfg))

def _default_stats():
    return {"total_words":0,"total_txns":0,"total_secs":0.0,"fillers":0,
            "like_count":0,"um_count":0,"dupes":0,"night_count":0,
            "speed_count":0,"tiny_count":0,"long_count":0,"morning_count":0,
            "first_use":None,"unlocked":[]}


# ============================================================================
class AudioRecorder:
    RATE = 16000
    def __init__(self):
        self._chunks, self._stream, self._lock, self.level = [], None, threading.Lock(), 0.0

    def start(self):
        with self._lock: self._chunks.clear()
        self.level = 0.0
        self._stream = sd.RawInputStream(samplerate=self.RATE, channels=1, dtype="int16",
                                         blocksize=self.RATE//10, callback=self._cb)
        self._stream.start()

    def stop(self):
        if self._stream: self._stream.stop(); self._stream.close(); self._stream = None
        self.level = 0.0
        with self._lock:
            data = b"".join(self._chunks); self._chunks.clear(); return data

    def _cb(self, indata, *_):
        raw = bytes(indata)
        with self._lock: self._chunks.append(raw)
        s = array.array("h", raw)
        if s: self.level = math.sqrt(sum(v*v for v in s[::8]) / max(len(s)//8, 1)) / 32768.0

    def to_wav(self, pcm):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.RATE); w.writeframes(pcm)
        return buf.getvalue()


# ============================================================================
class ApiKeyDialog(ctk.CTkToplevel):
    def __init__(self, parent, t):
        super().__init__(parent)
        self.title("WispGer Flow — Setup"); self.geometry("420x280")
        self.configure(fg_color=t["bg"]); self.attributes("-topmost", True)
        self.resizable(False, False); self.grab_set(); self.result = None
        ctk.CTkLabel(self, text="\u223f", font=(F,36,"bold"), text_color=ACCENT).pack(pady=(24,8))
        ctk.CTkLabel(self, text="Enter your Groq API key", font=(F,16,"bold"), text_color=t["txt"]).pack()
        ctk.CTkLabel(self, text="Free signup at groq.com \u2192 API Keys", font=(F,11), text_color=t["dim"]).pack(pady=(4,16))
        self._e = ctk.CTkEntry(self, width=340, height=38, font=(F,12), placeholder_text="gsk_...",
                               fg_color=t["card"], border_color=t["border"], text_color=t["txt"])
        self._e.pack(); self._e.bind("<Return>", lambda _: self._ok())
        self._err = ctk.CTkLabel(self, text="", font=(F,10), text_color=RED); self._err.pack(pady=(4,0))
        ctk.CTkButton(self, text="Save & Start", width=160, height=36, corner_radius=8,
                      font=(F,12,"bold"), fg_color=ACCENT, hover_color=ACCENTH, command=self._ok).pack(pady=(12,0))
        self.protocol("WM_DELETE_WINDOW", lambda: (setattr(self,"result",None), self.destroy()))

    def _ok(self):
        k = self._e.get().strip()
        if not k: self._err.configure(text="Please enter an API key")
        elif not k.startswith("gsk_"): self._err.configure(text="Key should start with gsk_")
        else: self.result = k; self.destroy()


# ============================================================================
class RecordingOverlay(tk.Toplevel):
    W, H, N, GAP = 180, 56, 20, 2
    def __init__(self, parent, rec):
        super().__init__(parent)
        self._rec, self._active, self._h, self._ph = rec, False, [0.0]*self.N, 0.0
        self._fill = DARK["overlay"]
        self.overrideredirect(True); self.attributes("-topmost", True, "-alpha", 0.90)
        self.configure(bg="#010101"); self.wm_attributes("-transparentcolor", "#010101")
        self._c = tk.Canvas(self, width=self.W, height=self.H, bg="#010101", highlightthickness=0, bd=0)
        self._c.pack(fill="both", expand=True); self.withdraw()

    def set_theme(self, t): self._fill = t["overlay"]
    def _pos(self): self.geometry(f"{self.W}x{self.H}+{(_scr(0)-self.W)//2}+{_scr(1)-self.H-50}")

    def _rr(self, x0, y0, x1, y1, r, **kw):
        c = self._c
        for sx,sy,a in [(x0,y0,90),(x1-2*r,y0,0),(x0,y1-2*r,180),(x1-2*r,y1-2*r,270)]:
            c.create_arc(sx,sy,sx+2*r,sy+2*r, start=a, extent=90, style="pieslice", **kw)
        c.create_rectangle(x0+r,y0,x1-r,y1,**kw); c.create_rectangle(x0,y0+r,x1,y1-r,**kw)

    def show(self):
        self._active, self._ph, self._h = True, 0.0, [0.0]*self.N
        self._pos(); self.deiconify(); self.lift(); self._tick()

    def hide(self): self._active = False; self.withdraw()

    def _tick(self):
        if not self._active: return
        self._c.delete("b"); self._rr(0,0,self.W,self.H,14, fill=self._fill, outline="", tags="b")
        lv, self._ph = min(self._rec.level*50, 1.0), self._ph+0.25
        bw, mh, cx = (self.W-20)/self.N - self.GAP, self.H-8, self.N/2
        for i in range(self.N):
            d = abs(i-cx)/cx
            t = lv*(math.sin(self._ph+i*0.5)*0.4+0.6)*(1-d*0.4)*mh
            self._h[i] += (max(t,2)-self._h[i])*0.7; h = self._h[i]
            x0, br = 10+i*(bw+self.GAP), 1-d*0.35
            self._c.create_rectangle(x0,(self.H-h)/2, x0+bw,(self.H+h)/2, tags="b", outline="",
                fill=f"#{int(230*br):02x}{int(126*br):02x}{int(34*br):02x}")
        self.after(25, self._tick)


# ============================================================================
class TranscriptionCard(ctk.CTkFrame):
    def __init__(self, parent, text, dur, ts, t):
        super().__init__(parent, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        self._text = text
        hdr = ctk.CTkFrame(self, fg_color="transparent"); hdr.pack(fill="x", padx=16, pady=(14,6))
        ctk.CTkLabel(hdr, text="\u223f", font=(F,16,"bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(hdr, text=ts.strftime("%I:%M %p"), font=(F,11), text_color=t["txt2"]).pack(side="left", padx=(8,0))
        ctk.CTkLabel(hdr, text=f"{dur:.1f}s", font=(F,11,"bold"), text_color="#fff",
                     fg_color=TEAL, corner_radius=8, width=50, height=24).pack(side="right")
        ctk.CTkLabel(self, text=text, font=(F,13), text_color=t["txt"], wraplength=380,
                     justify="left", anchor="w").pack(fill="x", padx=16, pady=(0,8))
        self._btn = ctk.CTkButton(self, text="\u2398  Copy", width=95, height=32, corner_radius=8,
                                  font=(F,12,"bold"), fg_color=ACCENT, hover_color=ACCENTH, command=self._copy)
        self._btn.pack(anchor="e", padx=16, pady=(0,14))

    def _copy(self):
        pyperclip.copy(self._text)
        self._btn.configure(text="\u2713  Copied!", fg_color=GREEN)
        self.after(1500, lambda: self._btn.configure(text="\u2398  Copy", fg_color=ACCENT))


# ============================================================================
class StatusDot(ctk.CTkFrame):
    def __init__(self, parent, t):
        super().__init__(parent, fg_color="transparent")
        self._dot = ctk.CTkLabel(self, text="\u25cf", font=(F,10), text_color=TEAL, width=16)
        self._dot.pack(side="left")
        self._lbl = ctk.CTkLabel(self, text="Ready", font=(F,11), text_color=t["txt2"])
        self._lbl.pack(side="left", padx=(4,0))
        self._pulsing = self._on = False

    def ready(self):    self._pulsing=False; self._dot.configure(text_color=TEAL); self._lbl.configure(text="Ready")
    def recording(self): self._pulsing=True; self._lbl.configure(text="Recording", text_color=RED); self._pulse()
    def processing(self): self._pulsing=False; self._dot.configure(text_color=AMBER); self._lbl.configure(text="Processing...", text_color=AMBER)
    def error(self, m="Error"): self._pulsing=False; self._dot.configure(text_color=RED); self._lbl.configure(text=m, text_color=RED)
    def _pulse(self):
        if not self._pulsing: return
        self._on = not self._on; self._dot.configure(text_color=RED if self._on else REDDIM)
        self.after(500, self._pulse)


# ============================================================================
class WispGerFlow(ctk.CTk):
    SB_W, SB_C = 200, 56

    def __init__(self, lang="en"):
        super().__init__()
        self.title("WispGer Flow"); self.geometry("780x680+60+40"); self.minsize(640,500)
        self.attributes("-topmost", True); self.protocol("WM_DELETE_WINDOW", self.destroy)
        ctk.set_appearance_mode("dark")

        cfg = _load_cfg()
        self._dark = cfg.get("dark_mode", True)
        self._theme = DARK if self._dark else LIGHT
        self._collapsed = cfg.get("sidebar_collapsed", False)
        self.configure(fg_color=self._theme["bg"])

        self._lang, self._key = lang, cfg.get("groq_api_key", os.environ.get("GROQ_API_KEY",""))
        self._stats = {**_default_stats(), **cfg.get("stats",{})}
        if not self._stats["first_use"]: self._stats["first_use"] = datetime.now().isoformat()
        self._last_texts = []
        self._rec, self._kb = AudioRecorder(), keyboard.Controller()
        self._recording, self._ctrl, self._win, self._t0 = False, False, False, None
        self._cards, self._lock, self._view = [], threading.Lock(), "transcriptions"

        self._build_ui()
        self._overlay = RecordingOverlay(self, self._rec); self._overlay.set_theme(self._theme)
        keyboard.Listener(on_press=self._press, on_release=self._release, daemon=True).start()
        if not self._key: self.after(200, self._ask_key)

    def _ask_key(self):
        d = ApiKeyDialog(self, self._theme); self.wait_window(d)
        if d.result: self._key = d.result; _save_cfg({"groq_api_key": d.result})
        else: self.destroy()

    # -- Fast native scrollable --
    def _mk_scroll(self, parent, bg):
        c = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=c.yview)
        inner = tk.Frame(c, bg=bg)
        inner.bind("<Configure>", lambda e: c.configure(scrollregion=c.bbox("all")))
        wid = c.create_window((0,0), window=inner, anchor="nw")
        c.configure(yscrollcommand=sb.set)
        c.bind("<Configure>", lambda e: c.itemconfigure(wid, width=e.width))
        def scroll(e): c.yview_scroll(int(-1*(e.delta/90)), "units")
        c.bind("<Enter>", lambda e: c.bind_all("<MouseWheel>", scroll))
        c.bind("<Leave>", lambda e: c.unbind_all("<MouseWheel>"))
        c.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        return c, inner

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        t = self._theme
        self._sidebar = ctk.CTkFrame(self, fg_color=t["sidebar"], corner_radius=0,
                                     width=self.SB_C if self._collapsed else self.SB_W)
        self._sidebar.pack(side="left", fill="y"); self._sidebar.pack_propagate(False)
        self._right = ctk.CTkFrame(self, fg_color=t["bg"], corner_radius=0)
        self._right.pack(side="left", fill="both", expand=True)
        self._build_sidebar(t); self._build_content(t)

    def _build_sidebar(self, t):
        lf = ctk.CTkFrame(self._sidebar, fg_color="transparent"); lf.pack(fill="x", padx=12, pady=(20,24))
        self._logo = ctk.CTkLabel(lf, text="\u223f", font=(F,24,"bold"), text_color=ACCENT); self._logo.pack(side="left")
        self._logo_txt = ctk.CTkLabel(lf, text="WispGer Flow", font=(F,14,"bold"), text_color=t["txt"])
        if not self._collapsed: self._logo_txt.pack(side="left", padx=(8,0))

        self._nav_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent"); self._nav_frame.pack(fill="x", padx=8)
        self._nav_btns = {}
        for vid, icon, label in [("transcriptions","\U0001f4cb","Transcriptions"),("dashboard","\U0001f4ca","Dashboard")]:
            f = ctk.CTkFrame(self._nav_frame, fg_color="transparent", cursor="hand2"); f.pack(fill="x", pady=2)
            active = vid == self._view
            fg = "#fff" if active else t["txt2"]
            li = ctk.CTkLabel(f, text=icon, font=(F,16), width=32, text_color=fg); li.pack(side="left", padx=(4,0))
            lt = ctk.CTkLabel(f, text=label, font=(F,12,"bold" if active else "normal"), text_color=fg)
            if not self._collapsed: lt.pack(side="left", padx=(6,0))
            f.configure(fg_color=ACCENT if active else "transparent", corner_radius=8)
            for w in (f, li, lt): w.bind("<Button-1>", lambda e, v=vid: self._switch_view(v))
            self._nav_btns[vid] = {"frame":f, "icon":li, "label":lt}

        ctk.CTkFrame(self._sidebar, fg_color="transparent").pack(fill="both", expand=True)

        # Theme + Collapse + Status
        for icon, txt, cmd, attr_i, attr_t in [
            ("\u263e" if self._dark else "\u2600", "Theme", self._toggle_theme, "_theme_icon", "_theme_txt"),
            ("\u00bb" if self._collapsed else "\u00ab", "Collapse", self._toggle_sidebar, "_col_icon", "_col_txt"),
        ]:
            f = ctk.CTkFrame(self._sidebar, fg_color="transparent", cursor="hand2"); f.pack(fill="x", padx=8, pady=2)
            li = ctk.CTkLabel(f, text=icon, font=(F,14 if "col" in attr_i else 16), width=32, text_color=t["txt2"])
            li.pack(side="left", padx=(4,0))
            lt = ctk.CTkLabel(f, text=txt, font=(F,11), text_color=t["txt2"])
            if not self._collapsed: lt.pack(side="left", padx=(6,0))
            for w in (f, li, lt): w.bind("<Button-1>", lambda e, c=cmd: c())
            setattr(self, attr_i, li); setattr(self, attr_t, lt)

        self._status = StatusDot(self._sidebar, t); self._status.pack(padx=12, pady=(8,16), anchor="w")

    def _build_content(self, t):
        banner = ctk.CTkFrame(self._right, fg_color=t["bg2"], corner_radius=0, height=40)
        banner.pack(fill="x"); banner.pack_propagate(False); self._banner = banner
        self._banner_sep = ctk.CTkFrame(banner, fg_color=t["border"], height=1)
        self._banner_sep.pack(fill="x", side="bottom")
        self._hint_lbl = ctk.CTkLabel(banner, text="Hold  Ctrl + Win  to record   \u2022   Release to transcribe & paste",
                                      font=(F,10), text_color=t["dim"]); self._hint_lbl.pack(expand=True)

        self._tx_frame = ctk.CTkScrollableFrame(self._right, fg_color=t["bg"], scrollbar_button_color=t["border"], corner_radius=0)
        self._tx_frame.pack(fill="both", expand=True)
        self._tx_frame._parent_canvas.bind("<MouseWheel>", lambda e: self._tx_frame._parent_canvas.yview_scroll(int(-1*(e.delta/90)), "units"))

        self._empty = ctk.CTkFrame(self._tx_frame, fg_color="transparent"); self._empty.pack(fill="x", pady=80)
        ctk.CTkLabel(self._empty, text="\u223f", font=(F,56,"bold"), text_color=t["dim"]).pack()
        ctk.CTkLabel(self._empty, text="No transcriptions yet", font=(F,16,"bold"), text_color=t["dim"]).pack(pady=(16,4))
        ctk.CTkLabel(self._empty, text="Hold Ctrl+Win and start speaking.\nYour transcriptions will appear here.",
                     font=(F,11), text_color=t["dim"], justify="center").pack()

        self._dash_container = tk.Frame(self._right, bg=t["bg"])
        self._dash_canvas, self._dash_frame = self._mk_scroll(self._dash_container, t["bg"])

        self._bot = ctk.CTkFrame(self._right, fg_color=t["bg2"], corner_radius=0, height=32)
        self._bot.pack(fill="x", side="bottom"); self._bot.pack_propagate(False)
        self._bot_sep = ctk.CTkFrame(self._bot, fg_color=t["border"], height=1); self._bot_sep.pack(fill="x", side="top")
        self._bot_lbl = ctk.CTkLabel(self._bot, text=GROQ_MODEL, font=(F,9), text_color=t["dim"]); self._bot_lbl.pack(side="left", padx=16)
        self._count = ctk.CTkLabel(self._bot, text=f"{self._stats['total_txns']} transcriptions", font=(F,9), text_color=t["dim"])
        self._count.pack(side="right", padx=16)
        self._build_dashboard(t)

    # ---------------------------------------------------------------- Dashboard
    def _build_dashboard(self, t):
        d, s = self._dash_frame, self._stats

        hero = ctk.CTkFrame(d, fg_color="transparent"); hero.pack(fill="x", padx=12, pady=(16,8))
        hero.columnconfigure((0,1,2), weight=1)
        self._hero_widgets = []
        hero_tips = [
            "Total number of words you've dictated",
            "Total audio recording time processed",
            "Total number of voice transcriptions completed",
        ]
        for col, (icon, val, lbl) in enumerate([
            ("\u2328", f"{s['total_words']:,}", "Words Transcribed"),
            ("\u23f1", f"{s['total_secs']/60:.0f} min", "Audio Processed"),
            ("\u223f", str(s['total_txns']), "Transcriptions"),
        ]):
            c = ctk.CTkFrame(hero, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
            c.grid(row=0, column=col, padx=4, sticky="nsew")
            ctk.CTkLabel(c, text=icon, font=(F,22), text_color=ACCENT).pack(pady=(16,4))
            v = ctk.CTkLabel(c, text=val, font=(F,24,"bold"), text_color=t["txt"]); v.pack()
            ctk.CTkLabel(c, text=lbl, font=(F,9), text_color=t["txt2"]).pack(pady=(2,16))
            self._hero_widgets.append(v)
            Tooltip(c, hero_tips[col])

        fc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        fc.pack(fill="x", padx=16, pady=8)
        ff = ctk.CTkFrame(fc, fg_color="transparent"); ff.pack(fill="x", padx=16, pady=16)
        ctk.CTkLabel(ff, text=str(s["fillers"]), font=(F,32,"bold"), text_color=ACCENT).pack(side="left")
        fl = ctk.CTkFrame(ff, fg_color="transparent"); fl.pack(side="left", padx=(16,0))
        ctk.CTkLabel(fl, text="Filler Words Caught", font=(F,13), text_color=t["txt"]).pack(anchor="w")
        ctk.CTkLabel(fl, text="Ums, uhs, and waffle removed from your speech", font=(F,10), text_color=t["txt2"]).pack(anchor="w")
        Tooltip(fc, "Tracks filler words like 'um', 'uh', 'like', 'basically', etc. detected in your transcriptions")

        # Achievements
        BADGE_H = 200  # fixed height for all badges
        cur_section = None
        grid_frame = badge_list = None
        for aid, atype, target, icon, name, sub, tier in ACHIEVEMENTS:
            section = {"words":"Words Transcribed","txns":"Transcription Milestones"}.get(atype)
            if tier == "roast": section = "Roasts & Quirks"
            if section and section != cur_section:
                cur_section = section
                ctk.CTkLabel(d, text=section, font=(F,12,"bold"), text_color=t["txt2"], anchor="w").pack(fill="x", padx=20, pady=(20,8))
                grid_frame = ctk.CTkFrame(d, fg_color="transparent"); grid_frame.pack(fill="x", padx=16)
                grid_frame.columnconfigure((0,1), weight=1, uniform="badge"); badge_list = []

            row, col = len(badge_list)//2, len(badge_list)%2
            progress, count_text = self._ach_progress(atype, target)
            unlocked = aid in s.get("unlocked",[])

            b = ctk.CTkFrame(grid_frame, fg_color=t["card"], corner_radius=12, border_width=1,
                             border_color=TIER_COL[tier] if unlocked else t["border"], height=BADGE_H)
            b.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            b.pack_propagate(False)
            grid_frame.rowconfigure(row, minsize=BADGE_H)
            dim = t["txt"] if unlocked else t["dim"]
            ctk.CTkLabel(b, text=icon, font=(F,32), text_color=TIER_COL[tier] if unlocked else t["dim"]).pack(pady=(16,6))
            ctk.CTkLabel(b, text=name, font=(F,13,"bold"), text_color=dim).pack(pady=(0,2))
            ctk.CTkLabel(b, text=sub, font=(F,8), text_color=t["dim"]).pack(pady=(0,4))
            ctk.CTkLabel(b, text=tier.upper(), font=(F,7,"bold"), text_color="#fff",
                         fg_color=TIER_COL[tier], corner_radius=4, width=50, height=16).pack(pady=(4,0))
            pb = ctk.CTkProgressBar(b, width=100, height=6, corner_radius=3, progress_color=TEAL, fg_color=t["border"])
            pb.pack(pady=(8,4)); pb.set(min(progress, 1.0))
            ctk.CTkLabel(b, text=count_text, font=(F,9), text_color=t["dim"]).pack(pady=(0,16))
            hint = ACH_HINTS.get(atype, "").format(target=target)
            if unlocked: hint = f"\u2713 Unlocked!\n{hint}"
            Tooltip(b, hint)
            badge_list.append(b)

        days = 0
        try: days = (datetime.now() - datetime.fromisoformat(s["first_use"])).days
        except Exception: pass
        ctk.CTkLabel(d, text=f"You've been using WispGer Flow for {days} day{'s' if days!=1 else ''}",
                     font=(F,10), text_color=t["dim"]).pack(pady=16)

    def _ach_progress(self, atype, target):
        s = self._stats
        cur = {"words":s["total_words"],"txns":s["total_txns"],"like":s.get("like_count",0),
               "um":s.get("um_count",0),"dupes":s.get("dupes",0),"night":s.get("night_count",0),
               "speed":s.get("speed_count",0),"tiny":s.get("tiny_count",0),
               "long":s.get("long_count",0),"morning":s.get("morning_count",0)}.get(atype,0)
        capped = min(cur, target)
        progress = capped / target if target else 0
        if cur >= target:
            text = f"{target:,} / {target:,}  \u2713" if atype in ("words","txns") else "Unlocked!"
        else:
            text = f"{cur:,} / {target:,}" if atype in ("words","txns") else f"{cur} / {target}"
        return progress, text

    def _refresh_dashboard(self):
        s = self._stats
        if self._hero_widgets:
            self._hero_widgets[0].configure(text=f"{s['total_words']:,}")
            self._hero_widgets[1].configure(text=f"{s['total_secs']/60:.0f} min")
            self._hero_widgets[2].configure(text=str(s['total_txns']))

    # ---------------------------------------------------------------- Views
    def _switch_view(self, view):
        if view == self._view: return
        self._view = view; t = self._theme
        for vid, w in self._nav_btns.items():
            a = vid == view
            w["frame"].configure(fg_color=ACCENT if a else "transparent")
            w["icon"].configure(text_color="#fff" if a else t["txt2"])
            w["label"].configure(text_color="#fff" if a else t["txt2"], font=(F,12,"bold" if a else "normal"))
        if view == "transcriptions":
            self._dash_container.pack_forget()
            self._tx_frame.pack(fill="both", expand=True, before=self._bot)
        else:
            self._refresh_dashboard()
            self._tx_frame.pack_forget()
            self._dash_container.pack(fill="both", expand=True, before=self._bot)

    # ---------------------------------------------------------------- Sidebar
    def _toggle_sidebar(self):
        self._collapsed = not self._collapsed; _save_cfg({"sidebar_collapsed": self._collapsed})
        self._sidebar.configure(width=self.SB_C if self._collapsed else self.SB_W)
        self._col_icon.configure(text="\u00bb" if self._collapsed else "\u00ab")
        if self._collapsed:
            for w in (self._logo_txt, self._col_txt, self._theme_txt): w.pack_forget()
            for v in self._nav_btns.values(): v["label"].pack_forget()
        else:
            self._logo_txt.pack(side="left", padx=(8,0))
            self._col_txt.pack(side="left", padx=(6,0))
            self._theme_txt.pack(side="left", padx=(6,0))
            for v in self._nav_btns.values(): v["label"].pack(side="left", padx=(6,0))

    # ---------------------------------------------------------------- Theme
    def _toggle_theme(self):
        self._dark = not self._dark; self._theme = DARK if self._dark else LIGHT
        t = self._theme
        _save_cfg({"dark_mode": self._dark})
        self._theme_icon.configure(text="\u263e" if self._dark else "\u2600")

        # Main structure
        self.configure(fg_color=t["bg"])
        self._sidebar.configure(fg_color=t["sidebar"])
        self._right.configure(fg_color=t["bg"])
        self._banner.configure(fg_color=t["bg2"])
        self._banner_sep.configure(fg_color=t["border"])
        self._hint_lbl.configure(text_color=t["dim"])
        self._tx_frame.configure(fg_color=t["bg"])
        self._bot.configure(fg_color=t["bg2"])
        self._bot_sep.configure(fg_color=t["border"])
        self._bot_lbl.configure(text_color=t["dim"])
        self._count.configure(text_color=t["dim"])
        self._overlay.set_theme(t)

        # Sidebar
        self._logo_txt.configure(text_color=t["txt"])
        self._col_icon.configure(text_color=t["txt2"])
        self._col_txt.configure(text_color=t["txt2"])
        self._theme_icon.configure(text_color=t["txt2"])
        self._theme_txt.configure(text_color=t["txt2"])
        for vid, w in self._nav_btns.items():
            if vid != self._view:
                w["icon"].configure(text_color=t["txt2"])
                w["label"].configure(text_color=t["txt2"])

        # Transcription cards
        for card in self._cards:
            card.configure(fg_color=t["card"], border_color=t["border"])

        # Empty state
        if self._empty:
            for w in self._empty.winfo_children():
                if isinstance(w, ctk.CTkLabel): w.configure(text_color=t["dim"])

        # Dashboard — rebuild in background (native tk.Frame, fast)
        vis = self._view == "dashboard"
        if vis: self._dash_container.pack_forget()
        self._dash_container.destroy()
        self._dash_container = tk.Frame(self._right, bg=t["bg"])
        self._dash_canvas, self._dash_frame = self._mk_scroll(self._dash_container, t["bg"])
        self._build_dashboard(t)
        if vis: self._dash_container.pack(fill="both", expand=True, before=self._bot)

    # ---------------------------------------------------------------- Stats
    def _update_stats(self, text, dur):
        s, words = self._stats, text.split()
        wc = len(words); lw = [w.lower().strip(".,!?;:") for w in words]
        s["total_words"] += wc; s["total_txns"] += 1; s["total_secs"] += dur
        s["fillers"] += sum(1 for w in lw if w in FILLERS)
        s["like_count"] = s.get("like_count",0) + lw.count("like")
        s["um_count"] = s.get("um_count",0) + sum(1 for w in lw if w in ("um","uh","er","ah"))
        if wc == 1: s["tiny_count"] = s.get("tiny_count",0) + 1
        if wc >= 200: s["speed_count"] = s.get("speed_count",0) + 1
        if dur >= 60: s["long_count"] = s.get("long_count",0) + 1
        h = datetime.now().hour
        if h < 7: s["morning_count"] = s.get("morning_count",0) + 1
        if h < 5: s["night_count"] = s.get("night_count",0) + 1
        clean = text.strip().lower()
        if clean in self._last_texts: s["dupes"] = s.get("dupes",0) + 1
        self._last_texts.append(clean)
        if len(self._last_texts) > 20: self._last_texts.pop(0)

        unlocked, new = set(s.get("unlocked",[])), []
        for aid, atype, target, *rest in ACHIEVEMENTS:
            if aid not in unlocked and self._ach_progress(atype, target)[0] >= 1.0:
                unlocked.add(aid); new.append((aid, atype, target, *rest))
        s["unlocked"] = list(unlocked)
        _save_cfg({"stats": s})
        self._count.configure(text=f"{s['total_txns']} transcription{'s' if s['total_txns']!=1 else ''}")
        for a in new: self.after(500, lambda x=a: self._toast(x))

    def _toast(self, ach):
        icon, name = ach[3], ach[4]
        t = ctk.CTkFrame(self._right, fg_color=TEAL, corner_radius=12)
        t.place(relx=0.5, rely=0.95, anchor="s")
        ctk.CTkLabel(t, text=f"{icon}  Achievement Unlocked: {name}", font=(F,12,"bold"), text_color="#fff").pack(padx=20, pady=10)
        self.after(4000, t.destroy)

    # ---------------------------------------------------------------- Cards
    def _add_card(self, text, dur):
        if self._empty: self._empty.destroy(); self._empty = None
        card = TranscriptionCard(self._tx_frame, text, dur, datetime.now(), self._theme)
        if self._cards: card.pack(fill="x", padx=12, pady=(8,0), before=self._cards[0])
        else: card.pack(fill="x", padx=12, pady=(8,0))
        self._cards.insert(0, card)

    # ---------------------------------------------------------------- Hotkey
    def _press(self, key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): self._ctrl = True
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r): self._win = True
        if self._ctrl and self._win and not self._recording:
            self._recording, self._t0 = True, time.time()
            self._rec.start(); self.after(0, self._status.recording); self.after(0, self._overlay.show)

    def _release(self, key):
        both = self._ctrl and self._win
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): self._ctrl = False
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r): self._win = False
        if both and self._recording and not (self._ctrl and self._win):
            self._recording = False; dur = time.time()-self._t0 if self._t0 else 0.0
            pcm = self._rec.stop()
            self.after(0, self._overlay.hide); self.after(0, self._status.processing)
            if pcm: threading.Thread(target=self._transcribe, args=(pcm, dur), daemon=True).start()
            else: self.after(0, self._status.ready)

    def _transcribe(self, pcm, dur):
        if not self._lock.acquire(blocking=False): return
        try:
            resp = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("audio.wav", self._rec.to_wav(pcm), "audio/wav")},
                data={"model": GROQ_MODEL, "language": self._lang, "response_format": "json"}, timeout=15)
            if resp.status_code == 401: self.after(0, lambda: self._status.error("Invalid API key")); return
            resp.raise_for_status()
            text = resp.json().get("text","").strip()
            if not text: return
            print(f"[{dur:.1f}s] {text}")
            pyperclip.copy(text); time.sleep(0.05)
            self._kb.press(keyboard.Key.ctrl); self._kb.press("v")
            self._kb.release("v"); self._kb.release(keyboard.Key.ctrl)
            self.after(0, lambda: self._add_card(text, dur))
            self.after(0, lambda: self._update_stats(text, dur))
        except requests.ConnectionError: self.after(0, lambda: self._status.error("No connection"))
        except Exception as e: print(f"Error: {e}"); self.after(0, lambda: self._status.error("API error"))
        finally: self._lock.release(); self.after(0, self._status.ready)


if __name__ == "__main__":
    print("\n  WispGer Flow\n  Ctrl+Win to record. Release to paste.\n")
    WispGerFlow().mainloop()
