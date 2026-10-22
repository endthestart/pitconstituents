"""Tickers to CIKs: overrides, lookups, gaps kept as gaps, and tickers that change hands."""

from datetime import date

import pytest

from pitconstituents import Event, build_cik_map, cik_on, normalize_cik, resolve_cik

CURRENT = {'AAA': '0000000001', 'WWW': '0000000004'}


def lookup(ticker):
    return CURRENT.get(ticker)


@pytest.mark.parametrize(('value', 'expected'), [(320193, '0000320193'), ('66740', '0000066740'),
                                                 (' 0000000001 ', '0000000001')])
def test_ciks_are_ten_digits(value, expected):
    assert normalize_cik(value) == expected


@pytest.mark.parametrize('value', ['', 'abc', '12345678901', 0, '-1'])
def test_non_ciks_are_refused(value):
    with pytest.raises(ValueError):
        normalize_cik(value)


def test_overrides_come_first_then_the_lookup_then_none():
    overrides = {'AAA': '7', 'GONE': '0000000009'}
    assert resolve_cik('AAA', lookup, overrides=overrides) == '0000000007'
    assert resolve_cik('GONE', lookup, overrides=overrides) == '0000000009'
    assert resolve_cik('WWW', lookup, overrides=overrides) == '0000000004'
    assert resolve_cik('NOPE', lookup, overrides=overrides) is None
    assert resolve_cik('AAA') is None


def test_a_gap_stays_a_gap_in_the_map():
    """An unresolved ticker is reported as None, never dropped: dropping it would remove a
    real member from the history and bias anything built on it toward survivors."""
    assert build_cik_map(['WWW', 'AAA', 'NOPE', 'AAA'], lookup) == {
        'AAA': '0000000001', 'NOPE': None, 'WWW': '0000000004'}


def reuse(on, before, after, ticker='WWW'):
    return Event(f'{ticker}-{on}', on, 'ticker-reuse', 'https://example.com/filing',
                 ticker=ticker, entity_cik_before=before, entity_cik_after=after)


def test_a_reused_ticker_points_at_the_entity_of_its_era():
    events = [reuse(date(2009, 1, 2), '0000000003', '0000000004')]
    cik_map = {'WWW': '0000000004'}            # the current holder, as a lookup reports it
    assert cik_on('WWW', date(2008, 9, 25), cik_map, events) == '0000000003'
    assert cik_on('WWW', date(2009, 1, 2), cik_map, events) == '0000000004'
    assert cik_on('AAA', date(2008, 9, 25), {'AAA': '0000000001'}, events) == '0000000001'


def test_with_several_reuses_the_latest_in_effect_decides():
    events = [reuse(date(2015, 1, 2), '0000000004', '0000000005'),
              reuse(date(2009, 1, 2), '0000000003', '0000000004')]
    assert [cik_on('WWW', date(y, 6, 1), {}, events) for y in (2005, 2010, 2020)] == [
        '0000000003', '0000000004', '0000000005']
