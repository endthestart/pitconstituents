"""Event shapes, and loading them from JSON and TOML."""

import json
from datetime import UTC, date, datetime

import pytest

from pitconstituents import Action, Event, load_events

SOURCE = 'https://example.com/filing'


def event(**fields):
    base = dict(id='e1', date=date(2024, 3, 18), source_url=SOURCE)
    return Event(**(base | fields))


class TestShapes:
    def test_each_action_needs_its_own_fields(self):
        assert event(action='add', ticker='AAA', entity_cik='0000000001').action is Action.ADD
        event(action='rename', ticker_before='OLD', ticker_after='NEW', entity_cik='0000000002')
        event(action='ticker-reuse', ticker='WWW', entity_cik_before='0000000003',
              entity_cik_after='0000000004')

    @pytest.mark.parametrize(('fields', 'message'), [
        (dict(action='add', ticker='AAA'), 'needs entity_cik'),
        (dict(action='remove', entity_cik='0000000001'), 'needs ticker'),
        (dict(action='rename', ticker_after='NEW', entity_cik='0000000001'), 'ticker_before'),
        (dict(action='rename', ticker_before='X', ticker_after='X', entity_cik='0000000001'),
         'two different tickers'),
        (dict(action='ticker-reuse', ticker='W', entity_cik_before='0000000003',
              entity_cik_after='0000000003'), 'two different CIKs'),
        (dict(action='add', ticker='AAA', entity_cik='12345'), '10 digits'),
        (dict(action='add', ticker='AAA', entity_cik='0000000001', source_url=''),
         'source_url'),
    ])
    def test_incomplete_or_inconsistent_events_are_refused(self, fields, message):
        with pytest.raises(ValueError, match=message):
            event(**fields)

    def test_unknown_actions_and_bad_dates_are_refused(self):
        with pytest.raises(ValueError):
            event(action='merge', ticker='AAA', entity_cik='0000000001')
        with pytest.raises(TypeError):
            event(action='add', ticker='AAA', entity_cik='0000000001', date='2024-03-18')
        with pytest.raises(TypeError):
            event(action='add', ticker='AAA', entity_cik='0000000001',
                  date=datetime(2024, 3, 18, tzinfo=UTC))


class TestFromDict:
    def test_iso_dates_and_the_older_spellings_are_accepted(self):
        e = Event.from_dict({'id': 'w', 'date': '2009-01-02', 'action': 'spinoff-ticker-reuse',
                             'ticker': 'WWW', 'entity_cik_before': '0000000003',
                             'entity_cik_after': '0000000004', 'source_url': SOURCE,
                             'rationale': 'why'})
        assert (e.date, e.action, e.note) == (date(2009, 1, 2), Action.TICKER_REUSE, 'why')

    def test_a_misspelled_field_is_an_error_not_a_silent_drop(self):
        with pytest.raises(ValueError, match='unknown fields'):
            Event.from_dict({'id': 'x', 'date': '2024-01-02', 'action': 'add', 'ticker': 'A',
                             'entitycik': '0000000001', 'source_url': SOURCE})


ENTRIES = [
    {'id': 'add-AAA', 'date': '2020-12-21', 'action': 'add', 'ticker': 'AAA',
     'entity_cik': '0000000001', 'source_url': SOURCE},
    {'id': 'rm-BBB', 'date': '2023-03-15', 'action': 'remove', 'ticker': 'BBB',
     'entity_cik': '0000000002', 'source_url': SOURCE, 'note': 'receivership'},
]

TOML = '''
[[events]]
id = "add-AAA"
date = 2020-12-21
action = "add"
ticker = "AAA"
entity_cik = "0000000001"
source_url = "https://example.com/filing"

[[events]]
id = "rm-BBB"
date = 2023-03-15
action = "remove"
ticker = "BBB"
entity_cik = "0000000002"
source_url = "https://example.com/filing"
note = "receivership"
'''


class TestLoad:
    def test_json_list_json_mapping_and_toml_agree(self, tmp_path):
        (tmp_path / 'a.json').write_text(json.dumps(ENTRIES))
        (tmp_path / 'b.json').write_text(json.dumps({'events': ENTRIES}))
        (tmp_path / 'c.toml').write_text(TOML)
        loaded = [load_events(tmp_path / name) for name in ('a.json', 'b.json', 'c.toml')]
        assert loaded[0] == loaded[1] == loaded[2]
        assert [e.id for e in loaded[0]] == ['add-AAA', 'rm-BBB']

    def test_duplicate_ids_and_other_formats_are_refused(self, tmp_path):
        (tmp_path / 'dup.json').write_text(json.dumps(ENTRIES + ENTRIES[:1]))
        with pytest.raises(ValueError, match='duplicate'):
            load_events(tmp_path / 'dup.json')
        (tmp_path / 'events.yaml').write_text('events: []')
        with pytest.raises(ValueError, match='.json or .toml'):
            load_events(tmp_path / 'events.yaml')
        (tmp_path / 'odd.json').write_text('{"items": []}')
        with pytest.raises(TypeError):
            load_events(tmp_path / 'odd.json')
