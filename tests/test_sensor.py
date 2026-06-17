"""Tests for the advice sensor's attribute shaping."""

from __future__ import annotations

from custom_components.ghandalf.sensor import _advice_attrs


def _advice(*messages):
    return {"advice": [{"key": f"k{i}", "message": m} for i, m in enumerate(messages)]}


def test_advice_markdown_one_bullet_per_advice():
    attrs = _advice_attrs(_advice("First thing.", "Second thing."))
    assert attrs["advice_markdown"] == "- First thing.\n- Second thing."
    # Summary stays the single headline (first advice).
    assert attrs["summary"] == "First thing."


def test_advice_markdown_single_advice():
    attrs = _advice_attrs(_advice("Only thing."))
    assert attrs["advice_markdown"] == "- Only thing."


def test_advice_markdown_empty_is_plain_line():
    attrs = _advice_attrs({})
    assert attrs["advice_markdown"] == "No advice right now."
    assert attrs["summary"] == "No advice right now."
    assert attrs["advice"] == []
