"""Check a snapshot history against reference events, and against Wikipedia as a second opinion.

Snapshots are dated by when someone recorded them, events by when they took effect, so
exact agreement is not expected. Each check allows ``tolerance`` business days either
side of the event (Monday to Friday; holidays are not modelled, which is part of why the
default is three rather than the typical two-day snapshot cadence). Beyond that window,
a gap between snapshots excuses lateness or earliness, and nothing else does:

- **add** (and the new ticker of a **rename**): the ticker should be in the first
  snapshot after the window, or in one inside it. Arriving that late is the snapshot
  cadence and passes, however far away that snapshot is. Being a member in the last
  snapshot *before* the window is ``DRIFT`` (the history has it joining early);
  appearing only in some later snapshot is ``DRIFT`` too (joining late); never
  appearing from the window on is ``MISSING``.
- **remove**: the ticker should be in the last snapshot before the window, or in one
  inside it. Still being a member in the first snapshot *after* the window is ``DRIFT``
  (the history keeps a ticker it lost, a data error or a ticker reused by another
  company); having left before that last pre-window snapshot is ``DRIFT`` (leaving
  early); never being a member up to the window is ``MISSING``.
- **ticker-reuse** events concern identity, not membership, and are not checked here.
- Events dated outside the history are ``UNCOVERED``.

Checks look at the snapshots around each event, not at a ticker's first and last
appearance overall, so a ticker that was a member, left, and came back years later is
judged on the spell the event is about.

A ``MISSING`` check is a failure: the reference describes a membership the history
never shows. ``DRIFT`` is measured and reported, not fatal: a tolerance that hides
drift is worse than one that measures it, and the remedy (fix the history, or the
event) is a human decision.
"""

import statistics
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from pitconstituents.events import Action, Event
from pitconstituents.members import Membership, Snapshot
from pitconstituents.sources.wikipedia import URL as WIKIPEDIA_URL
from pitconstituents.sources.wikipedia import Change

TOLERANCE: int = 3
"""Default business days of disagreement accepted between an event and the snapshots."""


class Status(StrEnum):
    PASS = 'pass'
    DRIFT = 'drift'             # outside the tolerance in the direction that is an error
    MISSING = 'missing'         # the history never shows what the event says happened
    UNCOVERED = 'uncovered'     # the event lies outside the history's dates


class ValidationError(ValueError):
    """A history failed checks against its reference events."""


def business_days(start: date, end: date) -> int:
    """Weekdays in ``[start, end)``; when ``end`` is earlier, minus the weekdays in
    ``(end, start]``. Exactly ``numpy.busday_count`` with its default weekmask."""
    if end < start:
        return -business_days(end + timedelta(days=1), start + timedelta(days=1))
    weeks, extra = divmod((end - start).days, 7)
    first = start.weekday()
    return weeks * 5 + sum(1 for i in range(extra) if (first + i) % 7 < 5)


@dataclass(frozen=True, slots=True)
class Check:
    """One event against the history.

    ``observed`` is the snapshot date that decided the check (for a drift, the start or
    end of the offending membership spell) and ``offset`` its business days from the
    event date, positive when later. Both are ``None`` when no snapshot bears on it.
    """

    event_id: str
    action: Action
    ticker: str
    date: date
    status: Status
    observed: date | None = None
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class Slack:
    """How much of the tolerance the passing checks used, in business days."""

    count: int
    max: int
    median: float
    p99: int


@dataclass(frozen=True, slots=True)
class Report:
    checks: tuple[Check, ...]
    tolerance: int

    def where(self, status: Status) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status is status)

    @property
    def failures(self) -> tuple[Check, ...]:
        return self.where(Status.MISSING)

    @property
    def drift(self) -> tuple[Check, ...]:
        return self.where(Status.DRIFT)

    @property
    def ok(self) -> bool:
        return not self.failures

    def slack(self) -> Slack:
        """Over passing checks with an observation: the max, median and 99th percentile
        of how far the deciding snapshot sat from the event."""
        used = sorted(abs(c.offset) for c in self.where(Status.PASS) if c.offset is not None)
        if not used:
            return Slack(0, 0, 0.0, 0)
        n = len(used)
        return Slack(n, used[-1], float(statistics.median(used)),
                     used[max(0, min(n - 1, round(0.99 * n) - 1))])

    def raise_for_failures(self) -> None:
        if self.failures:
            raise ValidationError('history disagrees with its reference events:\n  - '
                                  + '\n  - '.join(describe(c) for c in self.failures))


def describe(check: Check) -> str:
    """One line for a log or an error message."""
    seen = (f'; history shows {check.observed} ({check.offset:+d} business days)'
            if check.observed is not None else '; history never shows it')
    return f'{check.event_id}: {check.action} {check.ticker} on {check.date} {check.status}{seen}'


# ── the checks ───────────────────────────────────────────────────────────────


def _around(membership: Membership, on: date, tolerance: int) -> Iterator[Snapshot]:
    """Snapshots from just before the tolerance window onward (a calendar-day margin)."""
    return membership.after(on - timedelta(days=tolerance * 2 + 7))


def _spell_start(membership: Membership, ticker: str, snap: Snapshot) -> date:
    start = snap.date
    for earlier in membership.before(snap.date):
        if ticker not in earlier.tickers:
            break
        start = earlier.date
    return start


def _spell_end(membership: Membership, ticker: str, snap: Snapshot) -> date:
    end = snap.date
    for later in membership.after(snap.date + timedelta(days=1)):
        if ticker not in later.tickers:
            break
        end = later.date
    return end


def _offset(on: date, snap: Snapshot) -> int:
    """Business days from the event to the snapshot: negative before, positive after."""
    return business_days(on, snap.date)


def _check_arrival(membership: Membership, event_id: str, action: Action, ticker: str,
                   on: date, tolerance: int) -> Check:
    def made(status: Status, observed: date | None) -> Check:
        offset = business_days(on, observed) if observed is not None else None
        return Check(event_id, action, ticker, on, status, observed, offset)

    # Membership in the last snapshot before the window is a join before the join.
    before = next((s for s in membership.before(on) if _offset(on, s) < -tolerance), None)
    if before is not None and ticker in before.tickers:
        return made(Status.DRIFT, _spell_start(membership, ticker, before))
    # It should appear by the first snapshot past the window, however far off that is.
    confirm = next((s for s in membership.after(on) if _offset(on, s) > tolerance), None)
    for snap in _around(membership, on, tolerance):
        if _offset(on, snap) >= -tolerance and ticker in snap.tickers:
            late = confirm is not None and snap.date > confirm.date
            return made(Status.DRIFT if late else Status.PASS, snap.date)
    return made(Status.MISSING, None)


def _check_departure(membership: Membership, event_id: str, ticker: str, on: date,
                     tolerance: int) -> Check:
    def made(status: Status, observed: date | None) -> Check:
        offset = business_days(on, observed) if observed is not None else None
        return Check(event_id, Action.REMOVE, ticker, on, status, observed, offset)

    # Membership in the first snapshot past the window is a ticker kept after it left.
    beyond = next((s for s in membership.after(on) if _offset(on, s) > tolerance), None)
    if beyond is not None and ticker in beyond.tickers:
        return made(Status.DRIFT, _spell_end(membership, ticker, beyond))
    # Latest first, from the window's end back: where was it last a member?
    latest_first = membership.before(on + timedelta(days=tolerance * 2 + 8))
    up_to_end = (s for s in latest_first if _offset(on, s) <= tolerance)
    for snap in up_to_end:
        if ticker in snap.tickers:
            if _offset(on, snap) >= -tolerance:                 # inside the window
                return made(Status.PASS, snap.date)
            last_before = next(s for s in membership.before(on) if _offset(on, s) < -tolerance)
            early = snap.date < last_before.date
            return made(Status.DRIFT if early else Status.PASS, snap.date)
    return made(Status.MISSING, None)


def _check(membership: Membership, event_id: str, action: Action, ticker: str, on: date,
           tolerance: int) -> Check:
    first, last = membership.first_date, membership.last_date
    if first is None or last is None or on < first or on > last:
        return Check(event_id, action, ticker, on, Status.UNCOVERED)
    if action is Action.REMOVE:
        return _check_departure(membership, event_id, ticker, on, tolerance)
    return _check_arrival(membership, event_id, action, ticker, on, tolerance)


def validate(membership: Membership, events: Iterable[Event], *,
             tolerance: int = TOLERANCE) -> Report:
    """Check ``membership`` against reference ``events``.

    Apply the renames first (``membership.with_events(events)``), or the new ticker of
    every rename will be reported missing. Call :meth:`Report.raise_for_failures` to
    refuse a history that fails.
    """
    if tolerance < 0:
        raise ValueError(f'tolerance must not be negative, got {tolerance}')
    checks = []
    for ev in events:
        if ev.action is Action.TICKER_REUSE:
            continue
        ticker = ev.ticker_after if ev.action is Action.RENAME else ev.ticker
        checks.append(_check(membership, ev.id, ev.action, ticker, ev.date, tolerance))
    return Report(tuple(checks), tolerance)


def cross_check(membership: Membership, changes: Iterable[Change], *,
                tolerance: int = TOLERANCE) -> Report:
    """The same checks for each addition and removal in Wikipedia's changes table.

    Every result is a warning: Wikipedia is a second opinion, not a reference. Rows
    outside the history's dates come back ``UNCOVERED``.
    """
    checks = []
    for change in changes:
        for action, ticker in ((Action.ADD, change.added), (Action.REMOVE, change.removed)):
            if ticker:
                event_id = f'wikipedia:{change.date.isoformat()}:{action}:{ticker}'
                checks.append(_check(membership, event_id, action, ticker, change.date,
                                     tolerance))
    return Report(tuple(checks), tolerance)


__all__ = ['TOLERANCE', 'WIKIPEDIA_URL', 'Check', 'Report', 'Slack', 'Status',
           'ValidationError', 'business_days', 'cross_check', 'describe', 'validate']
