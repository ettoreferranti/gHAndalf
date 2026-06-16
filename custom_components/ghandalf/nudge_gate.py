"""The nudge gate — anti-alert-fatigue machinery.

Given the advice candidates a rule run produced, decides which (if any) should
actually be surfaced *now*, applying: presence-gating, quiet hours, a debounce
(the condition must persist), a per-advice cooldown, and global + per-category
daily budgets.

State (first-seen / last-fired / fired-today) lives in memory for the lifetime
of the config entry. It is deterministic given its inputs and an injected
``now``, so it tests cleanly without patching the clock.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .helpers import in_quiet_hours
from .models import AdviceCandidate, Category

# Drop fired-history older than this (we only need "today" for budgets). The exact
# value and the prune comparison are memory housekeeping with no effect on which
# nudges fire (budgets filter by *today's* date), so their mutants are equivalent.
_HISTORY_RETENTION = timedelta(days=2)  # pragma: no mutate


class NudgeGate:
    """Decides which advice candidates are allowed to fire on a given cycle."""

    def __init__(
        self,
        *,
        quiet_start: time,
        quiet_end: time,
        debounce_seconds: int,
        cooldown_minutes: int,
        max_per_day: int,
        max_per_category_per_day: int,
    ) -> None:
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.debounce = timedelta(seconds=debounce_seconds)
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self.max_per_day = max_per_day
        self.max_per_category = max_per_category_per_day
        self._first_seen: dict[str, datetime] = {}
        self._last_fired: dict[str, datetime] = {}
        self._fired: list[tuple[datetime, Category]] = []

    def evaluate(
        self,
        candidates: list[AdviceCandidate],
        now: datetime,
        presence_home: bool = True,
    ) -> list[AdviceCandidate]:
        """Return the subset of ``candidates`` that should fire at ``now``."""
        cutoff = now - _HISTORY_RETENTION  # pragma: no mutate
        self._fired = [t for t in self._fired if t[0] >= cutoff]  # pragma: no mutate

        keys_now = {c.key for c in candidates}
        # A candidate that disappeared resolved itself — reset its debounce.
        for key in list(self._first_seen):
            if key not in keys_now:
                del self._first_seen[key]
        for candidate in candidates:
            self._first_seen.setdefault(candidate.key, now)

        # Nobody home: suppress everything and restart debounce timers.
        if not presence_home:
            self._first_seen.clear()
            return []
        # Quiet hours: suppress, but keep debounce timers running.
        if in_quiet_hours(now.time(), self.quiet_start, self.quiet_end):
            return []

        today = now.date()
        day_count = sum(1 for t, _ in self._fired if t.date() == today)
        cat_count: dict[Category, int] = {}
        for fired_at, category in self._fired:
            if fired_at.date() == today:
                cat_count[category] = cat_count.get(category, 0) + 1

        fired: list[AdviceCandidate] = []
        for candidate in candidates:
            if now - self._first_seen[candidate.key] < self.debounce:
                continue  # hasn't persisted long enough yet
            last = self._last_fired.get(candidate.key)
            if last is not None and now - last < self.cooldown:
                continue  # still cooling down
            if day_count >= self.max_per_day:
                # `continue` vs `break` is equivalent here: day_count only grows,
                # so once the global budget is spent nothing else can fire either.
                continue  # global daily budget spent  # pragma: no mutate
            if cat_count.get(candidate.category, 0) >= self.max_per_category:
                continue  # this category's daily budget spent

            self._last_fired[candidate.key] = now
            self._fired.append((now, candidate.category))
            fired.append(candidate)
            day_count += 1
            cat_count[candidate.category] = cat_count.get(candidate.category, 0) + 1

        return fired
