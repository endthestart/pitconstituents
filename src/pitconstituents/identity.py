"""Tickers to SEC CIKs, the identifier that survives renames and is not reused.

A ticker is a label: FB became META without the company changing, and WM meant
Washington Mutual before it meant Waste Management. Key anything that must follow a
company through time (prices, filings, trades) on its CIK, the SEC's Central Index Key.

:func:`resolve_cik` checks the caller's overrides first, then a lookup of *current*
tickers (see :mod:`pitconstituents.sources.edgar`). That lookup cannot be point-in-time:
it maps a ticker to whoever holds it today. Historical tickers that were since reused,
renamed or delisted need an override, and a ticker that changed hands needs a
``ticker-reuse`` event for :func:`cik_on`.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date

from pitconstituents.events import Action, Event

CikLookup = Callable[[str], str | None]
"""Maps a ticker to a 10-digit CIK, or None when it does not know it."""

_DIGITS = re.compile(r'\d{1,10}')


def normalize_cik(value: int | str) -> str:
    """A CIK as the SEC writes it: 10 digits, zero-padded."""
    text = str(value).strip()
    if not _DIGITS.fullmatch(text) or int(text) == 0:
        raise ValueError(f'not a CIK: {value!r}')
    return text.zfill(10)


def resolve_cik(ticker: str, lookup: CikLookup | None = None, *,
                overrides: Mapping[str, str] | None = None) -> str | None:
    """The CIK for ``ticker``: from ``overrides`` if present, else ``lookup``, else None.

    Overrides win because they exist precisely where the current-ticker lookup is wrong
    for history; each one should be checked against a filing before it is added.
    """
    if overrides and ticker in overrides:
        return normalize_cik(overrides[ticker])
    return lookup(ticker) if lookup is not None else None


def build_cik_map(tickers: Iterable[str], lookup: CikLookup | None = None, *,
                  overrides: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """``{ticker: cik or None}`` for every distinct ticker, sorted. ``None`` is a gap to
    fill with an override, never a reason to drop the ticker from membership."""
    return {t: resolve_cik(t, lookup, overrides=overrides) for t in sorted(set(tickers))}


def cik_on(ticker: str, on: date, cik_map: Mapping[str, str | None],
           events: Iterable[Event] = ()) -> str | None:
    """The CIK ``ticker`` referred to on ``on``.

    ``cik_map`` gives each ticker's entity by default. A ``ticker-reuse`` event for the
    ticker splits its history at the event's date: before it, ``entity_cik_before``;
    from it, ``entity_cik_after``. With several reuses, the latest one on or before
    ``on`` decides, and dates before the first reuse take its ``entity_cik_before``.
    """
    reuses = sorted((e for e in events
                     if e.action is Action.TICKER_REUSE and e.ticker == ticker),
                    key=lambda e: e.date)
    if not reuses:
        return cik_map.get(ticker)
    in_effect = [e for e in reuses if e.date <= on]
    return in_effect[-1].entity_cik_after if in_effect else reuses[0].entity_cik_before
