"""Membership as of a date, a rename, a reused ticker, and a check against hand-checked events.

Everything is made up and offline: four snapshots of a tiny index and three events.
Run with ``uv run python examples/as_of.py``. For the real S&P 500 history, see the
README: ``fja05680.load(cache_dir=...)`` gives the same object.
"""

from datetime import date

from pitconstituents import Event, Membership, build_cik_map, cik_on, describe, validate

HISTORY = '''date,tickers
2024-03-01,"ALFA,BRAV,OLDN,WHSK"
2024-03-08,"ALFA,BRAV,OLDN,WHSK"
2024-03-18,"ALFA,BRAV,OLDN,CHRL"
2024-03-25,"ALFA,BRAV,OLDN,CHRL"
'''
SOURCE = 'https://example.com/announcement'
EVENTS = [
    # CHRL replaced WHSK effective 2024-03-18.
    Event('CHRL-add', date(2024, 3, 18), 'add', SOURCE, ticker='CHRL',
          entity_cik='0000000003'),
    Event('WHSK-remove', date(2024, 3, 18), 'remove', SOURCE, ticker='WHSK',
          entity_cik='0000000004'),
    # OLDN renamed itself NEWN on 2024-03-20; the history file still says OLDN.
    Event('OLDN-NEWN', date(2024, 3, 20), 'rename', SOURCE, ticker_before='OLDN',
          ticker_after='NEWN', entity_cik='0000000005'),
    # BRAV the ticker passed to a different company on 2024-03-11.
    Event('BRAV-reuse', date(2024, 3, 11), 'ticker-reuse', SOURCE, ticker='BRAV',
          entity_cik_before='0000000006', entity_cik_after='0000000007'),
]

history = Membership.from_wide_csv(HISTORY).with_events(EVENTS)
for day in (date(2024, 2, 1), date(2024, 3, 12), date(2024, 3, 25)):
    print(day, sorted(history.members(day)))

report = validate(history, EVENTS)
print('checks:', ', '.join(f'{c.event_id} {c.status}' for c in report.checks))
for check in report.drift + report.failures:
    print('  ', describe(check))

current = {'ALFA': '0000000001', 'BRAV': '0000000007', 'CHRL': '0000000003',
           'NEWN': '0000000005'}
cik_map = build_cik_map(history.tickers(), current.get)
print('unresolved:', [t for t, cik in cik_map.items() if cik is None])
print('BRAV on 2024-03-08 was', cik_on('BRAV', date(2024, 3, 8), cik_map, EVENTS),
      'and on 2024-03-18', cik_on('BRAV', date(2024, 3, 18), cik_map, EVENTS))
