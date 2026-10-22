"""The changes-table parser, on made-up rows in the page's current and older layouts."""

from datetime import date

import pytest

from pitconstituents.sources.wikipedia import Change, fetch_changes, parse_changes

# The current layout: two heading rows, "Added" and "Removed" spanning ticker and
# security, a Refs column, footnote markers, and a row whose Refs cell is missing.
CURRENT = '''
<table class="wikitable sortable" id="constituents"><tr><th>Symbol</th></tr>
<tr><td>AAA</td></tr></table>
<table class="wikitable sortable" id="changes"><tbody>
<tr><th rowspan="2" data-sort-type="date">Effective Date</th><th colspan="2">Added</th>
    <th colspan="2">Removed</th><th rowspan="2">Reason</th><th rowspan="2">Refs</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
<tr><td>October 6, 2025</td><td>NEW</td><td>New Co</td><td>OLD</td><td>Old Co</td>
    <td>Old Co acquired.<sup>[a]</sup></td><td><sup>[2]</sup></td></tr>
<tr><td>October 6, 2025</td><td></td><td></td><td>LOW</td><td>Low Co</td>
    <td>Market capitalization change.</td><td>[2]</td></tr>
<tr><td>September 2, 2024</td><td>AAA<sup>[b]</sup></td><td>A Co</td><td>BBB</td><td>B Co</td>
    <td>Spin-off.</td></tr>
<tr><td>Not a date</td><td>XXX</td><td>X Co</td><td></td><td></td><td></td><td></td></tr>
</tbody></table>
'''

# An older layout: no id, the date spanning the rows of one day's changes.
OLDER = '''
<table class="wikitable"><tr><th rowspan="2">Date</th><th colspan="2">Added</th>
<th colspan="2">Removed</th><th rowspan="2">Reason</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
<tr><td rowspan="2">2023-03-15</td><td>PPP</td><td>P Co</td><td>SSS</td><td>S Co</td>
    <td rowspan="2">Receiverships.</td></tr>
<tr><td>QQQ</td><td>Q Co</td><td>TTT</td><td>T Co</td></tr>
<tr><td>2023-05-04</td><td>RRR</td><td>R Co</td><td>UUU</td><td>U Co</td><td>Seized.</td></tr>
</table>
'''


def test_the_current_layout():
    assert parse_changes(CURRENT) == [
        Change(date(2024, 9, 2), 'AAA', 'BBB', 'Spin-off.'),
        Change(date(2025, 10, 6), 'NEW', 'OLD', 'Old Co acquired.'),
        Change(date(2025, 10, 6), None, 'LOW', 'Market capitalization change.'),
    ]


def test_an_older_layout_with_spanning_dates_and_no_id():
    assert parse_changes(OLDER) == [
        Change(date(2023, 3, 15), 'PPP', 'SSS', 'Receiverships.'),
        Change(date(2023, 3, 15), 'QQQ', 'TTT', 'Receiverships.'),
        Change(date(2023, 5, 4), 'RRR', 'UUU', 'Seized.'),
    ]


@pytest.mark.parametrize('html', [
    '<table class="wikitable"><tr><th>Symbol</th></tr><tr><td>AAA</td></tr></table>',
    '<table id="changes"><tr><th>When</th><th>Added</th><th>Removed</th></tr></table>',
    '<p>no tables at all</p>',
])
def test_a_page_that_changed_shape_says_so(html):
    with pytest.raises(LookupError):
        parse_changes(html)


def test_fetching_needs_a_user_agent():
    with pytest.raises(ValueError, match='User-Agent'):
        fetch_changes(user_agent=' ')


def test_a_table_nested_in_a_cell_does_not_take_the_cell_with_it():
    html = CURRENT.replace('<td>Spin-off.</td>',
                           '<td>Spin-off<table><tr><td>inner</td></tr></table>.</td>')
    rows = parse_changes(html)
    assert rows[0] == Change(date(2024, 9, 2), 'AAA', 'BBB', 'Spin-off.')
