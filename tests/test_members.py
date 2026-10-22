"""Snapshots, the nearest-prior rule, the wide-CSV format, and renames."""

import hashlib
from datetime import date

import pytest
from conftest import snaps

from pitconstituents import Event, Membership, Snapshot

WIDE = 'date,tickers\n2001-01-02,"AAA,BBB"\n2001-01-04,"AAA, BBB ,, CCC"\n2001-02-01,"BBB,CCC"\n'


class TestWideCsv:
    def test_rows_become_snapshots_with_tickers_stripped_and_blanks_dropped(self):
        m = Membership.from_wide_csv(WIDE)
        assert [s.date for s in m] == [date(2001, 1, 2), date(2001, 1, 4), date(2001, 2, 1)]
        assert m.members(date(2001, 1, 4)) == {'AAA', 'BBB', 'CCC'}
        assert m.digest == hashlib.sha256(WIDE.encode()).hexdigest()

    def test_rows_out_of_order_are_sorted(self):
        m = Membership.from_wide_csv('date,tickers\n2001-02-01,"BBB"\n2001-01-02,"AAA"\n')
        assert m.first_date == date(2001, 1, 2)

    @pytest.mark.parametrize(('text', 'message'), [
        ('day,names\n2001-01-02,"AAA"\n', 'date and tickers'),
        ('date,tickers\n2001-13-02,"AAA"\n', 'line 2: bad date'),
        ('date,tickers\n2001-01-02,"AAA"\n2001-01-02,"BBB"\n', 'share a date'),
    ])
    def test_malformed_files_are_refused(self, text, message):
        with pytest.raises(ValueError, match=message):
            Membership.from_wide_csv(text)

    def test_load_reads_a_local_path(self, tmp_path):
        path = tmp_path / 'history.csv'
        path.write_text(WIDE)
        m = Membership.load(path)
        assert (len(m), m.source) == (3, str(path))

    def test_load_caches_a_url(self, server, tmp_path):
        server.routes['/history.csv'] = (200, WIDE.encode())
        url = f'{server.base}/history.csv'
        first = Membership.load(url, cache_dir=tmp_path)
        server.routes.clear()                          # a second fetch would now fail
        second = Membership.load(url, cache_dir=tmp_path)
        assert first.digest == second.digest
        assert len(server.requests) == 1


class TestAsOf:
    def test_the_last_snapshot_on_or_before_the_date_is_in_effect(self, history):
        assert history.members(date(2025, 10, 15)) == {'AAA', 'BBB'}
        assert history.members(date(2025, 10, 16)) == {'AAA', 'BBB'}     # between snapshots
        assert history.members(date(2025, 10, 17)) == {'AAA'}
        assert history.snapshot_on(date(2025, 10, 20)).date == date(2025, 10, 17)

    def test_nothing_is_known_before_the_first_snapshot(self, history):
        assert history.members(date(2025, 9, 30)) == frozenset()
        assert history.snapshot_on(date(2025, 9, 30)) is None

    def test_after_the_last_snapshot_the_last_stays_in_effect(self, history):
        assert history.members(date(2026, 6, 1)) == {'AAA', 'CCC', 'DDD', 'EEE'}
        assert history.last_date == date(2025, 11, 14)

    def test_first_and_last_appearances_and_every_ticker(self, history):
        assert history.first_seen('CCC') == date(2025, 10, 21)
        assert history.last_seen('BBB') == date(2025, 10, 15)
        assert history.first_seen('ZZZ') is None and history.last_seen('ZZZ') is None
        assert history.tickers() == {'AAA', 'BBB', 'CCC', 'DDD', 'EEE'}

    def test_neighbours_of_a_date(self, history):
        assert [s.date.day for s in history.before(date(2025, 10, 7))] == [3, 1]
        assert next(history.after(date(2025, 10, 8))).date == date(2025, 10, 9)

    def test_an_empty_history(self):
        m = Membership([])
        assert (len(m), m.first_date, m.members(date(2025, 1, 1))) == (0, None, frozenset())

    def test_two_snapshots_on_one_date_are_refused(self):
        with pytest.raises(ValueError, match='share a date'):
            snaps((date(2025, 1, 2), 'AAA'), (date(2025, 1, 2), 'BBB'))


def test_renames_read_as_the_new_ticker_from_their_date():
    m = snaps((date(2022, 6, 7), 'AAA OLD'), (date(2022, 6, 9), 'AAA OLD'),
              (date(2022, 6, 13), 'AAA NEW'))
    rename = Event('OLD-NEW', date(2022, 6, 9), 'rename', 'https://example.com/8-k',
                   ticker_before='OLD', ticker_after='NEW', entity_cik='0000000001')
    renamed = m.with_events([rename])
    assert renamed.members(date(2022, 6, 7)) == {'AAA', 'OLD'}
    assert renamed.members(date(2022, 6, 9)) == {'AAA', 'NEW'}
    assert renamed.members(date(2022, 6, 13)) == {'AAA', 'NEW'}
    assert m.with_events([]) is m
    assert isinstance(renamed.snapshots[0], Snapshot)
