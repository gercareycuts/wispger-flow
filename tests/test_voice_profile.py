"""Tests for wispger_flow.core.voice_profile."""

from wispger_flow.core.voice_profile import (
    default_voice_profile, update_voice_profile, build_whisper_prompt,
    COMMON_WORDS,
)


class TestDefaultVoiceProfile:
    def test_returns_empty_profile(self):
        vp = default_voice_profile()
        assert vp["vocab"] == {}
        assert vp["phrases"] == {}
        assert vp["corrections"] == {}
        assert vp["style_notes"] == ""
        assert vp["prompt_override"] == ""


class TestUpdateVoiceProfile:
    def test_tracks_uncommon_words(self):
        vp = default_voice_profile()
        vp = update_voice_profile(vp, "python javascript react", 1)
        assert "python" in vp["vocab"]
        assert "javascript" in vp["vocab"]

    def test_ignores_common_words(self):
        vp = default_voice_profile()
        vp = update_voice_profile(vp, "the quick brown fox", 1)
        assert "the" not in vp["vocab"]

    def test_ignores_fillers(self):
        vp = default_voice_profile()
        vp = update_voice_profile(vp, "um uh basically python", 1)
        assert "um" not in vp["vocab"]
        assert "python" in vp["vocab"]

    def test_increments_word_count(self):
        vp = default_voice_profile()
        vp = update_voice_profile(vp, "python", 1)
        vp = update_voice_profile(vp, "python", 2)
        assert vp["vocab"]["python"] == 2

    def test_caps_vocab_at_200(self):
        vp = default_voice_profile()
        words = " ".join(f"uniqueword{i}" for i in range(250))
        vp = update_voice_profile(vp, words, 1)
        assert len(vp["vocab"]) <= 200

    def test_tracks_phrases(self):
        vp = default_voice_profile()
        # Seed phrase count past the >= 2 filter so it persists
        vp["phrases"]["python framework"] = 2
        vp = update_voice_profile(vp, "python framework rocks", 1)
        assert "python framework" in vp["phrases"]
        assert vp["phrases"]["python framework"] == 3

    def test_phrases_need_min_count(self):
        vp = default_voice_profile()
        vp = update_voice_profile(vp, "quantum computing today", 1)
        # Phrases with count < 2 are filtered out
        assert "quantum computing" not in vp["phrases"]

    def test_caps_phrases_at_100(self):
        vp = default_voice_profile()
        for i in range(120):
            vp["phrases"][f"phrase{i} word{i}"] = 5
        vp = update_voice_profile(vp, "another phrase here", 1)
        assert len(vp["phrases"]) <= 100

    def test_decay_at_50_txns(self):
        vp = default_voice_profile()
        vp["vocab"] = {"python": 10, "react": 2}
        vp = update_voice_profile(vp, "test", 50)
        assert vp["vocab"]["python"] == 8.0
        # "react" at 2 * 0.8 = 1.6 should survive
        assert "react" in vp["vocab"]

    def test_decay_removes_low_counts(self):
        vp = default_voice_profile()
        vp["vocab"] = {"rareword": 1}
        vp = update_voice_profile(vp, "test", 50)
        # 1 * 0.8 = 0.8, rounds to 0.8, which < 1 so deleted
        assert "rareword" not in vp["vocab"]


class TestBuildWhisperPrompt:
    def test_uses_override_if_set(self):
        vp = default_voice_profile()
        vp["prompt_override"] = "Custom prompt here"
        assert build_whisper_prompt(vp) == "Custom prompt here"

    def test_override_truncated_at_600(self):
        vp = default_voice_profile()
        vp["prompt_override"] = "x" * 700
        assert len(build_whisper_prompt(vp)) == 600

    def test_includes_style_notes(self):
        vp = default_voice_profile()
        vp["style_notes"] = "Technical speaker"
        prompt = build_whisper_prompt(vp)
        assert "Technical speaker" in prompt

    def test_includes_corrections(self):
        vp = default_voice_profile()
        vp["corrections"] = {"pytorch": "PyTorch"}
        prompt = build_whisper_prompt(vp)
        assert "PyTorch" in prompt

    def test_includes_top_vocab(self):
        vp = default_voice_profile()
        vp["vocab"] = {"python": 10, "react": 5, "docker": 3}
        prompt = build_whisper_prompt(vp)
        assert "python" in prompt

    def test_includes_top_phrases(self):
        vp = default_voice_profile()
        vp["phrases"] = {"machine learning": 10}
        prompt = build_whisper_prompt(vp)
        assert "machine learning" in prompt

    def test_falls_back_to_default_prompt(self):
        vp = default_voice_profile()
        prompt = build_whisper_prompt(vp)
        assert len(prompt) > 0
        assert "Hello" in prompt

    def test_prompt_word_limit(self):
        vp = default_voice_profile()
        vp["vocab"] = {f"word{i}": 100 - i for i in range(200)}
        prompt = build_whisper_prompt(vp)
        assert len(prompt.split()) <= 150
