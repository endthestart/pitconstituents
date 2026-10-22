"""Point-in-time membership from dated snapshots of an index's constituents.

A snapshot says which tickers were members on its date. Between snapshots the last one
is in effect: a membership query for any date returns the most recent snapshot on or
before it, never a later one, so nothing is known before it happened.

Snapshots come from a "wide" CSV with a ``date`` column and a ``tickers`` column holding
a comma-separated list, the layout of fja05680/sp500 (:mod:`pitconstituents.sources.fja05680`).
"""

import bisect
import csv
import hashlib
import io
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pitconstituents._http import get_text
from pitconstituents.events import Action, Event


@dataclass(frozen=True, slots=True)
class Snapshot:
    date: date
    tickers: frozenset[str]


class Membership:
    """An ordered run of snapshots, queried as of a date.

    ``source`` and ``digest`` (sha256 of the text it was parsed from) say where it came
    from, for a provenance record; both are empty for snapshots built in code.
    """

    def __init__(self, snapshots: Iterable[Snapshot], *, source: str = '',
                 digest: str = '') -> None:
        ordered = sorted(snapshots, key=lambda s: s.date)
        dates = [s.date for s in ordered]
        if len(set(dates)) != len(dates):
            raise ValueError('two snapshots share a date')
        self._snapshots: tuple[Snapshot, ...] = tuple(ordered)
        self._dates: list[date] = dates
        self.source = source
        self.digest = digest

    # ── building ─────────────────────────────────────────────────────────────

    @classmethod
    def from_wide_csv(cls, text: str, *, source: str = '') -> 'Membership':
        """Parse ``date,tickers`` rows. Tickers are stripped and blanks dropped; a row
        whose date repeats an earlier one is an error, not a silent overwrite."""
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or not {'date', 'tickers'} <= set(reader.fieldnames):
            raise ValueError(f'expected date and tickers columns, got {reader.fieldnames}')
        snapshots = []
        for line, row in enumerate(reader, start=2):
            try:
                day = date.fromisoformat(row['date'].strip())
            except ValueError as exc:
                raise ValueError(f'line {line}: bad date {row["date"]!r}') from exc
            tickers = frozenset(t.strip() for t in (row['tickers'] or '').split(',') if t.strip())
            snapshots.append(Snapshot(day, tickers))
        return cls(snapshots, source=source,
                   digest=hashlib.sha256(text.encode('utf-8')).hexdigest())

    @classmethod
    def load(cls, source: str | Path, *, cache_dir: Path | str | None = None,
             timeout: float = 60.0) -> 'Membership':
        """Read a wide CSV from a URL (cached in ``cache_dir`` if given) or a local path.

        For the S&P 500: ``Membership.load(fja05680.URL, cache_dir=...)``.
        """
        text = get_text(str(source), timeout=timeout, cache_dir=cache_dir)
        return cls.from_wide_csv(text, source=str(source))

    def with_events(self, events: Iterable[Event]) -> 'Membership':
        """Apply ticker renames: from each rename's date on, ``ticker_before`` reads as
        ``ticker_after``. Other events leave membership alone (adds and removes are
        what the snapshots record; ticker reuse is an identity matter, see
        :func:`pitconstituents.identity.cik_on`)."""
        renames = [e for e in events if e.action is Action.RENAME]
        if not renames:
            return self
        snapshots = []
        for snap in self._snapshots:
            tickers = set(snap.tickers)
            for ev in renames:
                if snap.date >= ev.date and ev.ticker_before in tickers:
                    tickers.discard(ev.ticker_before)
                    tickers.add(ev.ticker_after)
            snapshots.append(Snapshot(snap.date, frozenset(tickers)))
        return Membership(snapshots, source=self.source, digest=self.digest)

    # ── querying ─────────────────────────────────────────────────────────────

    def snapshot_on(self, on: date) -> Snapshot | None:
        """The snapshot in effect on ``on``: the latest dated on or before it.

        ``None`` before the first snapshot. After the last one, the last stays in
        effect; compare with :attr:`last_date` if staleness matters.
        """
        i = bisect.bisect_right(self._dates, on)
        return self._snapshots[i - 1] if i else None

    def members(self, on: date) -> frozenset[str]:
        """Tickers that were members on ``on``; empty before the first snapshot."""
        snap = self.snapshot_on(on)
        return snap.tickers if snap is not None else frozenset()

    def first_seen(self, ticker: str) -> date | None:
        return next((s.date for s in self._snapshots if ticker in s.tickers), None)

    def last_seen(self, ticker: str) -> date | None:
        return next((s.date for s in reversed(self._snapshots) if ticker in s.tickers), None)

    def tickers(self) -> frozenset[str]:
        """Every ticker in any snapshot."""
        return frozenset().union(*(s.tickers for s in self._snapshots))

    @property
    def first_date(self) -> date | None:
        return self._dates[0] if self._dates else None

    @property
    def last_date(self) -> date | None:
        return self._dates[-1] if self._dates else None

    @property
    def snapshots(self) -> Sequence[Snapshot]:
        return self._snapshots

    def before(self, on: date) -> Iterator[Snapshot]:
        """Snapshots dated strictly before ``on``, latest first."""
        return reversed(self._snapshots[:bisect.bisect_left(self._dates, on)])

    def after(self, on: date) -> Iterator[Snapshot]:
        """Snapshots dated on or after ``on``, earliest first."""
        return iter(self._snapshots[bisect.bisect_left(self._dates, on):])

    def __len__(self) -> int:
        return len(self._snapshots)

    def __iter__(self) -> Iterator[Snapshot]:
        return iter(self._snapshots)
