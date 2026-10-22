"""Events against snapshots: the asymmetric tolerance, spells, and the report.

The ``history`` fixture (conftest) has snapshots on weekdays in October and November
2025: BBB leaves after 2025-10-15, CCC joins on 2025-10-20, DDD leaves after
2025-10-03 and returns on 2025-11-10, and EEE first appears on 2025-11-03 after a
seven-business-day gap between snapshots.
"""

from datetime import date

import pytest
from conftest import snaps

from pitconstituents import (
    Event,
    Status,
    ValidationError,
    business_days,
    cross_check,
    describe,
    validate,
)
from pitconstituents.sources.wikipedia import Change

SOURCE = 'https://example.com/filing'


def add(ticker, on, cik='0000000001'):
    return Event(f'add-{ticker}-{on}', on, 'add', SOURCE, ticker=ticker, entity_cik=cik)


def remove(ticker, on, cik='0000000001'):
    return Event(f'rm-{ticker}-{on}', on, 'remove', SOURCE, ticker=ticker, entity_cik=cik)


def one(history, event, tolerance=3):
    (check,) = validate(history, [event], tolerance=tolerance).checks
    return check


class TestBusinessDays:
    @pytest.mark.parametrize(('start', 'end', 'expected'), [
        (date(2025, 10, 20), date(2025, 10, 27), 5),    # Monday to Monday
        (date(2025, 10, 18), date(2025, 10, 20), 0),    # Saturday to Monday
        (date(2025, 10, 17), date(2025, 10, 20), 1),    # Friday to Monday
        (date(2025, 10, 20), date(2025, 10, 20), 0),
        # numpy.busday_count when end is earlier: minus the weekdays in (end, start]
        (date(2025, 10, 27), date(2025, 10, 20), -5),
        (date(2025, 10, 22), date(2025, 10, 18), -3),   # Wednesday back to Saturday
        (date(2025, 10, 19), date(2025, 10, 13), -4),   # Sunday back to Monday
    ])
    def test_weekdays_between(self, start, end, expected):
        assert business_days(start, end) == expected


class TestAdd:
    def test_the_first_snapshot_after_the_event_confirms_it(self, history):
        check = one(history, add('CCC', date(2025, 10, 20)))
        assert (check.status, check.observed, check.offset) == (Status.PASS, date(2025, 10, 21), 1)

    def test_arriving_in_the_first_snapshot_after_a_gap_passes(self, history):
        """The next snapshot can be weeks away: lateness it explains is the cadence."""
        check = one(history, add('EEE', date(2025, 10, 27)))
        assert (check.status, check.observed, check.offset) == (Status.PASS, date(2025, 11, 3), 5)

    def test_missing_from_that_snapshot_and_arriving_later_is_drift(self, history):
        """DDD should be in the 2025-11-03 snapshot if it joined on 2025-10-23; it is not."""
        check = one(history, add('DDD', date(2025, 10, 23)))
        assert (check.status, check.observed, check.offset) == (
            Status.DRIFT, date(2025, 11, 12), 14)

    def test_turning_up_a_little_early_is_within_tolerance(self, history):
        check = one(history, add('CCC', date(2025, 10, 24)))
        assert (check.status, check.offset) == (Status.PASS, -3)

    def test_being_a_member_well_before_the_addition_is_drift(self, history):
        check = one(history, add('CCC', date(2025, 10, 29)))
        assert check.status is Status.DRIFT
        assert (check.observed, check.offset) == (date(2025, 10, 21), -6)

    def test_never_appearing_is_a_failure(self, history):
        check = one(history, add('ZZZ', date(2025, 10, 20)))
        assert (check.status, check.observed, check.offset) == (Status.MISSING, None, None)

    def test_a_returning_member_is_judged_on_its_return(self, history):
        """DDD was a member until early October; its November return is no drift, which a
        check against its first appearance overall would wrongly report."""
        check = one(history, add('DDD', date(2025, 11, 10)))
        assert (check.status, check.observed) == (Status.PASS, date(2025, 11, 12))


class TestRemove:
    def test_leaving_on_time(self, history):
        check = one(history, remove('BBB', date(2025, 10, 16)))
        assert (check.status, check.observed, check.offset) == (Status.PASS, date(2025, 10, 15), -1)

    def test_leaving_a_little_late_is_within_tolerance(self, history):
        check = one(history, remove('BBB', date(2025, 10, 10)))
        assert (check.status, check.offset) == (Status.PASS, 3)

    def test_still_a_member_well_after_removal_is_drift(self, history):
        check = one(history, remove('BBB', date(2025, 10, 7)))
        assert check.status is Status.DRIFT
        assert (check.observed, check.offset) == (date(2025, 10, 15), 6)

    def test_leaving_in_the_gap_before_the_window_passes(self, history):
        """The last snapshot before the window still has BBB; the first inside does not."""
        check = one(history, remove('BBB', date(2025, 10, 22)))
        assert (check.status, check.observed, check.offset) == (
            Status.PASS, date(2025, 10, 15), -5)

    def test_leaving_well_before_the_removal_is_drift(self, history):
        check = one(history, remove('DDD', date(2025, 10, 23)))
        assert (check.status, check.observed, check.offset) == (
            Status.DRIFT, date(2025, 10, 3), -14)

    def test_never_a_member_before_its_removal_is_a_failure(self, history):
        assert one(history, remove('ZZZ', date(2025, 10, 20))).status is Status.MISSING


class TestRename:
    rename = Event('OLD-NEW', date(2022, 6, 9), 'rename', SOURCE, ticker_before='OLD',
                   ticker_after='NEW', entity_cik='0000000002')
    raw = snaps((date(2022, 6, 3), 'AAA OLD'), (date(2022, 6, 7), 'AAA OLD'),
                (date(2022, 6, 10), 'AAA OLD'), (date(2022, 6, 14), 'AAA OLD'))

    def test_the_new_ticker_is_checked_after_the_rename_is_applied(self):
        events = [self.rename]
        check = one(self.raw.with_events(events), self.rename)
        assert (check.status, check.ticker, check.observed) == (
            Status.PASS, 'NEW', date(2022, 6, 10))

    def test_without_the_overlay_the_new_ticker_is_missing(self):
        assert one(self.raw, self.rename).status is Status.MISSING


def test_ticker_reuse_is_not_a_membership_check(history):
    reuse = Event('WWW', date(2025, 10, 20), 'ticker-reuse', SOURCE, ticker='WWW',
                  entity_cik_before='0000000003', entity_cik_after='0000000004')
    assert validate(history, [reuse]).checks == ()


def test_events_outside_the_history_are_uncovered(history):
    report = validate(history, [add('AAA', date(2025, 9, 1)), remove('AAA', date(2026, 1, 5))])
    assert [c.status for c in report.checks] == [Status.UNCOVERED, Status.UNCOVERED]
    assert report.ok


class TestReport:
    events = (add('CCC', date(2025, 10, 20)), add('CCC', date(2025, 10, 29)),
              add('ZZZ', date(2025, 10, 20)), remove('BBB', date(2025, 10, 16)),
              remove('BBB', date(2025, 10, 10)))

    def test_failures_drift_and_slack(self, history):
        report = validate(history, self.events)
        assert [c.ticker for c in report.failures] == ['ZZZ']
        assert [c.event_id for c in report.drift] == ['add-CCC-2025-10-29']
        assert not report.ok
        slack = report.slack()
        assert (slack.count, slack.max, slack.median, slack.p99) == (3, 3, 1.0, 3)

    def test_a_failing_report_can_refuse_the_history(self, history):
        with pytest.raises(ValidationError, match='add-ZZZ-2025-10-20: add ZZZ .* missing'):
            validate(history, self.events).raise_for_failures()
        validate(history, self.events[:1]).raise_for_failures()

    def test_a_check_describes_itself(self, history):
        drift = validate(history, self.events).drift[0]
        assert describe(drift) == ('add-CCC-2025-10-29: add CCC on 2025-10-29 drift; '
                                   'history shows 2025-10-21 (-6 business days)')

    def test_tolerance_is_a_parameter(self, history):
        assert one(history, add('CCC', date(2025, 10, 24)), tolerance=2).status is Status.DRIFT
        with pytest.raises(ValueError):
            validate(history, self.events, tolerance=-1)

    def test_an_empty_report(self, history):
        report = validate(history, [])
        assert report.ok and report.slack().count == 0


def test_wikipedia_rows_become_warnings_of_the_same_kind(history):
    changes = [Change(date(2025, 10, 20), 'CCC', 'BBB'), Change(date(2025, 10, 7), None, 'BBB'),
               Change(date(1990, 1, 2), 'OLD', None)]
    report = cross_check(history, changes)
    assert [(c.action, c.ticker, c.status) for c in report.checks] == [
        ('add', 'CCC', Status.PASS), ('remove', 'BBB', Status.PASS),
        ('remove', 'BBB', Status.DRIFT), ('add', 'OLD', Status.UNCOVERED)]
    assert report.checks[0].event_id == 'wikipedia:2025-10-20:add:CCC'
