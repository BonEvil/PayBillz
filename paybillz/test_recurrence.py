"""Run with: python -m unittest discover -s calendar-delivery/paybillz -v"""

import unittest
from datetime import date, datetime

from paybillz.recurrence import bucket_bounds, occurrences, validate_rule


def d(year, month, day):
    return date(year, month, day)


class RecurrenceTests(unittest.TestCase):
    def assert_occurs(self, anchor, rule, start, end, expected):
        self.assertEqual(occurrences(anchor, rule, start, end), expected)

    def test_once_inclusive_and_no_pre_anchor(self):
        rule = {"kind": "once"}
        self.assert_occurs(d(2026, 1, 2), rule, d(2026, 1, 2), d(2026, 1, 2), [d(2026, 1, 2)])
        self.assert_occurs(d(2026, 1, 2), rule, d(2026, 1, 3), d(2026, 2, 1), [])
        self.assert_occurs(d(2026, 1, 2), rule, d(2025, 1, 1), d(2026, 1, 1), [])

    def test_empty_reversed_window(self):
        self.assert_occurs(d(2026, 1, 1), {"kind": "once"}, d(2026, 2, 1), d(2026, 1, 1), [])

    def test_interval_days_and_weeks(self):
        self.assert_occurs(d(2026, 1, 30), {"kind": "interval", "unit": "days", "every": 3},
                           d(2026, 1, 1), d(2026, 2, 9),
                           [d(2026, 1, 30), d(2026, 2, 2), d(2026, 2, 5), d(2026, 2, 8)])
        self.assert_occurs(d(2026, 12, 25), {"kind": "interval", "unit": "weeks", "every": 2},
                           d(2026, 12, 1), d(2027, 1, 30),
                           [d(2026, 12, 25), d(2027, 1, 8), d(2027, 1, 22)])

    def test_monthly_anchor_clamp_restores_day(self):
        self.assert_occurs(d(2024, 1, 31), {"kind": "interval", "unit": "months", "every": 1},
                           d(2024, 1, 1), d(2024, 4, 30),
                           [d(2024, 1, 31), d(2024, 2, 29), d(2024, 3, 31), d(2024, 4, 30)])
        self.assert_occurs(d(2023, 1, 31), {"kind": "interval", "unit": "months", "every": 2},
                           d(2023, 2, 1), d(2023, 7, 31),
                           [d(2023, 3, 31), d(2023, 5, 31), d(2023, 7, 31)])

    def test_yearly_leap_day_and_year_boundary(self):
        self.assert_occurs(d(2024, 2, 29), {"kind": "interval", "unit": "years", "every": 1},
                           d(2024, 1, 1), d(2028, 3, 1),
                           [d(2024, 2, 29), d(2025, 2, 28), d(2026, 2, 28),
                            d(2027, 2, 28), d(2028, 2, 29)])
        self.assert_occurs(d(2023, 12, 31), {"kind": "interval", "unit": "years", "every": 2},
                           d(2024, 1, 1), d(2027, 1, 1), [d(2025, 12, 31)])

    def test_weekdays_weekend_not_shifted(self):
        self.assert_occurs(d(2026, 11, 14), {"kind": "weekdays", "weekdays": [5, 6]},
                           d(2026, 11, 1), d(2026, 11, 22),
                           [d(2026, 11, 14), d(2026, 11, 15), d(2026, 11, 21), d(2026, 11, 22)])

    def test_monthly_dates_short_months_deduplicate(self):
        self.assert_occurs(d(2023, 1, 30), {"kind": "monthly_dates", "days": [30, 31]},
                           d(2023, 1, 1), d(2023, 4, 30),
                           [d(2023, 1, 30), d(2023, 1, 31), d(2023, 2, 28),
                            d(2023, 3, 30), d(2023, 3, 31), d(2023, 4, 30)])

    def test_selected_months_clamps_and_crosses_year(self):
        self.assert_occurs(d(2023, 1, 1), {"kind": "selected_months", "months": [2, 12], "day": 31},
                           d(2023, 1, 1), d(2024, 3, 1),
                           [d(2023, 2, 28), d(2023, 12, 31), d(2024, 2, 29)])

    def test_ordinal_weekday_first_last_and_missing_fifth(self):
        self.assert_occurs(d(2026, 1, 1), {"kind": "ordinal_weekday", "weekday": 0, "ordinal": 1},
                           d(2026, 1, 1), d(2026, 3, 31),
                           [d(2026, 1, 5), d(2026, 2, 2), d(2026, 3, 2)])
        self.assert_occurs(d(2026, 1, 1), {"kind": "ordinal_weekday", "weekday": 0, "ordinal": -1},
                           d(2026, 1, 1), d(2026, 3, 31),
                           [d(2026, 1, 26), d(2026, 2, 23), d(2026, 3, 30)])
        self.assert_occurs(d(2026, 2, 1), {"kind": "ordinal_weekday", "weekday": 0, "ordinal": 5},
                           d(2026, 2, 1), d(2026, 3, 31), [d(2026, 3, 30)])

    def test_bucket_bounds_interval_and_calendar(self):
        interval = {"kind": "interval", "unit": "weeks", "every": 2}
        self.assertEqual(bucket_bounds(d(2026, 1, 2), interval, d(2026, 1, 16)),
                         (d(2026, 1, 16), d(2026, 1, 30)))
        self.assertEqual(bucket_bounds(d(2026, 1, 2), interval, d(2025, 12, 31)),
                         (None, d(2026, 1, 2)))
        calendar_rule = {"kind": "monthly_dates", "days": [15, 31]}
        self.assertEqual(bucket_bounds(d(2026, 1, 1), calendar_rule, d(2026, 2, 28)),
                         (d(2026, 2, 28), d(2026, 3, 15)))
        self.assertEqual(bucket_bounds(d(2026, 1, 1), {"kind": "once"}, d(2026, 1, 1)),
                         (d(2026, 1, 1), None))

    def test_rule_validation(self):
        invalid = [None, {}, {"kind": "mystery"}, {"kind": []},
                   {"kind": "once", "extra": 1},
                   {"kind": "interval", "unit": "days", "every": 0},
                   {"kind": "interval", "unit": "weeks", "every": True},
                   {"kind": "interval", "unit": "day", "every": 1},
                   {"kind": "weekdays", "weekdays": []},
                   {"kind": "weekdays", "weekdays": [0, 0]},
                   {"kind": "weekdays", "weekdays": [7]},
                   {"kind": "monthly_dates", "days": [0]},
                   {"kind": "monthly_dates", "days": [31, 31]},
                   {"kind": "selected_months", "months": [13], "day": 1},
                   {"kind": "selected_months", "months": [1], "day": 32},
                   {"kind": "ordinal_weekday", "weekday": 6, "ordinal": 0},
                   {"kind": "ordinal_weekday", "weekday": 0, "ordinal": -2}]
        for rule in invalid:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                validate_rule(rule)
        with self.assertRaises(ValueError):
            occurrences(datetime(2026, 1, 1), {"kind": "once"}, d(2026, 1, 1), d(2026, 1, 1))

    def test_date_max_is_safe(self):
        self.assert_occurs(date.max, {"kind": "interval", "unit": "days", "every": 1},
                           date.max, date.max, [date.max])
        self.assertEqual(bucket_bounds(date.max, {"kind": "once"}, date.max), (date.max, None))


if __name__ == "__main__":
    unittest.main()
