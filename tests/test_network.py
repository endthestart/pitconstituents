"""Against the live upstreams. Deselected by default; run with ``uv run pytest -m network``.

The fja05680 test downloads the pinned file (about 5.5 MB). The SEC and Wikipedia tests
need ``PITCONSTITUENTS_USER_AGENT`` set to your application name and a contact address,
and skip without it.
"""

import os
from datetime import date

import pytest

from pitconstituents.sources import edgar, fja05680, wikipedia

pytestmark = pytest.mark.network
AGENT = os.environ.get('PITCONSTITUENTS_USER_AGENT', '')
needs_agent = pytest.mark.skipif(not AGENT, reason='set PITCONSTITUENTS_USER_AGENT')


def test_the_pinned_history_parses():
    history = fja05680.load()
    assert history.first_date == date(1996, 1, 2)
    assert history.last_date >= date(2026, 1, 1)
    assert 480 <= len(history.members(date(2010, 6, 1))) <= 510
    assert 'TSLA' in history.members(date(2021, 1, 4))
    assert 'TSLA' not in history.members(date(2020, 12, 1))


@needs_agent
def test_the_sec_ticker_table():
    lookup = edgar.sec_lookup(user_agent=AGENT)
    assert lookup('AAPL') == '0000320193'


@needs_agent
def test_the_wikipedia_changes_table():
    changes = wikipedia.fetch_changes(user_agent=AGENT)
    assert len(changes) > 300
    assert any(c.added == 'TSLA' and c.date == date(2020, 12, 21) for c in changes)
