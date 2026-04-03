"""WispGer Flow — main application window."""

import math
import os
import struct
import subprocess
import threading
import time
import tkinter as tk
import wave

import customtkinter as ctk
import pyperclip
from datetime import datetime
from pynput import keyboard

from wispger_flow.constants import IS_WIN, IS_MAC, APP_DIR, F, HOTKEY, _screen_size, _scroll_units
from wispger_flow.ui.theme import (
    DARK, LIGHT, ACCENT, ACCENTH, TEAL, GREEN, RED, REDDIM, AMBER, TIER_COL,
)
from wispger_flow.ui.widgets import (
    Tooltip, RecordingOverlay, TranscriptionCard, StatusDot,
    render_emoji_images, _ACH_EMOJI_CACHE,
)
from wispger_flow.ui.dialogs import ApiKeyDialog, HotkeyDialog
from wispger_flow.core import transcription
from wispger_flow.core.stats import (
    ACHIEVEMENTS, ACH_HINTS, default_stats, ach_progress, update_stats,
)
from wispger_flow.core.voice_profile import (
    default_voice_profile, update_voice_profile, build_whisper_prompt,
)
from wispger_flow.services import api, storage


class WispGerFlow(ctk.CTk):
    SB_W, SB_C = 200, 56

    def __init__(self, lang="en"):
        super().__init__()
        self.title("WispGer Flow")
        self.geometry("780x680+60+40")
        self.minsize(640, 500)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        ctk.set_appearance_mode("dark")

        cfg = storage.load_cfg()
        self._dark = cfg.get("dark_mode", True)
        self._theme = DARK if self._dark else LIGHT
        self._collapsed = cfg.get("sidebar_collapsed", False)
        self.configure(fg_color=self._theme["bg"])

        self._lang = cfg.get("language", lang)
        _BUNDLED_KEY = ""  # Set your Groq API key here to skip the setup dialog
        self._key = cfg.get("groq_api_key", os.environ.get("GROQ_API_KEY", _BUNDLED_KEY))
        self._stats = {**default_stats(), **cfg.get("stats", {})}
        if not self._stats["first_use"]:
            self._stats["first_use"] = datetime.now().isoformat()
        self._last_texts = []
        self._vp = {**default_voice_profile(), **cfg.get("voice_profile", {})}
        self._rec, self._kb = api.AudioRecorder(), keyboard.Controller()
        self._recording, self._ctrl, self._win, self._t0 = False, False, False, None
        self._key_lock = threading.Lock()
        self._hotkey_mod = cfg.get("hotkey_modifier", "ctrl+cmd" if IS_MAC else "ctrl+win")
        self._sounds_on = cfg.get("sounds_enabled", True)
        self._auto_paste = cfg.get("auto_paste", True)
        self._cards, self._lock, self._view = [], threading.Lock(), "transcriptions"
        self._tabs_stale = set()

        # Pre-render achievement emoji in background
        self._ach_photos = {}
        self._emoji_ready = False
        self._emoji_rendered = threading.Event()
        def _load_emoji():
            if not _ACH_EMOJI_CACHE:
                render_emoji_images()
            self._emoji_rendered.set()
        threading.Thread(target=_load_emoji, daemon=True).start()
        self._poll_emoji()

        self._build_ui()
        self._load_history()
        self._init_tones()
        self._overlay = RecordingOverlay(self, self._rec)
        self._overlay.set_theme(self._theme)
        keyboard.Listener(on_press=self._press, on_release=self._release, daemon=True).start()
        if not self._key:
            self.after(200, self._ask_key)

    def _poll_emoji(self):
        """Poll until background emoji rendering is done, then convert on main thread."""
        if self._emoji_rendered.is_set():
            from PIL import ImageTk
            for char, pil_img in _ACH_EMOJI_CACHE.items():
                if pil_img:
                    self._ach_photos[char] = ImageTk.PhotoImage(pil_img)
            self._emoji_ready = True
        else:
            self.after(100, self._poll_emoji)

    def destroy(self):
        storage.flush_now()
        super().destroy()

    def _ask_key(self):
        d = ApiKeyDialog(self, self._theme)
        self.wait_window(d)
        if d.result:
            self._key = d.result
            storage.save_cfg({"groq_api_key": d.result})
        else:
            self.destroy()

    # -- Fast native scrollable --
    def _mk_scroll(self, parent, bg, fast=False):
        c = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=c.yview)
        inner = tk.Frame(c, bg=bg)
        inner.bind("<Configure>", lambda e: c.configure(scrollregion=c.bbox("all")))
        wid = c.create_window((0, 0), window=inner, anchor="nw")
        c.configure(yscrollcommand=sb.set)
        c.bind("<Configure>", lambda e: c.itemconfigure(wid, width=e.width))
        if fast:
            def scroll(e): c.yview_scroll(int(-1 * (e.delta / 60)), "units")
        else:
            def scroll(e): c.yview_scroll(_scroll_units(e), "units")

        def _bind_scroll(e):
            self._active_scroll = (c, scroll)
            c.bind_all("<MouseWheel>", scroll)

        def _unbind_scroll(e):
            if getattr(self, '_active_scroll', (None,))[0] is c:
                c.unbind_all("<MouseWheel>")
                self._active_scroll = None

        c.bind("<Enter>", _bind_scroll)
        c.bind("<Leave>", _unbind_scroll)
        c.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return inner

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        t = self._theme
        self._sidebar = ctk.CTkFrame(self, fg_color=t["sidebar"], corner_radius=0,
                                     width=self.SB_C if self._collapsed else self.SB_W)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)
        self._right = ctk.CTkFrame(self, fg_color=t["bg"], corner_radius=0)
        self._right.pack(side="left", fill="both", expand=True)
        self._build_sidebar(t)
        self._build_content(t)

    def _build_sidebar(self, t):
        lf = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        lf.pack(fill="x", padx=12, pady=(20, 24))
        self._logo = ctk.CTkLabel(lf, text="\u223f", font=(F, 24, "bold"), text_color=ACCENT)
        self._logo.pack(side="left")
        self._logo_txt = ctk.CTkLabel(lf, text="WispGer Flow", font=(F, 14, "bold"), text_color=t["txt"])
        if not self._collapsed:
            self._logo_txt.pack(side="left", padx=(8, 0))

        self._nav_frame = ctk.CTkFrame(self._sidebar, fg_color="transparent")
        self._nav_frame.pack(fill="x", padx=8)
        self._nav_btns = {}
        for vid, icon, label in [("transcriptions", "\u2302", "Home"), ("dashboard", "\u2197", "Statistics"),
                                  ("voice", "\u266b", "My Voice"), ("settings", "\u2699", "Settings")]:
            f = ctk.CTkFrame(self._nav_frame, fg_color="transparent", cursor="hand2")
            f.pack(fill="x", pady=3)
            active = vid == self._view
            fg = "#fff" if active else t["txt2"]
            li = ctk.CTkLabel(f, text=icon, font=(F, 20), width=36, text_color=fg)
            li.pack(side="left", padx=(6, 0))
            lt = ctk.CTkLabel(f, text=label, font=(F, 14, "bold" if active else "normal"), text_color=fg)
            if not self._collapsed:
                lt.pack(side="left", padx=(6, 0))
            f.configure(fg_color=ACCENT if active else "transparent", corner_radius=8)
            for w in (f, li, lt):
                w.bind("<Button-1>", lambda e, v=vid: self._switch_view(v))

            def _hover_enter(e, frame=f, v=vid):
                if v != self._view:
                    frame.configure(fg_color=self._theme["border"])

            def _hover_leave(e, frame=f, v=vid):
                if v != self._view:
                    frame.configure(fg_color="transparent")

            for w in (f, li, lt):
                w.bind("<Enter>", _hover_enter)
                w.bind("<Leave>", _hover_leave)
            self._nav_btns[vid] = {"frame": f, "icon": li, "label": lt}

        ctk.CTkFrame(self._sidebar, fg_color="transparent").pack(fill="both", expand=True)

        for icon, txt, cmd, attr_i, attr_t in [
            ("\u263e" if self._dark else "\u2600", "Theme", self._toggle_theme, "_theme_icon", "_theme_txt"),
            ("\u00bb" if self._collapsed else "\u00ab", "Collapse", self._toggle_sidebar, "_col_icon", "_col_txt"),
        ]:
            f = ctk.CTkFrame(self._sidebar, fg_color="transparent", cursor="hand2")
            f.pack(fill="x", padx=8, pady=2)
            li = ctk.CTkLabel(f, text=icon, font=(F, 14 if "col" in attr_i else 16), width=32, text_color=t["txt2"])
            li.pack(side="left", padx=(4, 0))
            lt = ctk.CTkLabel(f, text=txt, font=(F, 11), text_color=t["txt2"])
            if not self._collapsed:
                lt.pack(side="left", padx=(6, 0))
            for w in (f, li, lt):
                w.bind("<Button-1>", lambda e, c=cmd: c())
            setattr(self, attr_i, li)
            setattr(self, attr_t, lt)

        self._status = StatusDot(self._sidebar, t)
        self._status.pack(padx=12, pady=(8, 16), anchor="w")

    def _days_active(self):
        try:
            return (datetime.now() - datetime.fromisoformat(self._stats["first_use"])).days
        except Exception:
            return 0

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
        banner.pack(fill="x")
        banner.pack_propagate(False)
        self._banner = banner
        self._banner_sep = ctk.CTkFrame(banner, fg_color=t["border"], height=1)
        self._banner_sep.pack(fill="x", side="bottom")

        stats_f = ctk.CTkFrame(banner, fg_color="transparent")
        stats_f.pack(side="right", padx=16)

        self._bell_btn = ctk.CTkButton(stats_f, text="\U0001f514", font=(F, 16), width=36, height=36,
                                        fg_color="transparent", hover_color=t["border"], text_color=t["txt2"],
                                        command=self._show_notifications)
        self._bell_btn.pack(side="right", padx=(12, 0))
        self._bell_badge = ctk.CTkLabel(stats_f, text="", font=(F, 7, "bold"), text_color="#fff",
                                         fg_color=RED, corner_radius=7, width=14, height=14)
        unread = len(self._stats.get("unlocked", [])) - self._stats.get("notifs_seen", 0)
        if unread > 0:
            self._bell_badge.place(in_=self._bell_btn, relx=0.75, rely=0.15, anchor="center")
            self._bell_badge.configure(text=str(min(unread, 9)))
        s = self._stats

        from PIL import Image, ImageTk
        self._emoji_imgs = []
        for img_name, val, label, attr in [
            ("fire", f"{self._days_active()}d", "Active", "_ban_days"),
            ("rocket", f"{s['total_words']:,}", "Words", "_ban_words"),
            ("trophy", f"{self._wpm()}", "WPM", "_ban_wpm"),
        ]:
            img = Image.open(APP_DIR / "fonts" / f"{img_name}.png")
            photo = ImageTk.PhotoImage(img)
            self._emoji_imgs.append(photo)
            tk.Label(stats_f, image=photo, bg=t["bg2"], bd=0).pack(side="left", padx=(18, 4))
            lbl = ctk.CTkLabel(stats_f, text=val, font=(F, 12, "bold"), text_color=t["txt2"])
            lbl.pack(side="left", padx=(0, 3))
            ctk.CTkLabel(stats_f, text=label, font=(F, 9), text_color=t["dim"]).pack(side="left")
            setattr(self, attr, lbl)

        self._tx_frame = ctk.CTkScrollableFrame(self._right, fg_color=t["bg"],
            scrollbar_button_color=t["border"], corner_radius=0)
        self._tx_frame.pack(fill="both", expand=True)
        # Disable CTk's internal slow scroll, replace with faster one
        self._tx_canvas = self._tx_frame._parent_canvas
        # Remove all existing mousewheel bindings on the canvas
        self._tx_canvas.unbind("<MouseWheel>")
        try:
            self._tx_canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        # Patch CTk's _mouse_wheel_all method to do nothing (prevents it rebinding)
        self._tx_frame._mouse_wheel_all = lambda e: None
        def _fast_scroll(e):
            self._tx_canvas.yview_scroll(int(-1 * (e.delta / 4)), "units")
        self._fast_home_scroll = _fast_scroll
        self._tx_canvas.bind("<MouseWheel>", _fast_scroll)
        self._tx_frame.bind_all("<MouseWheel>", _fast_scroll)

        self._empty = ctk.CTkFrame(self._tx_frame, fg_color="transparent")
        self._empty.pack(fill="x", pady=80)
        ctk.CTkLabel(self._empty, text="\u223f", font=(F, 56, "bold"), text_color=t["dim"]).pack()
        ctk.CTkLabel(self._empty, text="No transcriptions yet", font=(F, 16, "bold"), text_color=t["dim"]).pack(pady=(16, 4))
        ctk.CTkLabel(self._empty, text=f"Hold {HOTKEY} and start speaking.\nYour transcriptions will appear here.",
                     font=(F, 11), text_color=t["dim"], justify="center").pack()

        self._dash_container = tk.Frame(self._right, bg=t["bg"])
        self._dash_frame = self._mk_scroll(self._dash_container, t["bg"])

        self._voice_container = tk.Frame(self._right, bg=t["bg"])
        self._voice_frame = self._mk_scroll(self._voice_container, t["bg"])

        self._settings_container = tk.Frame(self._right, bg=t["bg"])
        self._settings_frame = self._mk_scroll(self._settings_container, t["bg"])

        self._build_dashboard(t)
        self._build_voice_tab(t)
        self._build_settings_tab(t)

    # ---------------------------------------------------------------- Dashboard
    def _build_dashboard(self, t):
        d, s = self._dash_frame, self._stats

        hero = ctk.CTkFrame(d, fg_color="transparent")
        hero.pack(fill="x", padx=12, pady=(16, 8))
        hero.columnconfigure((0, 1, 2), weight=1)
        self._hero_widgets = []
        hero_tips = [
            "Total number of words you've dictated",
            "Total audio recording time processed",
            "Total number of voice transcriptions completed",
        ]
        for col, (icon, val, lbl) in enumerate([
            ("\u2328", f"{s['total_words']:,}", "Words Transcribed"),
            ("\u23f1", f"{s['total_secs'] / 60:.0f} min", "Audio Processed"),
            ("\u223f", str(s['total_txns']), "Transcriptions"),
        ]):
            c = ctk.CTkFrame(hero, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
            c.grid(row=0, column=col, padx=4, sticky="nsew")
            ctk.CTkLabel(c, text=icon, font=(F, 22), text_color=ACCENT).pack(pady=(16, 4))
            v = ctk.CTkLabel(c, text=val, font=(F, 24, "bold"), text_color=t["txt"])
            v.pack()
            ctk.CTkLabel(c, text=lbl, font=(F, 9), text_color=t["txt2"]).pack(pady=(2, 16))
            self._hero_widgets.append(v)
            Tooltip(c, hero_tips[col])

        fc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        fc.pack(fill="x", padx=16, pady=(0, 8))
        ff = ctk.CTkFrame(fc, fg_color="transparent")
        ff.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(ff, text="\U0001f6ab", font=(F, 22), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(ff, text="Filler Words Caught", font=(F, 12), text_color=t["txt"]).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(ff, text=str(s["fillers"]), font=(F, 20, "bold"), text_color=t["txt"]).pack(side="right")
        bd = s.get("filler_breakdown", {})
        if bd:
            top = sorted(bd.items(), key=lambda x: -x[1])[:8]
            breakdown = " \u2022 ".join(f'"{w}" \u00d7{c}' for w, c in top)
            tip = f"Top fillers: {breakdown}"
        else:
            tip = "No filler words caught yet"
        Tooltip(fc, tip)

        cur_section = None
        grid_frame = badge_list = None
        for aid, atype, target, icon, name, sub, tier in ACHIEVEMENTS:
            section = {"words": "Words Transcribed", "txns": "Transcription Milestones"}.get(atype)
            if tier == "roast":
                section = "Roasts & Quirks"
            if section and section != cur_section:
                cur_section = section
                ctk.CTkLabel(d, text=section, font=(F, 12, "bold"), text_color=t["txt2"], anchor="w").pack(fill="x", padx=20, pady=(20, 8))
                grid_frame = ctk.CTkFrame(d, fg_color="transparent")
                grid_frame.pack(fill="x", padx=16)
                grid_frame.columnconfigure((0, 1), weight=1, uniform="badge")
                badge_list = []

            row, col = len(badge_list) // 2, len(badge_list) % 2
            progress, count_text = ach_progress(s, atype, target)
            unlocked = aid in s.get("unlocked", [])

            b = ctk.CTkFrame(grid_frame, fg_color=t["card"], corner_radius=12, border_width=1,
                             border_color=TIER_COL[tier] if unlocked else t["border"])
            b.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            dim = t["txt"] if unlocked else t["dim"]
            ctk.CTkLabel(b, text=tier.upper(), font=(F, 7, "bold"), text_color="#fff",
                         fg_color=TIER_COL[tier], corner_radius=4, width=50, height=16).pack(anchor="e", padx=10, pady=(8, 0))
            icon_holder = ctk.CTkFrame(b, fg_color="transparent", width=56, height=56)
            icon_holder.pack(pady=(4, 4))
            icon_holder.pack_propagate(False)
            photo = self._ach_photos.get(icon) if unlocked else None
            if photo:
                tk.Label(icon_holder, image=photo, bg=t["card"], bd=0, highlightthickness=0).place(relx=0.5, rely=0.5, anchor="center")
            else:
                ctk.CTkLabel(icon_holder, text=icon, font=(F, 32), text_color=t["dim"]).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(b, text=name, font=(F, 15, "bold"), text_color=dim).pack()
            ctk.CTkLabel(b, text=sub, font=(F, 8), text_color=t["dim"]).pack()
            pb = ctk.CTkProgressBar(b, height=10, corner_radius=5, progress_color=TEAL, fg_color=t["border"])
            pb.pack(fill="x", padx=16, pady=(6, 3))
            pb.set(min(progress, 1.0))
            ctk.CTkLabel(b, text=count_text, font=(F, 9), text_color=t["dim"]).pack(pady=(0, 10))
            hint = ACH_HINTS.get(atype, "").format(target=target)
            if unlocked:
                hint = f"\u2713 Unlocked!\n{hint}"
            Tooltip(b, hint)
            badge_list.append(b)

        days = 0
        try:
            days = (datetime.now() - datetime.fromisoformat(s["first_use"])).days
        except Exception:
            pass
        ctk.CTkLabel(d, text=f"You've been using WispGer Flow for {days} day{'s' if days != 1 else ''}",
                     font=(F, 10), text_color=t["dim"]).pack(pady=16)

    def _refresh_dashboard(self):
        s = self._stats
        if self._hero_widgets:
            self._hero_widgets[0].configure(text=f"{s['total_words']:,}")
            self._hero_widgets[1].configure(text=f"{s['total_secs'] / 60:.0f} min")
            self._hero_widgets[2].configure(text=str(s['total_txns']))

    # ---------------------------------------------------------------- My Voice Tab
    def _build_voice_tab(self, t):
        d = self._voice_frame
        vp = self._vp

        txns = self._stats.get("total_txns", 0)
        strength = min(txns / 2000, 1.0)
        strength_text = f"Profile trained ({txns:,}+ transcriptions)" if strength >= 1.0 else f"Learning... {txns:,} / 2,000 transcriptions"

        sc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        sc.pack(fill="x", padx=16, pady=(16, 8))
        sf = ctk.CTkFrame(sc, fg_color="transparent")
        sf.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(sf, text="\U0001f9e0", font=(F, 20)).pack(side="left")
        ctk.CTkLabel(sf, text=strength_text, font=(F, 12), text_color=t["txt"]).pack(side="left", padx=(10, 0))
        pb = ctk.CTkProgressBar(sc, height=8, corner_radius=4, progress_color=TEAL, fg_color=t["border"])
        pb.pack(fill="x", padx=16, pady=(0, 14))
        pb.set(strength)

        vocab = vp.get("vocab", {})
        ctk.CTkLabel(d, text="Top Vocabulary", font=(F, 13, "bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(16, 6))
        vc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        vc.pack(fill="x", padx=16, pady=(0, 8))
        if vocab:
            top_vocab = sorted(vocab.items(), key=lambda x: -x[1])[:20]
            vf = tk.Frame(vc, bg=t["card"])
            vf.pack(fill="x", padx=16, pady=12)
            self._vocab_chips = []
            for w, c in top_vocab:
                chip = ctk.CTkFrame(vf, fg_color=t["border"], corner_radius=6)
                ctk.CTkLabel(chip, text=f"{w} ({c})", font=(F, 9), text_color=t["txt"], padx=8, pady=2).pack()
                self._vocab_chips.append(chip)

            def _flow_layout(frame=vf, chips=self._vocab_chips):
                frame.update_idletasks()
                max_w = frame.winfo_width()
                if max_w < 10:
                    max_w = 400
                x, y, row_h = 0, 0, 0
                for chip in chips:
                    chip.update_idletasks()
                    cw, ch = chip.winfo_reqwidth(), chip.winfo_reqheight()
                    if x + cw > max_w and x > 0:
                        x = 0
                        y += row_h + 4
                        row_h = 0
                    chip.place(x=x, y=y)
                    row_h = max(row_h, ch)
                    x += cw + 4
                frame.configure(height=y + row_h + 4)
            self.after(100, _flow_layout)
        else:
            vf = ctk.CTkFrame(vc, fg_color="transparent")
            vf.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(vf, text="\U0001f4a1", font=(F, 16)).pack(side="left")
            ef = ctk.CTkFrame(vf, fg_color="transparent")
            ef.pack(side="left", padx=(8, 0))
            ctk.CTkLabel(ef, text="Your unique words will appear here", font=(F, 10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(ef, text="e.g.  deployment (12)  \u2022  kubernetes (8)  \u2022  refactor (5)", font=(F, 9), text_color=t["dim"]).pack(anchor="w")

        phrases = vp.get("phrases", {})
        ctk.CTkLabel(d, text="Common Phrases", font=(F, 13, "bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12, 6))
        pc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        pc.pack(fill="x", padx=16, pady=(0, 8))
        if phrases:
            top_phrases = sorted(phrases.items(), key=lambda x: -x[1])[:10]
            for p, c in top_phrases:
                pf = ctk.CTkFrame(pc, fg_color="transparent")
                pf.pack(fill="x", padx=16, pady=3)
                ctk.CTkLabel(pf, text=f'"{p}"', font=(F, 10), text_color=t["txt"]).pack(side="left")
                ctk.CTkLabel(pf, text=f"\u00d7{c}", font=(F, 9, "bold"), text_color=t["txt2"]).pack(side="right")
        else:
            ef = ctk.CTkFrame(pc, fg_color="transparent")
            ef.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(ef, text="\U0001f50d", font=(F, 16)).pack(side="left")
            pef = ctk.CTkFrame(ef, fg_color="transparent")
            pef.pack(side="left", padx=(8, 0))
            ctk.CTkLabel(pef, text="Repeated phrases will be detected automatically", font=(F, 10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(pef, text='e.g.  "at the end of the day" \u00d78  \u2022  "in terms of" \u00d75', font=(F, 9), text_color=t["dim"]).pack(anchor="w")

        corrections = vp.get("corrections", {})
        ctk.CTkLabel(d, text="Corrections", font=(F, 13, "bold"), text_color=t["txt"], anchor="w").pack(fill="x", padx=20, pady=(12, 6))
        cc = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=12, border_width=1, border_color=t["border"])
        cc.pack(fill="x", padx=16, pady=(0, 8))
        if corrections:
            for wrong, right in corrections.items():
                cf = ctk.CTkFrame(cc, fg_color="transparent")
                cf.pack(fill="x", padx=16, pady=3)
                ctk.CTkLabel(cf, text=wrong, font=(F, 10), text_color=RED).pack(side="left")
                ctk.CTkLabel(cf, text="\u2192", font=(F, 10), text_color=t["dim"]).pack(side="left", padx=8)
                ctk.CTkLabel(cf, text=right, font=(F, 10, "bold"), text_color=TEAL).pack(side="left")

                def _del(w=wrong):
                    del self._vp["corrections"][w]
                    storage.save_cfg({"voice_profile": self._vp})
                    self._rebuild_voice_tab()

                ctk.CTkButton(cf, text="\u2715", width=24, height=24, corner_radius=4, font=(F, 10),
                              fg_color="transparent", hover_color=t["border"], text_color=t["dim"],
                              command=_del).pack(side="right")
        else:
            ef = ctk.CTkFrame(cc, fg_color="transparent")
            ef.pack(fill="x", padx=16, pady=12)
            ctk.CTkLabel(ef, text="\u270f", font=(F, 16)).pack(side="left")
            cef = ctk.CTkFrame(ef, fg_color="transparent")
            cef.pack(side="left", padx=(8, 0))
            ctk.CTkLabel(cef, text="Teach Whisper your terminology", font=(F, 10), text_color=t["dim"]).pack(anchor="w")
            ctk.CTkLabel(cef, text='e.g.  "pie test" \u2192 pytest  \u2022  "cube control" \u2192 kubectl', font=(F, 9), text_color=t["dim"]).pack(anchor="w")

        add_f = ctk.CTkFrame(cc, fg_color="transparent")
        add_f.pack(fill="x", padx=16, pady=(4, 12))
        self._cor_wrong = ctk.CTkEntry(add_f, width=120, height=28, font=(F, 10), placeholder_text="Whisper hears...",
                                       fg_color=t["bg"], border_color=t["border"], text_color=t["txt"])
        self._cor_wrong.pack(side="left")
        ctk.CTkLabel(add_f, text="\u2192", font=(F, 10), text_color=t["dim"]).pack(side="left", padx=6)
        self._cor_right = ctk.CTkEntry(add_f, width=120, height=28, font=(F, 10), placeholder_text="You mean...",
                                       fg_color=t["bg"], border_color=t["border"], text_color=t["txt"])
        self._cor_right.pack(side="left")
        ctk.CTkButton(add_f, text="Add", width=50, height=28, corner_radius=6, font=(F, 10, "bold"),
                      fg_color=ACCENT, hover_color=ACCENTH, command=self._add_correction).pack(side="left", padx=(8, 0))

        ctk.CTkButton(d, text="Reset Voice Profile", width=140, height=32, corner_radius=8, font=(F, 10),
                      fg_color=RED, hover_color=REDDIM, text_color="#fff",
                      command=self._reset_voice_profile).pack(pady=16)

    def _add_correction(self):
        w = self._cor_wrong.get().strip()
        r = self._cor_right.get().strip()
        if w and r:
            self._vp.setdefault("corrections", {})[w.lower()] = r
            storage.save_cfg({"voice_profile": self._vp})
            self._rebuild_voice_tab()

    def _reset_voice_profile(self):
        self._vp = default_voice_profile()
        storage.save_cfg({"voice_profile": self._vp})
        self._rebuild_voice_tab()

    def _rebuild_voice_tab(self):
        if hasattr(self, '_voice_container'):
            vis = self._view == "voice"
            if vis:
                self._voice_container.pack_forget()
            if getattr(self, '_active_scroll', None):
                try:
                    self.unbind_all("<MouseWheel>")
                except Exception:
                    pass
                self._active_scroll = None
            self._voice_container.destroy()
            self._voice_container = tk.Frame(self._right, bg=self._theme["bg"])
            self._voice_frame = self._mk_scroll(self._voice_container, self._theme["bg"])
            self._build_voice_tab(self._theme)
            if vis:
                self._voice_container.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- Settings Tab
    def _build_settings_tab(self, t):
        d = self._settings_frame
        cfg = storage.load_cfg()

        ctk.CTkLabel(d, text="\u2699 Settings", font=(F, 18, "bold"), text_color=t["txt"]).pack(pady=(20, 16))

        def _row(parent, label, widget_fn):
            f = ctk.CTkFrame(parent, fg_color=t["card"], corner_radius=10)
            f.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(f, text=label, font=(F, 11), text_color=t["txt"]).pack(side="left", padx=12, pady=10)
            widget_fn(f)
            return f

        dd = dict(fg_color=t["border"], button_color=ACCENT, button_hover_color=ACCENTH,
                  text_color=t["txt"], dropdown_fg_color=t["card"], dropdown_text_color=t["txt"],
                  dropdown_hover_color=t["border"])

        self._s_lang = ctk.StringVar(value=self._lang)
        _row(d, "Language", lambda f: ctk.CTkOptionMenu(f, values=["en", "es", "fr", "de", "it", "pt", "nl", "ja", "ko", "zh"],
             variable=self._s_lang, width=80, font=(F, 10), **dd).pack(side="right", padx=12, pady=10))

        current_mod = cfg.get("hotkey_modifier", "ctrl+cmd" if IS_MAC else "ctrl+win")
        self._s_hk = ctk.StringVar(value=current_mod)
        hk_presets = ["ctrl+cmd", "ctrl+shift", "ctrl+alt"] if IS_MAC else ["ctrl+win", "ctrl+shift", "ctrl+alt"]
        hk_opts = hk_presets + ["custom..."]
        if current_mod not in hk_presets:
            hk_opts = hk_presets + [current_mod, "custom..."]

        def _on_hk_change(choice):
            if choice == "custom...":
                self._open_hotkey_capture()

        hk_f = ctk.CTkFrame(d, fg_color=t["card"], corner_radius=10)
        hk_f.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(hk_f, text="Record Hotkey", font=(F, 11), text_color=t["txt"]).pack(side="left", padx=12, pady=10)
        self._hk_menu = ctk.CTkOptionMenu(hk_f, values=hk_opts, variable=self._s_hk, width=130, font=(F, 10),
                                           command=_on_hk_change, **dd)
        self._hk_menu.pack(side="right", padx=12, pady=10)

        self._s_aot = ctk.BooleanVar(value=cfg.get("always_on_top", True))
        _row(d, "Always On Top", lambda f: ctk.CTkSwitch(f, text="", variable=self._s_aot, width=40,
             progress_color=ACCENT).pack(side="right", padx=12, pady=10))

        self._s_snd = ctk.BooleanVar(value=cfg.get("sounds_enabled", True))
        _row(d, "Recording Sounds", lambda f: ctk.CTkSwitch(f, text="", variable=self._s_snd, width=40,
             progress_color=ACCENT).pack(side="right", padx=12, pady=10))

        self._s_paste = ctk.BooleanVar(value=cfg.get("auto_paste", True))
        _row(d, "Auto-Paste on Transcribe", lambda f: ctk.CTkSwitch(f, text="", variable=self._s_paste, width=40,
             progress_color=ACCENT).pack(side="right", padx=12, pady=10))

        key_display = self._key[:8] + "..." if len(self._key) > 8 else self._key
        _row(d, "API Key", lambda f: ctk.CTkLabel(f, text=key_display, font=(F, 9), text_color=t["dim"]).pack(side="right", padx=12, pady=10))

        ctk.CTkButton(d, text="Save Settings", width=140, height=36, corner_radius=8, font=(F, 12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENTH, command=self._save_settings).pack(pady=(20, 16))

    def _open_hotkey_capture(self):
        dlg = HotkeyDialog(self, self._theme)
        self.wait_window(dlg)
        if dlg.result:
            self._s_hk.set(dlg.result)
            presets = ["ctrl+cmd", "ctrl+shift", "ctrl+alt"] if IS_MAC else ["ctrl+win", "ctrl+shift", "ctrl+alt"]
            self._hk_menu.configure(values=presets + [dlg.result, "custom..."])
        else:
            prev = storage.load_cfg().get("hotkey_modifier", "ctrl+cmd" if IS_MAC else "ctrl+win")
            self._s_hk.set(prev)

    def _save_settings(self):
        self._lang = self._s_lang.get()
        self.attributes("-topmost", self._s_aot.get())
        self._hotkey_mod = self._s_hk.get()
        self._sounds_on = self._s_snd.get()
        self._auto_paste = self._s_paste.get()
        storage.save_cfg({
            "language": self._lang,
            "always_on_top": self._s_aot.get(),
            "sounds_enabled": self._sounds_on,
            "auto_paste": self._s_paste.get(),
            "hotkey_modifier": self._hotkey_mod,
        })

    # ---------------------------------------------------------------- Views
    def _rebuild_tab(self, tab, t):
        """Destroy and rebuild a secondary tab container."""
        attr_map = {
            "dashboard": ("_dash_container", "_dash_frame", "_build_dashboard"),
            "voice": ("_voice_container", "_voice_frame", "_build_voice_tab"),
            "settings": ("_settings_container", "_settings_frame", "_build_settings_tab"),
        }
        container_attr, frame_attr, builder_name = attr_map[tab]
        container = getattr(self, container_attr)
        was_visible = container.winfo_manager() != ""
        if was_visible:
            container.pack_forget()
        container.destroy()
        new_container = tk.Frame(self._right, bg=t["bg"])
        setattr(self, container_attr, new_container)
        setattr(self, frame_attr, self._mk_scroll(new_container, t["bg"]))
        getattr(self, builder_name)(t)
        if was_visible:
            new_container.pack(fill="both", expand=True)
        self._tabs_stale.discard(tab)

    def _switch_view(self, view):
        if view == self._view:
            return
        self._view = view
        t = self._theme
        for vid, w in self._nav_btns.items():
            a = vid == view
            w["frame"].configure(fg_color=ACCENT if a else "transparent")
            w["icon"].configure(text_color="#fff" if a else t["txt2"])
            w["label"].configure(text_color="#fff" if a else t["txt2"], font=(F, 14, "bold" if a else "normal"))
        for f in (self._tx_frame, self._dash_container, self._voice_container, self._settings_container):
            f.pack_forget()
        if view == "transcriptions":
            self._tx_frame.pack(fill="both", expand=True)
            self._tx_frame.bind_all("<MouseWheel>", self._fast_home_scroll)
        elif view == "dashboard":
            if "dashboard" in getattr(self, '_tabs_stale', set()):
                self._rebuild_tab("dashboard", t)
            else:
                self._refresh_dashboard()
            self._dash_container.pack(fill="both", expand=True)
        elif view == "voice":
            if "voice" in getattr(self, '_tabs_stale', set()):
                self._rebuild_tab("voice", t)
            else:
                self._rebuild_voice_tab()
            self._voice_container.pack(fill="both", expand=True)
        elif view == "settings":
            if "settings" in getattr(self, '_tabs_stale', set()):
                self._rebuild_tab("settings", t)
            self._settings_container.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- Sidebar
    def _toggle_sidebar(self):
        self._collapsed = not self._collapsed
        storage.save_cfg({"sidebar_collapsed": self._collapsed})
        self._sidebar.configure(width=self.SB_C if self._collapsed else self.SB_W)
        self._col_icon.configure(text="\u00bb" if self._collapsed else "\u00ab")
        if self._collapsed:
            for w in (self._logo_txt, self._col_txt, self._theme_txt):
                w.pack_forget()
            for v in self._nav_btns.values():
                v["label"].pack_forget()
        else:
            self._logo_txt.pack(side="left", padx=(8, 0))
            self._col_txt.pack(side="left", padx=(6, 0))
            self._theme_txt.pack(side="left", padx=(6, 0))
            for v in self._nav_btns.values():
                v["label"].pack(side="left", padx=(6, 0))

    # ---------------------------------------------------------------- Theme
    def _toggle_theme(self):
        self._dark = not self._dark
        self._theme = DARK if self._dark else LIGHT
        t = self._theme
        storage.save_cfg({"dark_mode": self._dark})
        self._theme_icon.configure(text="\u263e" if self._dark else "\u2600")

        self.configure(fg_color=t["bg"])
        self._sidebar.configure(fg_color=t["sidebar"])
        self._right.configure(fg_color=t["bg"])
        self._banner.configure(fg_color=t["bg2"])
        self._banner_sep.configure(fg_color=t["border"])
        self._bell_btn.configure(text_color=t["txt2"], hover_color=t["border"])
        self._ban_days.configure(text_color=t["txt2"])
        self._ban_words.configure(text_color=t["txt2"])
        self._ban_wpm.configure(text_color=t["txt2"])
        for w in self._banner.winfo_children():
            for ch in (w.winfo_children() if hasattr(w, 'winfo_children') else []):
                if isinstance(ch, tk.Label) and ch.cget("image"):
                    ch.configure(bg=t["bg2"])
        self._tx_frame.configure(fg_color=t["bg"], scrollbar_button_color=t["border"])
        self._overlay.set_theme(t)

        self._logo_txt.configure(text_color=t["txt"])
        self._col_icon.configure(text_color=t["txt2"])
        self._col_txt.configure(text_color=t["txt2"])
        self._theme_icon.configure(text_color=t["txt2"])
        self._theme_txt.configure(text_color=t["txt2"])
        for vid, w in self._nav_btns.items():
            if vid != self._view:
                w["icon"].configure(text_color=t["txt2"])
                w["label"].configure(text_color=t["txt2"])

        for card in self._cards:
            card.update_theme(t)

        if self._empty:
            for w in self._empty.winfo_children():
                if isinstance(w, ctk.CTkLabel):
                    w.configure(text_color=t["dim"])

        if getattr(self, '_active_scroll', None):
            try:
                self.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._active_scroll = None
        # Mark all secondary tabs as stale — only rebuild the visible one now
        self._tabs_stale = {"dashboard", "voice", "settings"}
        view_map = {"dashboard": "_dash_container", "voice": "_voice_container", "settings": "_settings_container"}
        if self._view in view_map:
            self._rebuild_tab(self._view, t)

        # Re-bind fast home scroll (may have been overridden by tab rebuilds)
        if self._view == "transcriptions":
            self._tx_frame.bind_all("<MouseWheel>", self._fast_home_scroll)

    # ---------------------------------------------------------------- Stats
    def _update_stats(self, text, dur):
        self._stats, newly_unlocked, self._last_texts = update_stats(
            self._stats, text, dur, self._last_texts
        )
        storage.save_cfg({"stats": self._stats})
        self._refresh_banner()
        for a in newly_unlocked:
            self.after(500, lambda x=a: self._toast(x))

    def _toast(self, ach):
        icon, name = ach[3], ach[4]
        t = ctk.CTkFrame(self._right, fg_color=TEAL, corner_radius=12)
        t.place(relx=0.5, rely=0.95, anchor="s")
        ctk.CTkLabel(t, text=f"{icon}  Achievement Unlocked: {name}", font=(F, 12, "bold"), text_color="#fff").pack(padx=20, pady=10)
        self.after(4000, t.destroy)
        unread = len(self._stats.get("unlocked", [])) - self._stats.get("notifs_seen", 0)
        if unread > 0:
            self._bell_badge.configure(text=str(min(unread, 9)))
            self._bell_badge.place(in_=self._bell_btn, relx=0.75, rely=0.15, anchor="center")

    def _show_notifications(self):
        if hasattr(self, '_notif_panel') and self._notif_panel and self._notif_panel.winfo_exists():
            self._notif_panel.destroy()
            self._notif_panel = None
            return

        t = self._theme
        unlocked_ids = set(self._stats.get("unlocked", []))
        self._stats["notifs_seen"] = len(unlocked_ids)
        storage.save_cfg({"stats": self._stats})
        self._bell_badge.place_forget()

        pw = min(300, int(self._right.winfo_width() * 0.45)) or 280
        ph = min(400, max(220, 80 + len(unlocked_ids) * 56))
        panel = ctk.CTkFrame(self._right, fg_color=t["card"], corner_radius=12,
                             border_width=1, border_color=t["border"], width=pw, height=ph)
        panel.place(relx=1.0, x=-12, y=68, anchor="ne")
        panel.pack_propagate(False)
        self._notif_panel = panel

        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(hdr, text="Achievements", font=(F, 13, "bold"), text_color=t["txt"]).pack(side="left")
        ctk.CTkButton(hdr, text="\u2715", width=28, height=28, corner_radius=6, font=(F, 12),
                      fg_color="transparent", hover_color=t["border"], text_color=t["dim"],
                      command=lambda: [panel.destroy(), setattr(self, '_notif_panel', None)]).pack(side="right")

        ctk.CTkFrame(panel, fg_color=t["border"], height=1).pack(fill="x", padx=12, pady=(0, 4))

        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent", scrollbar_button_color=t["border"])
        scroll.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        unlocked_achs = [a for a in ACHIEVEMENTS if a[0] in unlocked_ids]
        if unlocked_achs:
            for _, _, _, icon, name, sub, tier in reversed(unlocked_achs):
                row = ctk.CTkFrame(scroll, fg_color=t["bg"], corner_radius=8)
                row.pack(fill="x", pady=2)
                photo = self._ach_photos.get(icon)
                if photo:
                    tk.Label(row, image=photo, bg=t["bg"], bd=0, highlightthickness=0).pack(side="left", padx=(8, 4), pady=6)
                else:
                    ctk.CTkLabel(row, text=icon, font=(F, 18), text_color=t["txt"]).pack(side="left", padx=(8, 4), pady=6)
                info = ctk.CTkFrame(row, fg_color="transparent")
                info.pack(side="left", fill="x", expand=True, pady=6)
                ctk.CTkLabel(info, text=name, font=(F, 10, "bold"), text_color=t["txt"], anchor="w").pack(fill="x")
                ctk.CTkLabel(info, text=sub, font=(F, 8), text_color=t["dim"], anchor="w").pack(fill="x")
                ctk.CTkLabel(row, text=tier.upper(), font=(F, 7, "bold"), text_color="#fff",
                             fg_color=TIER_COL[tier], corner_radius=4, width=44, height=14).pack(side="right", padx=8)
        else:
            ctk.CTkLabel(scroll, text="\U0001f3af", font=(F, 28)).pack(pady=(16, 4))
            ctk.CTkLabel(scroll, text="No achievements earned yet", font=(F, 11, "bold"), text_color=t["txt"]).pack()
            ctk.CTkLabel(scroll, text="Keep transcribing to unlock\nyour first achievement!", font=(F, 9),
                         text_color=t["dim"], justify="center").pack(pady=(4, 12))

    # ---------------------------------------------------------------- Cards
    def _on_card_edit(self, ts, new_text):
        storage.update_history_text(ts.isoformat(), new_text)

    def _load_history(self):
        history = storage.load_history()
        if not history:
            return
        if self._empty:
            self._empty.destroy()
            self._empty = None
        for entry in history:
            ts = datetime.fromisoformat(entry["ts"])
            card = TranscriptionCard(self._tx_frame, entry["text"], entry["dur"], ts, self._theme,
                                     on_edit=self._on_card_edit)
            card.pack(fill="x", padx=12, pady=(8, 0))
            self._cards.append(card)

    def _add_card(self, text, dur):
        if self._empty:
            self._empty.destroy()
            self._empty = None
        ts = datetime.now()
        card = TranscriptionCard(self._tx_frame, text, dur, ts, self._theme, animate=True,
                                 on_edit=self._on_card_edit)
        if self._cards:
            card.pack(fill="x", padx=12, pady=(8, 0), before=self._cards[0])
        else:
            card.pack(fill="x", padx=12, pady=(8, 0))
        self._cards.insert(0, card)
        storage.save_history_entry(text, dur, ts)

    # ---------------------------------------------------------------- Hotkey & Recording
    MIN_RECORDING_SECS = 0.3

    @staticmethod
    def _make_tone(freq, ms, vol=0.12):
        import tempfile
        sr = 22050
        n = int(sr * ms / 1000)
        fade = min(n // 4, 200)
        pcm = []
        for i in range(n):
            s = math.sin(2 * math.pi * freq * i / sr) * vol
            if i < fade:
                s *= i / fade
            elif i > n - fade:
                s *= (n - i) / fade
            pcm.append(int(s * 32767))
        path = os.path.join(tempfile.gettempdir(), f"wispger_{freq}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(struct.pack(f"<{n}h", *pcm))
        return path

    def _init_tones(self):
        self._tone_start = self._make_tone(880, 60)
        self._tone_stop = self._make_tone(660, 40)

    def _beep(self, tone_path):
        try:
            if IS_WIN:
                import winsound
                winsound.PlaySound(tone_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            elif IS_MAC:
                subprocess.Popen(["afplay", tone_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _hotkey_keys(self):
        mod = self._hotkey_mod
        parts = mod.split("+")
        key_map = {
            "ctrl": (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r),
            "win": (keyboard.Key.cmd, keyboard.Key.cmd_r),
            "cmd": (keyboard.Key.cmd, keyboard.Key.cmd_r),
            "shift": (keyboard.Key.shift_l, keyboard.Key.shift_r),
            "alt": (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr),
        }
        sets = []
        for p in parts:
            if p in key_map:
                sets.append(key_map[p])
            else:
                try:
                    sets.append((keyboard.KeyCode.from_char(p),))
                except Exception:
                    pass
        if len(sets) >= 2:
            return sets[0], sets[1]
        return (), ()

    def _press(self, key):
        with self._key_lock:
            k1, k2 = self._hotkey_keys()
            if key in k1:
                self._ctrl = True
            elif key in k2:
                self._win = True
            if self._ctrl and self._win and not self._recording:
                self._recording, self._t0 = True, time.time()
                if self._sounds_on:
                    self._beep(self._tone_start)
                self._rec.start()
                self.after(0, self._status.recording)
                self.after(0, self._overlay.show)

    def _release(self, key):
        with self._key_lock:
            k1, k2 = self._hotkey_keys()
            both = self._ctrl and self._win
            if key in k1:
                self._ctrl = False
            elif key in k2:
                self._win = False
            if both and self._recording and not (self._ctrl and self._win):
                self._recording = False
                threading.Timer(0.2, self._stop_recording).start()

    def _stop_recording(self):
        dur = time.time() - self._t0 if self._t0 else 0.0
        pcm = self._rec.stop()
        if self._sounds_on:
            self._beep(self._tone_stop)
        self.after(0, self._overlay.hide)
        if not pcm or dur < self.MIN_RECORDING_SECS:
            self.after(0, self._status.ready)
            return
        self.after(0, self._status.processing)
        threading.Thread(target=self._transcribe, args=(pcm, dur), daemon=True).start()

    def _transcribe(self, pcm, dur):
        if not self._lock.acquire(blocking=False):
            self.after(0, lambda: self._status.error("Busy"))
            self.after(3000, self._status.ready)
            return
        try:
            raw = api.send_transcription(
                self._key, self._rec.to_wav(pcm), self._lang,
                build_whisper_prompt(self._vp),
            )
            if not raw or raw.lower().strip(".!? ") in transcription.HALLUCINATIONS:
                self.after(0, self._status.ready)
                return
            text = transcription.clean_pipeline(raw)
            text = transcription.apply_corrections(text, self._vp.get("corrections", {}))
            paste_text = transcription.prep_for_paste(text)
            print(f"[{dur:.1f}s] {text}")
            if self._auto_paste:
                pyperclip.copy(paste_text)
                time.sleep(0.15)
                mod = keyboard.Key.cmd if IS_MAC else keyboard.Key.ctrl
                self._kb.press(mod)
                self._kb.press("v")
                self._kb.release("v")
                self._kb.release(mod)
            self.after(0, lambda: self._add_card(text, dur))
            self.after(0, lambda: self._update_stats(text, dur))
            self.after(0, lambda: self._update_voice_profile(text))
            self.after(0, self._status.ready)
        except PermissionError:
            self.after(0, lambda: self._status.error("Invalid API key"))
            self.after(3000, self._status.ready)
        except Exception as e:
            msg = "Timed out" if "Timeout" in type(e).__name__ else "No connection" if "ConnectionError" in type(e).__name__ else "API error"
            print(f"Error: {e}")
            self.after(0, lambda: self._status.error(msg))
            self.after(3000, self._status.ready)
        finally:
            self._lock.release()

    def _update_voice_profile(self, text):
        self._vp = update_voice_profile(self._vp, text, self._stats["total_txns"])
        storage.save_cfg({"voice_profile": self._vp})
