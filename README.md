# pitconstituents

Which companies were in the S&P 500 on a given day, as it was known that day, keyed by
an identifier that survives renames, and checked against a record you can trust.

A backtest that picks from today's index members has already chosen the survivors:
the companies that went bankrupt, were acquired or were demoted are not in today's list,
and leaving them out flatters every strategy that buys the index's constituents.
Point-in-time membership fixes that. The details are where it goes wrong, and they are
what this package is for:

- **As of a date, never after it.** Membership comes from dated snapshots, and a query
  returns the latest snapshot on or before the date. Before the first snapshot it is
  empty; nothing is known before it happened.
- **Tickers are labels; CIKs are companies.** FB became META without the company
  changing; WM meant Washington Mutual before it meant Waste Management. Anything that
  must follow a company through time keys on its SEC CIK. Renames are applied to the
  history, and a ticker that changed hands resolves to the CIK of its era.
- **A gap stays a gap.** A ticker whose CIK cannot be resolved is reported as `None`,
  never dropped: dropping it would remove a real member and put the survivorship bias
  back.
- **Histories drift, and the drift is measured.** Snapshot histories are compiled by
  hand. `validate` checks one against a short list of events you have checked against
  primary sources (an 8-K, the index provider's announcement), with a tolerance for
  the snapshot cadence. A member the history never shows is a failure; a date that is
  off is reported as drift, with its size.
- **A second opinion, not a referee.** Wikipedia's table of changes can be cross-checked
  the same way, and its disagreements come back as warnings.
- **Nothing is bundled.** Every dataset is read from its upstream at run time, pinned
  where it can be, under its own terms (see "Data and licences").

No dependencies: the standard library only. edgartools is an optional extra for an
offline SEC ticker table.

```python
from datetime import date
from pitconstituents import Event, Membership, validate

history = Membership.from_wide_csv('''date,tickers
2024-03-01,"ALFA,BRAV,OLDN,WHSK"
2024-03-08,"ALFA,BRAV,OLDN,WHSK"
2024-03-18,"ALFA,BRAV,OLDN,CHRL"
2024-03-25,"ALFA,BRAV,OLDN,CHRL"
''')
source = 'https://example.com/announcement'
events = [
    Event('CHRL-add', date(2024, 3, 18), 'add', source, ticker='CHRL', entity_cik='0000000003'),
    Event('WHSK-remove', date(2024, 3, 18), 'remove', source, ticker='WHSK',
          entity_cik='0000000004'),
    Event('OLDN-NEWN', date(2024, 3, 20), 'rename', source, ticker_before='OLDN',
          ticker_after='NEWN', entity_cik='0000000005'),
]
history = history.with_events(events)          # OLDN reads as NEWN from 2024-03-20

sorted(history.members(date(2024, 3, 12)))     # ['ALFA', 'BRAV', 'OLDN', 'WHSK']
sorted(history.members(date(2024, 3, 25)))     # ['ALFA', 'BRAV', 'CHRL', 'NEWN']
history.members(date(2024, 2, 1))              # frozenset(): before the first snapshot

report = validate(history, events)
[(c.event_id, c.status, c.offset) for c in report.checks]
# [('CHRL-add', <Status.PASS: 'pass'>, 0), ('WHSK-remove', <Status.PASS: 'pass'>, -6),
#  ('OLDN-NEWN', <Status.PASS: 'pass'>, 3)]
report.raise_for_failures()                    # refuse a history that fails
```

`examples/as_of.py` runs the same history with a reused ticker and CIK resolution.

## The S&P 500

```python
from datetime import date
from pitconstituents import load_events, validate
from pitconstituents.sources import fja05680

events = load_events('events.toml')            # your hand-checked reference events
history = fja05680.load(cache_dir='.cache/sp500').with_events(events)
report = validate(history, events)
report.raise_for_failures()
history.members(date(2008, 9, 12))             # the index the week Lehman failed
history.digest                                 # sha256 of the file, for your records
```

The history is [fja05680/sp500](https://github.com/fja05680/sp500), pinned to one
commit (`fja05680.COMMIT`): snapshots since 1996, roughly every two business days, with
gaps of months in places. Moving the pin is a decision to re-validate, not a routine
update. Any CSV with `date` and `tickers` (comma-separated) columns works the same way:
`Membership.load(path_or_url)`.

## Validation

Each event is checked against the snapshots around it, with `tolerance` business days
(default 3) either side. Beyond that window, a gap between snapshots excuses lateness or
earliness, and nothing else does:

| Event | Passes when | `DRIFT` when | `MISSING` when |
|---|---|---|---|
| add, rename (new ticker) | present inside the window, or in the first snapshot after it | a member in the last snapshot before the window, or only appearing later | never present from the window on |
| remove | present inside the window, or in the last snapshot before it, and gone after | still a member in the first snapshot after the window, or gone before the last snapshot before it | never a member up to the window |

Checks look at the spell an event is about, not a ticker's first and last appearance
overall, so a company that left and rejoined years later is not mistaken for drift.
`ticker-reuse` events concern identity and are not membership checks; events outside the
history's dates are `UNCOVERED`. `report.failures`, `report.drift` and `report.slack()`
(max, median and 99th percentile of the offsets that passed) are for your build log;
`describe(check)` gives one line per check.

`cross_check(history, wikipedia.fetch_changes(user_agent=...))` runs the same checks on
every row of Wikipedia's [changes table](https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500).
Its disagreements are leads, not verdicts: Wikipedia writes today's ticker where the
history wrote the one in use then, lists changes it calls "selected", and is edited by
anyone. On the pinned history it finds, for example, the December 2023 rebalance dated
about two months early, and tickers later reused by other companies.

Events load from TOML or JSON (`load_events`), one table per event:

```toml
[[events]]
id = "TSLA-2020-12-21-add"
date = 2020-12-21
action = "add"                  # add | remove | rename | ticker-reuse
ticker = "TSLA"
entity_cik = "0001318605"
source_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001318605"
note = "Effective before the open on 2020-12-21."
```

A rename takes `ticker_before`, `ticker_after` and the unchanged `entity_cik`; a ticker
reuse takes `ticker`, `entity_cik_before` and `entity_cik_after`. `source_url` is
required: an event nobody can check is not a reference.

## Identity

`build_cik_map(tickers, lookup, overrides=...)` resolves each ticker: your overrides
first, then a lookup of current tickers, else `None`. `cik_on(ticker, day, cik_map,
events)` applies `ticker-reuse` events, so a reused ticker points at the company of its
era.

| Lookup | |
|---|---|
| `edgar.sec_lookup(user_agent=...)` | the SEC's current `company_tickers.json`, fetched once (cacheable) |
| `edgar.edgartools_lookup()` | edgartools' bundled copy, mostly offline (`pitconstituents[edgartools]`) |
| any `Callable[[str], str \| None]` | your own |

A current-ticker lookup cannot be point-in-time: it maps a ticker to whoever holds it
today. Delisted, renamed and reused tickers need overrides. `edgar.search_cik(ticker,
user_agent=...)` searches EDGAR's full-text index for 8-Ks, 10-Ks and 10-Qs that quote
the ticker and ranks the filers, which finds most old tickers. Its answer is a
candidate, never an override as it stands: a short ticker that is also a word, or part
of another company's name or ticker, collects relevance for the wrong filer, so check
each candidate against a filing first.

## Data and licences

The code is MIT. No data ships with it; each source is read at run time, and its terms
are yours to keep:

- **fja05680/sp500**: the repository is MIT-licensed. Its README says the 1996-2019
  history came from the download accompanying Andreas Clenow's *Trading Evolved*, and
  later changes are transcribed from Wikipedia and news reports. Read it from GitHub;
  think before redistributing a copy.
- **Wikipedia**: text under CC BY-SA 4.0. If you store or publish what the parser reads,
  attribute Wikipedia and keep the licence. Wikimedia asks automated clients for a
  User-Agent naming the tool and a contact.
- **SEC EDGAR**: US government works, public domain. The SEC's fair-access policy applies
  to every request: a User-Agent with your application and a contact address, under ten
  requests a second. No identity is built in; you pass yours.
- **edgartools** (optional): MIT.

S&P 500 is a trademark of S&P Dow Jones Indices LLC. This project is not affiliated
with, endorsed by, or sponsored by S&P Dow Jones Indices, and uses no data from it.

## What it does not do

No prices, no index weights, no other corporate actions (splits, spin-off share
allocations): membership and identity only. Business days are Monday to Friday, not an
exchange calendar. It does not decide which reference events are true; it tells you
where the history and your events disagree.

## License

MIT.
