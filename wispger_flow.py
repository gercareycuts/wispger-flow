#!/usr/bin/env python3
"""WispGer Flow — Voice to text, refined. Hold Ctrl+Win to record, release to paste."""

import array, io, json, math, os, re, struct, subprocess, sys, threading, time, tkinter as tk, wave
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import pyperclip, requests, sounddevice as sd
from pynput import keyboard

# -- Platform --
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if IS_WIN:
    import ctypes

# -- Paths & Font --
APP_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
if IS_WIN:
    CFG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "WispGer"
elif IS_MAC:
    CFG_DIR = Path.home() / "Library" / "Application Support" / "WispGer"
else:
    CFG_DIR = Path.home() / ".config" / "WispGer"
CFG_FILE = CFG_DIR / "config.json"

# Load Poppins font (platform-specific)
if IS_WIN:
    for ttf in (APP_DIR / "fonts").glob("*.ttf"):
        ctypes.windll.gdi32.AddFontResourceExW(str(ttf), 0x10, 0)
    F = "Poppins"
elif IS_MAC:
    # macOS loads .ttf from the app bundle automatically via Tk; fall back to system font
    F = "Poppins" if (APP_DIR / "fonts" / "Poppins-Regular.ttf").exists() else "SF Pro"
else:
    F = "Poppins"

# -- Theme --
DARK = {"bg": "#0f0f1a", "bg2": "#161625", "card": "#1c1c30", "txt": "#e8e8f0",
        "txt2": "#8888a8", "dim": "#555570", "border": "#2a2a45", "overlay": "#333338", "sidebar": "#12121f"}
LIGHT = {"bg": "#f0f0f5", "bg2": "#e4e4ec", "card": "#ffffff", "txt": "#1a1a2e",
         "txt2": "#555570", "dim": "#8888a8", "border": "#d0d0dd", "overlay": "#e0e0e8", "sidebar": "#dcdce8"}
ACCENT, ACCENTH, TEAL, GREEN = "#e67e22", "#f39c12", "#00b894", "#2ecc71"
RED, REDDIM, AMBER = "#ff4757", "#cc3040", "#ffa502"

# -- DPI & Screen --
if IS_WIN:
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    def _screen_size(): return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
else:
    def _screen_size():
        # On macOS/Linux, use a temporary Tk to get screen size (cached after first call)
        if not hasattr(_screen_size, "_c"):
            try:
                r = tk.Tk(); r.withdraw()
                _screen_size._c = (r.winfo_screenwidth(), r.winfo_screenheight()); r.destroy()
            except Exception: _screen_size._c = (1920, 1080)
        return _screen_size._c

# -- API --
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
WHISPER_PROMPT = "Hello, how are you? I'm doing well. Yes, that sounds great! Let me think about it. Okay, I'll do that."

# -- Whisper hallucination filter (common outputs on silence) --
_HALLUCINATIONS = {
    "thank you", "thanks", "thank you.", "thanks.", "thank you for watching",
    "thanks for watching", "thanks for watching.", "thank you for watching.",
    "subscribe", "like and subscribe", "please subscribe",
    "bye", "bye.", "goodbye", "goodbye.", "you", "you.",
    "the end", "the end.", "",
}

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
    ("t50","txns",50,"\U0001f3af","Getting Started","Welcome aboard","bronze"),
    ("t100","txns",100,"\U0001f4af","Centurion","A hundred and counting","silver"),
    ("t500","txns",500,"\u26a1","Power User","Keyboard? Never heard of it","gold"),
    ("t1000","txns",1000,"\U0001f916","Voice Addict","Your keyboard is collecting dust","diamond"),
    ("like100","like",100,"\U0001f644","Like, Totally","Are you in high school?","roast"),
    ("um200","um",200,"\U0001f914","The Thinker","Uhhhhhhhhhhhh...","roast"),
    ("dup15","dupes",15,"\U0001f99c","Broken Record","You said the same thing 15x","roast"),
    ("night10","night",10,"\U0001f319","Night Owl","Go to bed already","roast"),
    ("speed100","speed",1,"\U0001f407","Speed Demon","Slow down, auctioneer","roast"),
    ("tiny50","tiny",50,"\U0001f90f","One Word Wonder","Could've just typed it","roast"),
    ("long30","long",1,"\U0001f4d6","Monologue King","Sir, this is a Wendy's","roast"),
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
    "speed": "Transcribe 100+ words in a single recording",
    "tiny": "Transcribe just 1 word {target} times",
    "long": "Record for 30+ seconds in a single session",
    "morning": "Transcribe before 7am {target} times",
}

# -- Text cleanup --
_VOWELS = set("aeiouAEIOU")
_CONSONANT_SOUND = {"one","once","uni","unit","united","unique","union","university",
                    "uniform","unicorn","universal","use","used","useful","user",
                    "usual","usually","europe","european","ufo"}
_SILENT_H_SKIP = {"have","had","has","he","her","him","his","how","here"}

# Words that typically start a new sentence (used for punctuation insertion)
_SENTENCE_STARTERS = {"So","But","However","Also","Then","Now","Well",
                      "Actually","Anyway","Besides","Furthermore","Meanwhile",
                      "Nevertheless","Otherwise","Therefore","Instead","Finally",
                      "Basically","Honestly","Look","Listen","Hey","Okay","OK","Yeah","Yes","No"}
# Words that signal a question
_QUESTION_STARTERS = {"who","what","where","when","why","how","is","are","was","were",
                      "do","does","did","can","could","would","should","will","shall",
                      "have","has","had","am","isn't","aren't","wasn't","weren't",
                      "don't","doesn't","didn't","can't","couldn't","wouldn't","shouldn't"}

def _fix_article(m):
    article, space, word = m.group(1), m.group(2), m.group(3)
    wl = word.lower()
    vowel = wl[0] in _VOWELS if wl else False
    if any(wl.startswith(x) for x in _CONSONANT_SOUND): vowel = False
    if wl.startswith("h") and len(wl)>1 and wl[1] in _VOWELS and wl not in _SILENT_H_SKIP: vowel = True
    correct = "an" if vowel else "a"
    if article[0].isupper(): correct = correct.capitalize()
    return correct + space + word

def _add_punctuation(text):
    """Insert periods and commas where Whisper omitted them."""
    words = text.split()
    if len(words) < 2:
        # Single word or empty — just add period if missing
        if text and text[-1].isalpha(): text += "."
        return text

    result = [words[0]]
    since_punct = 1  # words since last punctuation

    for i in range(1, len(words)):
        prev = result[-1]
        curr = words[i]
        prev_ended = prev[-1] in ".!?," if prev else False
        if prev_ended: since_punct = 0

        # Insert period before sentence-starting words, but only if we're 3+ words
        # into a clause (avoids breaking short phrases like "and So on")
        if not prev_ended and curr in _SENTENCE_STARTERS and since_punct >= 3:
            result[-1] = prev + "."
            since_punct = 0

        # Insert comma before subordinating conjunctions in longer clauses
        elif not prev_ended and curr.lower() in ("because","although","since","unless","whereas") and since_punct >= 3:
            result[-1] = prev + ","

        result.append(curr)
        since_punct += 1

    text = " ".join(result)

    # Add period at end if missing
    if text and text[-1].isalpha():
        text += "."

    # Detect questions: if first word is a question word, swap trailing period for ?
    first = text.split()[0].lower().rstrip(".,!?") if text else ""
    if first in _QUESTION_STARTERS and text.endswith("."):
        text = text[:-1] + "?"

    return text

def clean_pipeline(text):
    # Remove repeated consecutive phrases (2-5 word ngrams)
    for n in range(5, 1, -1):
        words = text.split()
        i = 0
        while i + 2*n <= len(words):
            if [w.lower() for w in words[i:i+n]] == [w.lower() for w in words[i+n:i+2*n]]:
                words = words[:i+n] + words[i+2*n:]
            else: i += 1
        text = " ".join(words)
    # Insert punctuation where missing
    text = _add_punctuation(text)
    # Capitalise after sentence-ending punctuation
    text = re.sub(r'([.!?])\s+([a-z])', lambda m: m.group(1)+" "+m.group(2).upper(), text)
    if text and text[0].islower(): text = text[0].upper() + text[1:]
    # Correct a/an
    text = re.sub(r'\b(A|a|An|an)\b(\s+)(\w+)', _fix_article, text)
    # Space after punctuation if missing
    text = re.sub(r'([.!?])([A-Za-z])', r'\1 \2', text)
    # Collapse double spaces
    return re.sub(r'  +', ' ', text).strip()

def prep_for_paste(text):
    if not text or text[0] in ".!?,;:'\"-": return text
    return " " + text


# -- Config --
def _load_cfg():
    try: return json.loads(CFG_FILE.read_text()) if CFG_FILE.exists() else {}
    except Exception: return {}

def _save_cfg(data):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(); cfg.update(data)
    CFG_FILE.write_text(json.dumps(cfg))

# -- Common English words (filtered out of voice profile) --
COMMON_WORDS = frozenset(
    "a about after again all also am an and any are as at back be because been before being below between both but by "
    "came can come could day did do does done down each even few first for from get go going good got great had has have "
    "he her here him his how i if in into is it its just know last let like long look made make many may me might more "
    "most much must my new no nor not now of off on one only or other our out over own part per put quite really right "
    "said same say see she should show side since so some something still such take tell than that the their them then "
    "there these they thing think this those through time to too two under up upon us use used using very want was way "
    "we well were what when where which while who why will with without word work would year yes yet you your "
    "able about above actually after again against ago ahead almost already although always among another "
    "around away bad before began begin behind believe best better big bit bring brought called certain "
    "change children city close company country course cut different doing door early end enough ever every "
    "example face fact family far feel felt find found four full gave give given goes gone great group hand "
    "head hear help high home house however important keep kind knew large last later least left less life "
    "line little live long looked making man men might mind money morning move mr mrs never next night nothing "
    "number often old once open order place play point possible power probably problem quite ran read real "
    "room run saw school second set several shall short small started state still stop story sure system "
    "taken talk tell thought three together told took top turn under until upon water whole world write young".split()
)

def _default_voice_profile():
    return {"vocab":{},"phrases":{},"corrections":{},"style_notes":"","prompt_override":""}

def _apply_corrections(text, corrections):
    """Apply user-defined word corrections after clean_pipeline."""
    for wrong, right in corrections.items():
        text = re.sub(r'\b' + re.escape(wrong) + r'\b', right, text, flags=re.IGNORECASE)
    return text

def _default_stats():
    return {"total_words":0,"total_txns":0,"total_secs":0.0,"fillers":0,
            "filler_breakdown":{},
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
    def _pos(self):
        sw, sh = _screen_size()
        self.geometry(f"{self.W}x{self.H}+{(sw-self.W)//2}+{sh-self.H-50}")

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
        self._vp = {**_default_voice_profile(), **cfg.get("voice_profile",{})}
        self._rec, self._kb = AudioRecorder(), keyboard.Controller()
        self._recording, self._ctrl, self._win, self._t0 = False, False, False, None
        self._key_lock = threading.Lock()
        self._cards, self._lock, self._view = [], threading.Lock(), "transcriptions"

        self._build_ui()
        self._init_tones()
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
        c.bind("<Enter>", lambda e: c.bind_all("<MouseWheel>", scroll, "+"))
        c.bind("<Leave>", lambda e: c.unbind_all("<MouseWheel>"))
        c.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        return inner

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
        for vid, icon, label in [("transcriptions","\u2302","Home"),("dashboard","\u2197","Statistics"),("voice","\u266b","My Voice")]:
            f = ctk.CTkFrame(self._nav_frame, fg_color="transparent", cursor="hand2"); f.pack(fill="x", pady=3)
            active = vid == self._view
            fg = "#fff" if active else t["txt2"]
            li = ctk.CTkLabel(f, text=icon, font=(F,20), width=36, text_color=fg); li.pack(side="left", padx=(6,0))
            lt = ctk.CTkLabel(f, text=label, font=(F,14,"bold" if active else "normal"), text_color=fg)
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

    def _days_active(self):
        try: return (datetime.now() - datetime.fromisoformat(self._stats["first_use"])).days
        except Exception: return 0

    def _wpm(self):
        s = self._stats
        mins = s["total_secs"] / 60
        return int(s["total_words"] / mins) if mins > 0 else 0

    def _refresh_banner(self):
        s = self._stats
        self._ban_days.configure(text=f"{self._days_active()}d")
        self._ban_words.configure(text=f"{s['total_words']:,}")
        self._ban_wpm.configure(text=f"{self._wpm()}")

    def _build_content(self, t):
        banner = ctk.CTkFrame(self._right, fg_color=t["bg2"], corner_radius=0, height=62)
        banner.pack(fill="x"); banner.pack_propagate(False); self._banner = banner
        self._banner_sep = ctk.CTkFrame(banner, fg_color=t["border"], height=1)
        self._banner_sep.pack(fill="x", side="bottom")

        # Left: hotkey hint
        self._hint_lbl = ctk.CTkLabel(banner, text="Ctrl+Win to record", font=(F,10), text_color=t["dim"])
        self._hint_lbl.pack(side="left", padx=(16,0))

        # Right: quick stats with emoji icons
        stats_f = ctk.CTkFrame(banner, fg_color="transparent")
        stats_f.pack(side="right", padx=16)
        s = self._stats

        from PIL import Image, ImageTk
        self._emoji_imgs = []  # prevent garbage collection
        for img_name, val, label, attr in [
            ("fire", f"{self._days_active()}d", "Active", "_ban_days"),
            ("rocket", f"{s['total_words']:,}", "Words", "_ban_words"),
            ("trophy", f"{self._wpm()}", "WPM", "_ban_wpm"),
        ]:
            img = Image.open(APP_DIR / "fonts" / f"{img_name}.png")
            photo = ImageTk.PhotoImage(img)
            self._emoji_imgs.append(photo)
            tk.Label(stats_f, image=photo, bg=t["bg2"], bd=0).pack(side="left", padx=(18,4))
            lbl = ctk.CTkLabel(stats_f, text=val, font=(F,12,"bold"), text_color=t["txt2"])
            lbl.pack(side="left", padx=(0,3))
            ctk.CTkLabel(stats_f, text=label, font=(F,9), text_color=t["dim"]).pack(side="left")
            setattr(self, attr, lbl)

        self._tx_frame = ctk.CTkScrollableFrame(self._right, fg_color=t["bg"], scrollbar_button_color=t["border"], corner_radius=0)
        self._tx_frame.pack(fill="both", expand=True)
        self._tx_frame._parent_canvas.bind("<MouseWheel>", lambda e: self._tx_frame._parent_canvas.yview_scroll(int(-1*(e.delta/90)), "units"))

        self._empty = ctk.CTkFrame(self._tx_frame, fg_color="transparent"); self._empty.pack(fill="x", pady=80)
        ctk.CTkLabel(self._empty, text="\u223f", font=(F,56,"bold"), text_color=t["dim"]).pack()
        ctk.CTkLabel(self._empty, text="No transcriptions yet", font=(F,16,"bold"), text_color=t["dim"]).pack(pady=(16,4))
        ctk.CTkLabel(self._empty, text="Hold Ctrl+Win and start speaking.\nYour transcriptions will appear here.",
                     font=(F,11), text_color=t["dim"], justify="center").pack()

        self._dash_container = tk.Frame(self._right, bg=t["bg"])
        self._dash_frame = self._mk_scroll(self._dash_container, t["bg"])

        self._voice_container = tk.Frame(self._right, bg=t["bg"])
        self._voice_frame = self._mk_scroll(self._voice_container, t["bg"])

        self._bot = ctk.CTkFrame(self._right, fg_color=t["bg2"], corner_radius=0, height=32)
        self._bot.pack(fill="x", side="bottom"); self._bot.pack_propagate(False)
        self._bot_sep = ctk.CTkFrame(self._bot, fg_color=t["border"], height=1); self._bot_sep.pack(fill="x", side="top")
        self._bot_lbl = ctk.CTkLabel(self._bot, text=GROQ_MODEL, font=(F,9), text_color=t["dim"]); self._bot_lbl.pack(side="left", padx=16)
        self._count = ctk.CTkLabel(self._bot, text=f"{self._stats['total_txns']} transcriptions", font=(F,9), text_color=t["dim"])
        self._count.pack(side="right", padx=16)
        self._build_dashboard(t)
        self._build_voice_tab(t)

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

        # Filler words card — single card, icon left, count right
        fc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        fc.pack(fill="x", padx=16, pady=(0,8))
        ff = ctk.CTkFrame(fc, fg_color="transparent"); ff.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(ff, text="\U0001f6ab", font=(F,22), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(ff, text="Filler Words Caught", font=(F,12), text_color=t["txt"]).pack(side="left", padx=(10,0))
        ctk.CTkLabel(ff, text=str(s["fillers"]), font=(F,20,"bold"), text_color=t["txt"]).pack(side="right")
        bd = s.get("filler_breakdown", {})
        if bd:
            top = sorted(bd.items(), key=lambda x: -x[1])[:8]
            breakdown = " \u2022 ".join(f'"{w}" \u00d7{c}' for w, c in top)
            tip = f"Top fillers: {breakdown}"
        else:
            tip = "No filler words caught yet"
        Tooltip(fc, tip)

        # Achievements
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
                             border_color=TIER_COL[tier] if unlocked else t["border"])
            b.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            dim = t["txt"] if unlocked else t["dim"]
            # Tier badge top-right
            ctk.CTkLabel(b, text=tier.upper(), font=(F,7,"bold"), text_color="#fff",
                         fg_color=TIER_COL[tier], corner_radius=4, width=50, height=16).pack(anchor="e", padx=10, pady=(8,0))
            ctk.CTkLabel(b, text=icon, font=(F,38), text_color=TIER_COL[tier] if unlocked else t["dim"]).pack(pady=(2,2))
            ctk.CTkLabel(b, text=name, font=(F,15,"bold"), text_color=dim).pack()
            ctk.CTkLabel(b, text=sub, font=(F,8), text_color=t["dim"]).pack()
            pb = ctk.CTkProgressBar(b, height=10, corner_radius=5, progress_color=TEAL, fg_color=t["border"])
            pb.pack(fill="x", padx=16, pady=(6,3)); pb.set(min(progress, 1.0))
            ctk.CTkLabel(b, text=count_text, font=(F,9), text_color=t["dim"]).pack(pady=(0,10))
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

    # ---------------------------------------------------------------- My Voice Tab
    def _build_voice_tab(self, t):
        d = self._voice_frame
        vp = self._vp

        # Profile strength
        txns = self._stats.get("total_txns", 0)
        strength = min(txns / 100, 1.0)
        strength_text = f"Profile trained ({txns}+ transcriptions)" if strength >= 1.0 else f"Learning... {txns} transcriptions"

        sc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        sc.pack(fill="x", padx=16, pady=(16,8))
        sf = ctk.CTkFrame(sc, fg_color="transparent"); sf.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(sf, text="\U0001f9e0", font=(F,20)).pack(side="left")
        ctk.CTkLabel(sf, text=strength_text, font=(F,12), text_color=t["txt"]).pack(side="left", padx=(10,0))
        pb = ctk.CTkProgressBar(sc, height=8, corner_radius=4, progress_color=TEAL, fg_color=t["border"])
        pb.pack(fill="x", padx=16, pady=(0,14)); pb.set(strength)

        # Top Vocabulary
        vocab = vp.get("vocab", {})
        ctk.CTkLabel(d, text="Top Vocabulary", font=(F,13,"bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(16,6))
        vc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        vc.pack(fill="x", padx=16, pady=(0,8))
        vf = ctk.CTkFrame(vc, fg_color="transparent"); vf.pack(fill="x", padx=16, pady=12)
        if vocab:
            top_vocab = sorted(vocab.items(), key=lambda x: -x[1])[:20]
            for w, c in top_vocab:
                chip = ctk.CTkFrame(vf, fg_color=t["border"], corner_radius=6)
                chip.pack(side="left", padx=2, pady=2)
                ctk.CTkLabel(chip, text=f"{w} ({c})", font=(F,9), text_color=t["txt"], padx=8, pady=2).pack()
        else:
            ctk.CTkLabel(vf, text="\U0001f4a1", font=(F,16)).pack(side="left")
            ef = ctk.CTkFrame(vf, fg_color="transparent"); ef.pack(side="left", padx=(8,0))
            ctk.CTkLabel(ef, text="Your unique words will appear here", font=(F,10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(ef, text="e.g.  deployment (12)  \u2022  kubernetes (8)  \u2022  refactor (5)", font=(F,9), text_color=t["dim"]).pack(anchor="w")

        # Common Phrases
        phrases = vp.get("phrases", {})
        ctk.CTkLabel(d, text="Common Phrases", font=(F,13,"bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12,6))
        pc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        pc.pack(fill="x", padx=16, pady=(0,8))
        if phrases:
            top_phrases = sorted(phrases.items(), key=lambda x: -x[1])[:10]
            for p, c in top_phrases:
                pf = ctk.CTkFrame(pc, fg_color="transparent"); pf.pack(fill="x", padx=16, pady=3)
                ctk.CTkLabel(pf, text=f'"{p}"', font=(F,10), text_color=t["txt"]).pack(side="left")
                ctk.CTkLabel(pf, text=f"\u00d7{c}", font=(F,9,"bold"), text_color=t["txt2"]).pack(side="right")
        else:
            ef = ctk.CTkFrame(pc, fg_color="transparent"); ef.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(ef, text="\U0001f50d", font=(F,16)).pack(side="left")
            pef = ctk.CTkFrame(ef, fg_color="transparent"); pef.pack(side="left", padx=(8,0))
            ctk.CTkLabel(pef, text="Repeated phrases will be detected automatically", font=(F,10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(pef, text='e.g.  "at the end of the day" \u00d78  \u2022  "in terms of" \u00d75', font=(F,9), text_color=t["dim"]).pack(anchor="w")

        # Corrections
        corrections = vp.get("corrections", {})
        ctk.CTkLabel(d, text="Corrections", font=(F,13,"bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12,6))
        cc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        cc.pack(fill="x", padx=16, pady=(0,8))
        if corrections:
            for wrong, right in corrections.items():
                cf = ctk.CTkFrame(cc, fg_color="transparent"); cf.pack(fill="x", padx=16, pady=3)
                ctk.CTkLabel(cf, text=wrong, font=(F,10), text_color=RED).pack(side="left")
                ctk.CTkLabel(cf, text="\u2192", font=(F,10), text_color=t["dim"]).pack(side="left", padx=8)
                ctk.CTkLabel(cf, text=right, font=(F,10,"bold"), text_color=TEAL).pack(side="left")
                def _del(w=wrong):
                    del self._vp["corrections"][w]; _save_cfg({"voice_profile": self._vp})
                    self._rebuild_voice_tab()
                ctk.CTkButton(cf, text="\u2715", width=24, height=24, corner_radius=4, font=(F,10),
                              fg_color="transparent", hover_color=t["border"], text_color=t["dim"],
                              command=_del).pack(side="right")
        else:
            ef = ctk.CTkFrame(cc, fg_color="transparent"); ef.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(ef, text="\u270f", font=(F,16)).pack(side="left")
            cef = ctk.CTkFrame(ef, fg_color="transparent"); cef.pack(side="left", padx=(8,0))
            ctk.CTkLabel(cef, text="Teach Whisper your terminology", font=(F,10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(cef, text='e.g.  "pie test" \u2192 pytest  \u2022  "cube control" \u2192 kubectl', font=(F,9), text_color=t["dim"]).pack(anchor="w")

        # Add correction button
        add_f = ctk.CTkFrame(cc, fg_color="transparent"); add_f.pack(fill="x", padx=16, pady=(4,12))
        self._cor_wrong = ctk.CTkEntry(add_f, width=120, height=28, font=(F,10), placeholder_text="Whisper hears...",
                                       fg_color=t["bg"], border_color=t["border"], text_color=t["txt"])
        self._cor_wrong.pack(side="left")
        ctk.CTkLabel(add_f, text="\u2192", font=(F,10), text_color=t["dim"]).pack(side="left", padx=6)
        self._cor_right = ctk.CTkEntry(add_f, width=120, height=28, font=(F,10), placeholder_text="You mean...",
                                       fg_color=t["bg"], border_color=t["border"], text_color=t["txt"])
        self._cor_right.pack(side="left")
        ctk.CTkButton(add_f, text="Add", width=50, height=28, corner_radius=6, font=(F,10,"bold"),
                      fg_color=ACCENT, hover_color=ACCENTH, command=self._add_correction).pack(side="left", padx=(8,0))

        # Style Notes
        ctk.CTkLabel(d, text="Style Notes", font=(F,13,"bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12,6))
        self._style_box = ctk.CTkTextbox(d, height=60, font=(F,10), fg_color=t["card"], border_color=t["border"],
                                         text_color=t["txt"], corner_radius=12, border_width=1)
        self._style_box.pack(fill="x", padx=16, pady=(0,8))
        if vp.get("style_notes"): self._style_box.insert("1.0", vp["style_notes"])
        ctk.CTkButton(d, text="Save Notes", width=100, height=28, corner_radius=6, font=(F,10,"bold"),
                      fg_color=ACCENT, hover_color=ACCENTH, command=self._save_style_notes).pack(anchor="e", padx=16, pady=(0,8))

        # Prompt Preview
        ctk.CTkLabel(d, text="Prompt Preview", font=(F,13,"bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12,6))
        prompt = self._build_whisper_prompt()
        word_count = len(prompt.split())
        prev_c = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        prev_c.pack(fill="x", padx=16, pady=(0,8))
        ctk.CTkLabel(prev_c, text=prompt if prompt else "Default prompt (no profile data yet)", font=(F,9),
                     text_color=t["txt2"], wraplength=400, justify="left", anchor="w").pack(fill="x", padx=16, pady=(12,4))
        ctk.CTkLabel(prev_c, text=f"~{word_count} / 150 words", font=(F,8), text_color=t["dim"]).pack(anchor="e", padx=16, pady=(0,10))

        # Reset button
        ctk.CTkButton(d, text="Reset Voice Profile", width=140, height=32, corner_radius=8, font=(F,10),
                      fg_color=RED, hover_color=REDDIM, text_color="#fff",
                      command=self._reset_voice_profile).pack(pady=16)

    def _add_correction(self):
        w = self._cor_wrong.get().strip()
        r = self._cor_right.get().strip()
        if w and r:
            self._vp.setdefault("corrections", {})[w.lower()] = r
            _save_cfg({"voice_profile": self._vp})
            self._rebuild_voice_tab()

    def _save_style_notes(self):
        self._vp["style_notes"] = self._style_box.get("1.0", "end").strip()
        _save_cfg({"voice_profile": self._vp})

    def _reset_voice_profile(self):
        self._vp = _default_voice_profile()
        _save_cfg({"voice_profile": self._vp})
        self._rebuild_voice_tab()

    def _rebuild_voice_tab(self):
        if hasattr(self, '_voice_container'):
            vis = self._view == "voice"
            if vis: self._voice_container.pack_forget()
            # Unbind global mousewheel before destroying to prevent stale canvas references
            try: self.unbind_all("<MouseWheel>")
            except Exception: pass
            self._voice_container.destroy()
            self._voice_container = tk.Frame(self._right, bg=self._theme["bg"])
            self._voice_frame = self._mk_scroll(self._voice_container, self._theme["bg"])
            self._build_voice_tab(self._theme)
            if vis: self._voice_container.pack(fill="both", expand=True, before=self._bot)

    # ---------------------------------------------------------------- Views
    def _switch_view(self, view):
        if view == self._view: return
        self._view = view; t = self._theme
        for vid, w in self._nav_btns.items():
            a = vid == view
            w["frame"].configure(fg_color=ACCENT if a else "transparent")
            w["icon"].configure(text_color="#fff" if a else t["txt2"])
            w["label"].configure(text_color="#fff" if a else t["txt2"], font=(F,14,"bold" if a else "normal"))
        # Hide all content frames
        for f in (self._tx_frame, self._dash_container, self._voice_container): f.pack_forget()
        # Show the selected one
        if view == "transcriptions":
            self._tx_frame.pack(fill="both", expand=True, before=self._bot)
        elif view == "dashboard":
            self._refresh_dashboard()
            self._dash_container.pack(fill="both", expand=True, before=self._bot)
        elif view == "voice":
            self._rebuild_voice_tab()
            self._voice_container.pack(fill="both", expand=True, before=self._bot)

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
        self._ban_days.configure(text_color=t["txt2"])
        self._ban_words.configure(text_color=t["txt2"])
        self._ban_wpm.configure(text_color=t["txt2"])
        # Update emoji image label backgrounds
        for w in self._banner.winfo_children():
            for ch in (w.winfo_children() if hasattr(w, 'winfo_children') else []):
                if isinstance(ch, tk.Label) and ch.cget("image"): ch.configure(bg=t["bg2"])
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

        # Transcription cards — update card and all text labels inside
        for card in self._cards:
            card.configure(fg_color=t["card"], border_color=t["border"])
            for w in card.winfo_children():
                if isinstance(w, ctk.CTkFrame):
                    for ch in w.winfo_children():
                        if isinstance(ch, ctk.CTkLabel):
                            tc = ch.cget("text_color")
                            if tc not in (ACCENT, "#fff", "#ffffff") and ch.cget("fg_color") != TEAL:
                                ch.configure(text_color=t["txt2"])
                elif isinstance(w, ctk.CTkLabel):
                    tc = w.cget("text_color")
                    if tc not in (ACCENT, "#fff", "#ffffff") and w.cget("fg_color") != TEAL:
                        w.configure(text_color=t["txt"])

        # Empty state
        if self._empty:
            for w in self._empty.winfo_children():
                if isinstance(w, ctk.CTkLabel): w.configure(text_color=t["dim"])

        # Rebuild dashboard and voice tab with new theme
        try: self.unbind_all("<MouseWheel>")
        except Exception: pass
        for attr, builder in [("_dash_container", "_build_dashboard"), ("_voice_container", "_build_voice_tab")]:
            container = getattr(self, attr)
            vis = self._view == {"_dash_container":"dashboard","_voice_container":"voice"}[attr]
            if vis: container.pack_forget()
            container.destroy()
            new_container = tk.Frame(self._right, bg=t["bg"])
            setattr(self, attr, new_container)
            frame_attr = attr.replace("container", "frame")
            setattr(self, frame_attr, self._mk_scroll(new_container, t["bg"]))
            getattr(self, builder)(t)
            if vis: new_container.pack(fill="both", expand=True, before=self._bot)

    # ---------------------------------------------------------------- Stats
    def _update_stats(self, text, dur):
        s, words = self._stats, text.split()
        wc = len(words); lw = [w.lower().strip(".,!?;:") for w in words]
        s["total_words"] += wc; s["total_txns"] += 1; s["total_secs"] += dur
        bd = s.get("filler_breakdown", {})
        for w in lw:
            if w in FILLERS:
                s["fillers"] += 1
                bd[w] = bd.get(w, 0) + 1
        s["filler_breakdown"] = bd
        s["like_count"] = s.get("like_count",0) + lw.count("like")
        s["um_count"] = s.get("um_count",0) + sum(1 for w in lw if w in ("um","uh","er","ah"))
        if wc == 1: s["tiny_count"] = s.get("tiny_count",0) + 1
        if wc >= 100: s["speed_count"] = s.get("speed_count",0) + 1
        if dur >= 30: s["long_count"] = s.get("long_count",0) + 1
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
        self._refresh_banner()
        for a in new: self.after(500, lambda x=a: self._toast(x))

    def _toast(self, ach):
        icon, name = ach[3], ach[4]
        t = ctk.CTkFrame(self._right, fg_color=TEAL, corner_radius=12)
        t.place(relx=0.5, rely=0.95, anchor="s")
        ctk.CTkLabel(t, text=f"{icon}  Achievement Unlocked: {name}", font=(F,12,"bold"), text_color="#fff").pack(padx=20, pady=10)
        self.after(4000, t.destroy)

    # ---------------------------------------------------------------- Voice Profile
    def _update_voice_profile(self, text):
        vp = self._vp
        words = [w.lower().strip(".,!?;:\"'") for w in text.split() if len(w) > 2]

        # Update vocab — only uncommon words
        vocab = vp.get("vocab", {})
        for w in words:
            if w not in COMMON_WORDS and w not in FILLERS:
                vocab[w] = vocab.get(w, 0) + 1
        # Cap at 200 entries
        if len(vocab) > 200:
            vocab = dict(sorted(vocab.items(), key=lambda x: -x[1])[:200])
        vp["vocab"] = vocab

        # Update phrases — bigrams and trigrams
        phrases = vp.get("phrases", {})
        for n in (2, 3):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i+n])
                if not any(w in COMMON_WORDS for w in words[i:i+n]):
                    phrases[phrase] = phrases.get(phrase, 0) + 1
        # Keep only phrases seen 2+ times, cap at 100
        phrases = {k: v for k, v in phrases.items() if v >= 2}
        if len(phrases) > 100:
            phrases = dict(sorted(phrases.items(), key=lambda x: -x[1])[:100])
        vp["phrases"] = phrases

        # Decay every 50 transcriptions
        s = self._stats
        if s["total_txns"] > 0 and s["total_txns"] % 50 == 0:
            for d in (vp["vocab"], vp["phrases"]):
                for k in list(d):
                    d[k] = round(d[k] * 0.8, 1)
                    if d[k] < 1: del d[k]

        _save_cfg({"voice_profile": vp})

    def _build_whisper_prompt(self):
        vp = self._vp
        # Full override if set
        if vp.get("prompt_override", "").strip():
            return vp["prompt_override"][:600]

        parts = []
        # Style notes
        notes = vp.get("style_notes", "").strip()
        if notes: parts.append(notes[:200])

        # Top correction targets (just the correct forms as vocabulary hints)
        corrections = vp.get("corrections", {})
        if corrections:
            parts.append(", ".join(corrections.values())[:100])

        # Top vocab words
        vocab = vp.get("vocab", {})
        if vocab:
            top = sorted(vocab.items(), key=lambda x: -x[1])[:25]
            parts.append(", ".join(w for w, _ in top))

        # Top phrases as natural fragments
        phrases = vp.get("phrases", {})
        if phrases:
            top = sorted(phrases.items(), key=lambda x: -x[1])[:8]
            parts.append(". ".join(p for p, _ in top))

        prompt = ". ".join(parts) if parts else WHISPER_PROMPT
        # Cap at ~150 words
        words = prompt.split()
        if len(words) > 150: prompt = " ".join(words[:150])
        return prompt

    # ---------------------------------------------------------------- Cards
    def _add_card(self, text, dur):
        if self._empty: self._empty.destroy(); self._empty = None
        card = TranscriptionCard(self._tx_frame, text, dur, datetime.now(), self._theme)
        if self._cards: card.pack(fill="x", padx=12, pady=(8,0), before=self._cards[0])
        else: card.pack(fill="x", padx=12, pady=(8,0))
        self._cards.insert(0, card)

    # ---------------------------------------------------------------- Hotkey
    MIN_RECORDING_SECS = 0.3

    @staticmethod
    def _make_tone(freq, ms, vol=0.12):
        """Generate a sine wave WAV file in temp dir. Returns file path."""
        import tempfile
        sr = 22050
        n = int(sr * ms / 1000)
        fade = min(n // 4, 200)
        pcm = []
        for i in range(n):
            s = math.sin(2 * math.pi * freq * i / sr) * vol
            if i < fade: s *= i / fade
            elif i > n - fade: s *= (n - i) / fade
            pcm.append(int(s * 32767))
        path = os.path.join(tempfile.gettempdir(), f"wispger_{freq}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(struct.pack(f"<{n}h", *pcm))
        return path

    def _init_tones(self):
        """Pre-generate start/stop tones at startup."""
        self._tone_start = self._make_tone(880, 60)
        self._tone_stop = self._make_tone(660, 40)

    def _beep(self, tone_path):
        """Play a pre-generated tone file. Non-blocking, instant."""
        try:
            if IS_WIN:
                import winsound
                winsound.PlaySound(tone_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            elif IS_MAC:
                subprocess.Popen(["afplay", tone_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass

    def _press(self, key):
        with self._key_lock:
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): self._ctrl = True
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r): self._win = True
            if self._ctrl and self._win and not self._recording:
                self._recording, self._t0 = True, time.time()
                self._beep(self._tone_start)
                self._rec.start(); self.after(0, self._status.recording); self.after(0, self._overlay.show)

    def _release(self, key):
        with self._key_lock:
            both = self._ctrl and self._win
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): self._ctrl = False
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_r): self._win = False
            if both and self._recording and not (self._ctrl and self._win):
                self._recording = False; dur = time.time()-self._t0 if self._t0 else 0.0
                pcm = self._rec.stop()
                self._beep(self._tone_stop)
                self.after(0, self._overlay.hide)
                if not pcm or dur < self.MIN_RECORDING_SECS:
                    self.after(0, self._status.ready); return
                self.after(0, self._status.processing)
                threading.Thread(target=self._transcribe, args=(pcm, dur), daemon=True).start()

    def _transcribe(self, pcm, dur):
        if not self._lock.acquire(blocking=False):
            self.after(0, lambda: self._status.error("Busy"))
            self.after(3000, self._status.ready)
            return
        try:
            resp = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {self._key}"},
                files={"file": ("audio.wav", self._rec.to_wav(pcm), "audio/wav")},
                data={"model": GROQ_MODEL, "language": self._lang, "response_format": "json",
                      "prompt": self._build_whisper_prompt()}, timeout=15)
            if resp.status_code == 401:
                self.after(0, lambda: self._status.error("Invalid API key"))
                self.after(3000, self._status.ready); return
            resp.raise_for_status()
            raw = resp.json().get("text","").strip()
            if not raw or raw.lower().strip(".!? ") in _HALLUCINATIONS:
                self.after(0, self._status.ready); return
            text = clean_pipeline(raw)
            text = _apply_corrections(text, self._vp.get("corrections", {}))
            paste_text = prep_for_paste(text)  # add leading space for seamless paste
            print(f"[{dur:.1f}s] {text}")
            pyperclip.copy(paste_text); time.sleep(0.15)
            self._kb.press(keyboard.Key.ctrl); self._kb.press("v")
            self._kb.release("v"); self._kb.release(keyboard.Key.ctrl)
            self.after(0, lambda: self._add_card(text, dur))
            self.after(0, lambda: self._update_stats(text, dur))
            self.after(0, lambda: self._update_voice_profile(text))
            self.after(0, self._status.ready)
        except requests.Timeout:
            self.after(0, lambda: self._status.error("Timed out"))
            self.after(3000, self._status.ready)
        except requests.ConnectionError:
            self.after(0, lambda: self._status.error("No connection"))
            self.after(3000, self._status.ready)
        except Exception as e:
            print(f"Error: {e}")
            self.after(0, lambda: self._status.error("API error"))
            self.after(3000, self._status.ready)
        finally:
            self._lock.release()


if __name__ == "__main__":
    print("\n  WispGer Flow\n  Ctrl+Win to record. Release to paste.\n")
    WispGerFlow().mainloop()
