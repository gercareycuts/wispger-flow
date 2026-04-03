"""Tests for wispger_flow.core.stats."""

from wispger_flow.core.stats import default_stats, ach_progress, update_stats


class TestDefaultStats:
    def test_returns_zeroed_stats(self):
        s = default_stats()
        assert s["total_words"] == 0
        assert s["total_txns"] == 0
        assert s["total_secs"] == 0.0
        assert s["fillers"] == 0
        assert s["unlocked"] == []
        assert s["first_use"] is None

    def test_returns_fresh_copy(self):
        s1 = default_stats()
        s2 = default_stats()
        s1["total_words"] = 100
        assert s2["total_words"] == 0


class TestAchProgress:
    def test_zero_progress(self):
        s = default_stats()
        progress, text = ach_progress(s, "words", 5000)
        assert progress == 0.0
        assert "0" in text
        assert "5,000" in text

    def test_partial_progress(self):
        s = default_stats()
        s["total_words"] = 2500
        progress, text = ach_progress(s, "words", 5000)
        assert progress == 0.5

    def test_completed(self):
        s = default_stats()
        s["total_words"] = 5000
        progress, text = ach_progress(s, "words", 5000)
        assert progress == 1.0
        assert "\u2713" in text

    def test_over_target_capped(self):
        s = default_stats()
        s["total_words"] = 10000
        progress, _ = ach_progress(s, "words", 5000)
        assert progress == 1.0

    def test_txns_progress(self):
        s = default_stats()
        s["total_txns"] = 25
        progress, text = ach_progress(s, "txns", 50)
        assert progress == 0.5


class TestUpdateStats:
    def test_increments_word_count(self):
        s = default_stats()
        s, _, _ = update_stats(s, "hello world foo bar", 2.0, [])
        assert s["total_words"] == 4

    def test_increments_txn_count(self):
        s = default_stats()
        s, _, _ = update_stats(s, "test", 1.0, [])
        assert s["total_txns"] == 1

    def test_tracks_duration(self):
        s = default_stats()
        s, _, _ = update_stats(s, "test", 3.5, [])
        assert s["total_secs"] == 3.5

    def test_counts_fillers(self):
        s = default_stats()
        s, _, _ = update_stats(s, "um I like uh basically", 2.0, [])
        assert s["fillers"] > 0
        assert s["filler_breakdown"]["um"] == 1

    def test_counts_like(self):
        s = default_stats()
        s, _, _ = update_stats(s, "I like totally like this", 2.0, [])
        assert s["like_count"] == 2

    def test_counts_um(self):
        s = default_stats()
        s, _, _ = update_stats(s, "um uh er ah well", 2.0, [])
        assert s["um_count"] == 4

    def test_tiny_transcription(self):
        s = default_stats()
        s, _, _ = update_stats(s, "hello", 1.0, [])
        assert s["tiny_count"] == 1

    def test_not_tiny_if_multiple_words(self):
        s = default_stats()
        s, _, _ = update_stats(s, "hello world", 1.0, [])
        assert s["tiny_count"] == 0

    def test_speed_achievement(self):
        s = default_stats()
        text = " ".join(["word"] * 100)
        s, _, _ = update_stats(s, text, 5.0, [])
        assert s["speed_count"] == 1

    def test_long_recording(self):
        s = default_stats()
        s, _, _ = update_stats(s, "test", 35.0, [])
        assert s["long_count"] == 1

    def test_duplicate_detection(self):
        s = default_stats()
        last = []
        s, _, last = update_stats(s, "hello world", 1.0, last)
        s, _, last = update_stats(s, "hello world", 1.0, last)
        assert s["dupes"] == 1

    def test_last_texts_capped(self):
        s = default_stats()
        last = []
        for i in range(25):
            s, _, last = update_stats(s, f"text {i}", 1.0, last)
        assert len(last) == 20

    def test_unlocks_achievement(self):
        s = default_stats()
        s["total_words"] = 4990
        s, newly, _ = update_stats(s, " ".join(["word"] * 15), 2.0, [])
        unlocked_ids = [a[0] for a in newly]
        assert "w5000" in unlocked_ids

    def test_no_double_unlock(self):
        s = default_stats()
        s["total_words"] = 5000
        s["unlocked"] = ["w5000"]
        s, newly, _ = update_stats(s, "one more", 1.0, [])
        assert "w5000" not in [a[0] for a in newly]
