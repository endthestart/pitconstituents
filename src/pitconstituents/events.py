"""Hand-checked index events: the reference a snapshot history is validated against.

An event is one dated fact with a source: a ticker added or removed, a ticker renamed
(same company, same CIK), or a ticker reused by a different company (two CIKs).
Snapshot histories are compiled by hand and drift; a short list of events checked
against primary sources (SEC filings, the index provider's announcements) is how the
drift is found. See :mod:`pitconstituents.validation`.

Events load from JSON (a list, or ``{"events": [...]}``) or TOML (``[[events]]``
tables), both readable with the standard library. For YAML, load it yourself and pass
each mapping to :meth:`Event.from_dict`.
"""

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

_CIK = re.compile(r'\d{10}')


class Action(StrEnum):
    ADD = 'add'
    REMOVE = 'remove'
    RENAME = 'rename'               # same entity, new ticker
    TICKER_REUSE = 'ticker-reuse'   # same ticker, a different entity from this date


_REQUIRED: dict[Action, tuple[str, ...]] = {
    Action.ADD: ('ticker', 'entity_cik'),
    Action.REMOVE: ('ticker', 'entity_cik'),
    Action.RENAME: ('ticker_before', 'ticker_after', 'entity_cik'),
    Action.TICKER_REUSE: ('ticker', 'entity_cik_before', 'entity_cik_after'),
}
_CIK_FIELDS = ('entity_cik', 'entity_cik_before', 'entity_cik_after')


@dataclass(frozen=True, slots=True)
class Event:
    """One index event. ``date`` is the effective date: the first day of the new state.

    Each action needs its own fields (``ticker`` and ``entity_cik`` for add and remove;
    ``ticker_before``, ``ticker_after`` and the unchanged ``entity_cik`` for a rename;
    ``ticker`` and two different CIKs for ticker reuse). CIKs are 10-digit, zero-padded.
    ``source_url`` is required: an event nobody can check is not a reference.
    """

    id: str
    date: date
    action: Action
    source_url: str
    ticker: str | None = None
    ticker_before: str | None = None
    ticker_after: str | None = None
    entity_cik: str | None = None
    entity_cik_before: str | None = None
    entity_cik_after: str | None = None
    note: str = ''

    def __post_init__(self) -> None:
        object.__setattr__(self, 'action', Action(self.action))
        if not isinstance(self.date, date) or isinstance(self.date, datetime):
            raise TypeError(f'{self.id}: date must be a date, got {self.date!r}')
        if not self.id or not self.source_url:
            raise ValueError(f'{self.id or "event"}: id and source_url are required')
        missing = [f for f in _REQUIRED[self.action] if not getattr(self, f)]
        if missing:
            raise ValueError(f'{self.id}: {self.action} needs {", ".join(missing)}')
        for field in _CIK_FIELDS:
            value = getattr(self, field)
            if value is not None and not _CIK.fullmatch(value):
                raise ValueError(f'{self.id}: {field} must be 10 digits, got {value!r}')
        if self.action is Action.TICKER_REUSE and self.entity_cik_before == self.entity_cik_after:
            raise ValueError(f'{self.id}: ticker reuse needs two different CIKs')
        if self.action is Action.RENAME and self.ticker_before == self.ticker_after:
            raise ValueError(f'{self.id}: a rename needs two different tickers')

    @classmethod
    def from_dict(cls, data: Mapping) -> 'Event':
        """Build from a mapping with a date as an ISO string or a ``date``. Unknown keys
        are errors, so a typo cannot silently drop a field. ``rationale`` is accepted as
        a synonym for ``note`` and ``spinoff-ticker-reuse`` for ``ticker-reuse``."""
        fields = dict(data)
        if 'rationale' in fields:
            fields['note'] = fields.pop('rationale')
        if fields.get('action') == 'spinoff-ticker-reuse':
            fields['action'] = Action.TICKER_REUSE
        if isinstance(fields.get('date'), str):
            fields['date'] = date.fromisoformat(fields['date'])
        unknown = set(fields) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f'{fields.get("id", "event")}: unknown fields {sorted(unknown)}')
        return cls(**fields)


def load_events(path: str | Path) -> list[Event]:
    """Events from a ``.json`` or ``.toml`` file. Ids must be unique."""
    path = Path(path)
    if path.suffix == '.json':
        raw = json.loads(path.read_text(encoding='utf-8'))
    elif path.suffix == '.toml':
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    else:
        raise ValueError(f'expected a .json or .toml file, got {path.name}')
    entries = raw.get('events') if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise TypeError(f'{path.name}: expected a list of events or an "events" list')
    events = [Event.from_dict(entry) for entry in entries]
    ids = [e.id for e in events]
    if len(set(ids)) != len(ids):
        raise ValueError(f'{path.name}: duplicate event ids')
    return events
