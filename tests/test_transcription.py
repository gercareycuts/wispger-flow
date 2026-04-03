"""Tests for wispger_flow.core.transcription."""

import pytest
from wispger_flow.core.transcription import (
    clean_pipeline, prep_for_paste, apply_corrections,
    HALLUCINATIONS, FILLERS,
)


class TestCleanPipeline:
    def test_removes_repeated_phrases(self):
        result = clean_pipeline("I went to the store I went to the store and bought milk")
        assert "I went to the store" in result
        assert result.count("went to the store") == 1

    def test_adds_trailing_period(self):
        result = clean_pipeline("hello world")
        assert result.endswith(".")

    def test_capitalizes_first_word(self):
        result = clean_pipeline("hello world")
        assert result[0] == "H"

    def test_capitalizes_after_period(self):
        result = clean_pipeline("first sentence. second sentence")
        assert "Second" in result

    def test_question_detection(self):
        result = clean_pipeline("what is your name")
        assert result.endswith("?")

    def test_article_correction_a_to_an(self):
        result = clean_pipeline("I ate a apple")
        assert "an apple" in result

    def test_article_correction_an_to_a(self):
        result = clean_pipeline("this is an cat")
        assert "a cat" in result

    def test_article_consonant_sound_exceptions(self):
        result = clean_pipeline("this is an university")
        assert "a university" in result

    def test_adds_space_after_sentence_end(self):
        result = clean_pipeline("hello.world")
        assert ". " in result or result == "Hello. World."

    def test_collapses_extra_spaces(self):
        result = clean_pipeline("hello   world")
        assert "  " not in result

    def test_empty_input(self):
        assert clean_pipeline("") == ""

    def test_single_word(self):
        result = clean_pipeline("hello")
        assert result == "Hello."

    def test_sentence_starter_punctuation(self):
        result = clean_pipeline("I like cats However I prefer dogs")
        assert "." in result or "," in result

    def test_preserves_existing_punctuation(self):
        result = clean_pipeline("Hello! How are you?")
        assert "!" in result
        assert "?" in result


class TestPrepForPaste:
    def test_adds_leading_space(self):
        assert prep_for_paste("Hello") == " Hello"

    def test_no_space_for_punctuation(self):
        assert prep_for_paste(".") == "."
        assert prep_for_paste(",test") == ",test"
        assert prep_for_paste("!done") == "!done"

    def test_empty_string(self):
        assert prep_for_paste("") == ""

    def test_none_returns_none(self):
        assert prep_for_paste(None) is None


class TestApplyCorrections:
    def test_basic_correction(self):
        result = apply_corrections("I use pytorch daily", {"pytorch": "PyTorch"})
        assert "PyTorch" in result

    def test_case_insensitive(self):
        result = apply_corrections("I use PYTORCH daily", {"pytorch": "PyTorch"})
        assert "PyTorch" in result

    def test_word_boundary(self):
        result = apply_corrections("the cat sat", {"cat": "dog"})
        assert result == "the dog sat"
        # Should not replace partial matches
        result = apply_corrections("concatenate", {"cat": "dog"})
        assert "dog" not in result

    def test_empty_corrections(self):
        assert apply_corrections("hello world", {}) == "hello world"

    def test_multiple_corrections(self):
        result = apply_corrections("use pytorch and tensorflow", {
            "pytorch": "PyTorch",
            "tensorflow": "TensorFlow",
        })
        assert "PyTorch" in result
        assert "TensorFlow" in result


class TestConstants:
    def test_hallucinations_are_lowercase_ish(self):
        for h in HALLUCINATIONS:
            assert h == h.lower() or h == ""

    def test_fillers_are_lowercase(self):
        for f in FILLERS:
            assert f == f.lower()
