"""Tests for the nudge gate (debounce, cooldown, quiet hours, budgets, presence)."""

from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.ghandalf.helpers import parse_time
from custom_components.ghandalf.models import AdviceCandidate, Category, Urgency
from custom_components.ghandalf.nudge_gate import NudgeGate

NOON = datetime(2026, 6, 16, 12, 0, 0)


def make_gate(
    *,
    debounce_seconds: int = 300,
    cooldown_minutes: int = 60,
    max_per_day: int = 8,
    max_per_category_per_day: int = 3,
) -> NudgeGate:
    return NudgeGate(
        quiet_start=parse_time("22:00:00"),
        quiet_end=parse_time("07:00:00"),
        debounce_seconds=debounce_seconds,
        cooldown_minutes=cooldown_minutes,
        max_per_day=max_per_day,
        max_per_category_per_day=max_per_category_per_day,
    )


def cand(key: str = "solar_surplus", category: Category = Category.ENERGY):
    return AdviceCandidate(
        key=key, category=category, urgency=Urgency.INFO, message="m"
    )


def keys(fired):
    return {c.key for c in fired}


def test_debounce_holds_until_condition_persists():
    g = make_gate(debounce_seconds=300)
    c = [cand()]
    assert g.evaluate(c, NOON) == []  # just appeared
    assert g.evaluate(c, NOON + timedelta(seconds=120)) == []  # not long enough
    assert keys(g.evaluate(c, NOON + timedelta(seconds=300))) == {"solar_surplus"}


def test_cooldown_blocks_repeat_then_allows():
    g = make_gate(debounce_seconds=0, cooldown_minutes=60)
    c = [cand()]
    assert keys(g.evaluate(c, NOON)) == {"solar_surplus"}
    assert g.evaluate(c, NOON + timedelta(minutes=30)) == []  # cooling down
    assert keys(g.evaluate(c, NOON + timedelta(minutes=60))) == {"solar_surplus"}


def test_quiet_hours_suppress():
    g = make_gate(debounce_seconds=0)
    night = datetime(2026, 6, 16, 23, 30, 0)
    assert g.evaluate([cand()], night) == []


def test_outside_quiet_hours_fires():
    g = make_gate(debounce_seconds=0)
    assert keys(g.evaluate([cand()], NOON)) == {"solar_surplus"}


def test_absence_suppresses_and_resets_debounce():
    g = make_gate(debounce_seconds=300)
    c = [cand()]
    g.evaluate(c, NOON, presence_home=True)  # first seen at NOON
    g.evaluate(c, NOON + timedelta(seconds=200), presence_home=False)  # away -> reset
    # Back home; debounce restarts from this moment.
    assert g.evaluate(c, NOON + timedelta(seconds=250), presence_home=True) == []
    assert keys(g.evaluate(c, NOON + timedelta(seconds=560), presence_home=True)) == {
        "solar_surplus"
    }


def test_resolved_candidate_resets_debounce():
    g = make_gate(debounce_seconds=300)
    g.evaluate([cand("a")], NOON)
    g.evaluate([], NOON + timedelta(seconds=100))  # condition cleared
    assert g.evaluate([cand("a")], NOON + timedelta(seconds=150)) == []  # restarted
    assert keys(g.evaluate([cand("a")], NOON + timedelta(seconds=460))) == {"a"}


def test_global_daily_budget():
    g = make_gate(debounce_seconds=0, max_per_day=2, max_per_category_per_day=10)
    cs = [
        cand("a", Category.ENERGY),
        cand("b", Category.ENERGY),
        cand("c", Category.ENERGY),
    ]
    assert len(g.evaluate(cs, NOON)) == 2  # third blocked by global cap


def test_per_category_budget():
    g = make_gate(debounce_seconds=0, max_per_day=100, max_per_category_per_day=1)
    cs = [
        cand("a", Category.ENERGY),
        cand("b", Category.AIR_QUALITY),
        cand("c", Category.ENERGY),
    ]
    # one ENERGY (a) + one AIR_QUALITY (b); second ENERGY (c) blocked.
    assert keys(g.evaluate(cs, NOON)) == {"a", "b"}


def test_budget_resets_next_day():
    g = make_gate(debounce_seconds=0, cooldown_minutes=60, max_per_day=1)
    assert len(g.evaluate([cand("a")], NOON)) == 1
    assert g.evaluate([cand("b")], NOON + timedelta(minutes=5)) == []  # cap reached
    next_day = NOON + timedelta(days=1)
    assert len(g.evaluate([cand("b")], next_day)) == 1  # budget rolled over


def test_global_budget_counts_prior_cycles():
    """The daily count must include nudges fired on earlier cycles, once each."""
    g = make_gate(debounce_seconds=0, max_per_day=2, max_per_category_per_day=10)
    assert keys(g.evaluate([cand("a")], NOON)) == {"a"}
    assert keys(g.evaluate([cand("b")], NOON + timedelta(minutes=1))) == {"b"}
    assert g.evaluate([cand("c")], NOON + timedelta(minutes=2)) == []  # 3rd over cap


def test_category_budget_counts_prior_cycles():
    """Per-category cap counts this category's prior-cycle nudges, once each."""
    g = make_gate(debounce_seconds=0, max_per_day=100, max_per_category_per_day=2)
    assert keys(g.evaluate([cand("a", Category.ENERGY)], NOON)) == {"a"}
    later = g.evaluate([cand("b", Category.ENERGY)], NOON + timedelta(minutes=1))
    assert keys(later) == {"b"}
    assert g.evaluate([cand("c", Category.ENERGY)], NOON + timedelta(minutes=2)) == []


def test_category_budget_within_one_cycle():
    g = make_gate(debounce_seconds=0, max_per_day=100, max_per_category_per_day=2)
    cs = [
        cand("a", Category.ENERGY),
        cand("b", Category.ENERGY),
        cand("c", Category.ENERGY),
    ]
    assert keys(g.evaluate(cs, NOON)) == {"a", "b"}  # exactly the cap


def test_unripe_candidate_does_not_block_a_ripe_one():
    g = make_gate(debounce_seconds=300)
    g.evaluate([cand("a")], NOON)  # a first seen now
    # b appears only now (not ripe); a (ripe) is listed *after* b.
    fired = g.evaluate([cand("b"), cand("a")], NOON + timedelta(seconds=300))
    assert keys(fired) == {"a"}


def test_cooling_candidate_does_not_block_a_fresh_one():
    g = make_gate(debounce_seconds=0, cooldown_minutes=60)
    g.evaluate([cand("a")], NOON)  # a fires, now cooling
    fired = g.evaluate([cand("a"), cand("b")], NOON + timedelta(minutes=1))
    assert keys(fired) == {"b"}  # a still cooling, b fresh


def test_full_category_does_not_block_another_category():
    g = make_gate(debounce_seconds=0, max_per_day=100, max_per_category_per_day=1)
    g.evaluate([cand("a", Category.ENERGY)], NOON)  # ENERGY now at its cap
    fired = g.evaluate(
        [cand("a2", Category.ENERGY), cand("b", Category.AIR_QUALITY)],
        NOON + timedelta(minutes=1),
    )
    assert keys(fired) == {"b"}  # energy blocked, air-quality still allowed
