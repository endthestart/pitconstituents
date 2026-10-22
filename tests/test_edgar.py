"""SEC lookups and full-text search, against a local server standing in for the SEC."""

import urllib.error

import pytest

from pitconstituents.sources.edgar import Candidate, pick_dominant, search_cik, sec_lookup

AGENT = 'pitconstituents-tests test@example.com'


def hit(score, *ciks):
    return {'_score': score, '_source': {'ciks': list(ciks)}}


GATES = dict(min_score=50.0, min_dominance=1.2)


class TestPickDominant:
    def test_a_clear_leader_wins(self):
        cik, scores = pick_dominant([hit(300, '0000000006'), hit(60, '0000000006', '0000004515'),
                                     hit(20, '0000004515')], **GATES)
        assert cik == '0000000006'
        assert scores == (('0000000006', 360.0), ('0000004515', 80.0))

    def test_too_little_relevance_is_no_answer(self):
        assert pick_dominant([hit(23, '0000000001')], **GATES)[0] is None

    def test_a_near_tie_is_no_answer(self):
        assert pick_dominant([hit(100, '0000000001'), hit(99, '0000000002')],
                             **GATES)[0] is None

    def test_nothing_found(self):
        assert pick_dominant([], **GATES) == (None, ())

    def test_cik_widths_are_normalised_and_junk_skipped(self):
        cik, scores = pick_dominant([hit(80, '6201'), hit(10, 'n/a')], **GATES)
        assert (cik, scores) == ('0000006201', (('0000006201', 80.0),))


def test_search_asks_for_the_quoted_ticker_and_caches_the_answer(server, tmp_path):
    server.json('/LATEST/search-index', {'hits': {'hits': [hit(400, '0000000006')]}})
    url = f'{server.base}/LATEST/search-index'
    pauses = []
    first = search_cik('OLDQ', user_agent=AGENT, url=url, cache_dir=tmp_path,
                       pause=lambda: pauses.append(1))
    second = search_cik('OLDQ', user_agent=AGENT, url=url, cache_dir=tmp_path,
                        pause=lambda: pauses.append(1))
    assert first == second == Candidate('OLDQ', '0000000006', (('0000000006', 400.0),), 1)
    assert first.top_score == 400.0
    (path, agent), = server.requests
    assert 'q=%22OLDQ%22' in path and 'forms=8-K%2C10-K%2C10-Q' in path
    assert agent == AGENT
    assert pauses == [1]                       # the cached answer needed no courtesy pause


def test_a_failed_search_raises_and_is_not_cached(server, tmp_path):
    server.json('/LATEST/search-index', {}, status=500)
    url = f'{server.base}/LATEST/search-index'
    with pytest.raises(urllib.error.HTTPError):
        search_cik('OLDQ', user_agent=AGENT, url=url, cache_dir=tmp_path, pause=lambda: None)
    assert list(tmp_path.iterdir()) == []


def test_the_current_ticker_table(server):
    server.json('/files/company_tickers.json', {
        '0': {'cik_str': 320193, 'ticker': 'AAPL', 'title': 'Apple Inc.'},
        '1': {'cik_str': 1067983, 'ticker': 'BRK-B', 'title': 'Berkshire Hathaway'},
        '2': {'cik_str': 1067983, 'ticker': 'BRK-A', 'title': 'Berkshire Hathaway'},
    })
    lookup = sec_lookup(user_agent=AGENT, url=f'{server.base}/files/company_tickers.json')
    assert lookup('AAPL') == '0000320193'
    assert lookup('BRK.B') == lookup('brk-b') == '0001067983'   # snapshot files write a dot
    assert lookup('GONE') is None


@pytest.mark.parametrize('agent', ['', '   '])
def test_the_sec_needs_to_know_who_is_asking(agent):
    with pytest.raises(ValueError, match='User-Agent'):
        sec_lookup(user_agent=agent)
    with pytest.raises(ValueError, match='User-Agent'):
        search_cik('AAA', user_agent=agent)
