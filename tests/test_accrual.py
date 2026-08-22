from datetime import date, timedelta

from rota.services.fill.accrual import (due_through, epoch_for, week_monday,
                                        weekly_rate)
from rota.models import CoverageRule

MON = date(2026, 7, 20)


def _due_sequence(rate, weeks):
    return [due_through(rate, MON, MON + timedelta(days=7 * i))
            for i in range(weeks)]


def test_week_monday():
    assert week_monday(date(2026, 7, 22)) == MON  # Wednesday -> its Monday
    assert week_monday(MON) == MON


def test_epoch_is_monday_of_jan1_week():
    assert epoch_for(date(2026, 3, 15)) == date(2025, 12, 29)  # 1 Jan 2026 is a Thursday


def test_full_time_weekly_rate_due_every_week():
    assert _due_sequence(1.0, 4) == [1, 2, 3, 4]


def test_half_wte_alternates_weeks():
    # 0.5/week -> due in weeks 2, 4, 6, 8 (1-based)
    assert _due_sequence(0.5, 8) == [0, 1, 1, 2, 2, 3, 3, 4]


def test_point_six_wte_averages_out():
    # 0.6/week over 5 weeks -> 3 sessions
    assert _due_sequence(0.6, 5) == [0, 1, 1, 2, 3]


def test_monthly_rate_conversion():
    class R:
        frequency = CoverageRule.Frequency.PER_MONTH
        count = 2
    assert abs(weekly_rate(R()) - 2 * 12 / 52.18) < 1e-9

    class R2:
        frequency = CoverageRule.Frequency.PER_WEEK
        count = 2
    assert weekly_rate(R2()) == 2

    class R3:
        frequency = CoverageRule.Frequency.PER_SLOT
        count = 1
    assert weekly_rate(R3()) is None


def test_due_before_anchor_is_zero():
    assert due_through(1.0, MON, MON - timedelta(days=7)) == 0
