import math
from datetime import date, timedelta

from rota.models import CoverageRule


def week_monday(day):
    return day - timedelta(days=day.weekday())


def epoch_for(start):
    return week_monday(date(start.year, 1, 1))


def weekly_rate(rule):
    if rule.frequency == CoverageRule.Frequency.PER_WEEK:
        return float(rule.count)
    if rule.frequency == CoverageRule.Frequency.PER_MONTH:
        return rule.count * 12 / 52.18
    return None


def due_through(rate, anchor_monday, monday):
    if monday < anchor_monday:
        return 0
    weeks = (monday - anchor_monday).days // 7 + 1
    return math.floor(rate * weeks + 1e-9)
