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


def _parse_dt(raw: object) -> datetime | None:
    """Parse an ISO datetime string from the store, or None if it won't parse."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_category(raw: object) -> Category | None:
    """Parse a persisted category value, tolerating an unknown/renamed one."""
    try:
        return Category(raw)
    except ValueError:
        return None


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

    def snapshot(self) -> dict[str, object]:
        """Serialize the persist-worthy state (cooldown + today's budget history).

        Debounce timers (``_first_seen``) are intentionally left out: restarting
        them after a reload is harmless and arguably correct (a condition should
        have to re-persist before it fires). Datetimes serialize as ISO strings.
        """
        return {
            "last_fired": {key: ts.isoformat() for key, ts in self._last_fired.items()},
            "fired": [[ts.isoformat(), str(cat)] for ts, cat in self._fired],
        }

    def restore(self, data: dict[str, object]) -> None:
        """Rehydrate cooldown + budget history from a :meth:`snapshot`.

        Defensive against a malformed/stale store: anything that won't parse is
        skipped rather than crashing setup. Old history is pruned the same way
        ``evaluate`` does, on the next cycle.
        """
        last_fired = data.get("last_fired")
        if isinstance(last_fired, dict):
            for key, raw in last_fired.items():
                ts = _parse_dt(raw)
                if ts is not None:
                    self._last_fired[key] = ts
        fired = data.get("fired")
        if isinstance(fired, list):
            for entry in fired:
                if not isinstance(entry, list | tuple) or len(entry) != 2:
                    continue
                ts = _parse_dt(entry[0])
                category = _parse_category(entry[1])
                if ts is not None and category is not None:
                    self._fired.append((ts, category))

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
