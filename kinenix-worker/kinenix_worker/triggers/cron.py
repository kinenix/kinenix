"""Five-field cron expressions (minute hour day-of-month month day-of-week), in the worker's local time.

Each field accepts *, a number, a range a-b, a list a,b,c, and a step */n or a-b/n. Day of week is 0-6 with
0 = Sunday (7 is also Sunday). As in standard cron, when both day of month and day of week are restricted,
a day matches if either one does.

Examples: "0 8 1 * *" (08:00 on the 1st of every month), "30 7 * * 1-5" (07:30 Monday to Friday).
"""
from datetime import datetime, timedelta
from typing import FrozenSet, Optional, Tuple

_FIELDS: Tuple[Tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)


def _parse_field(text: str, name: str, low: int, high: int) -> FrozenSet[int]:
    values = set()
    for part in text.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError(f"cron {name}: invalid step '/{step_text}'")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"cron {name}: invalid range '{part}'")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = int(part)
            # "5/15" means from 5 to the end in steps of 15
            end = high if step > 1 else start
        else:
            raise ValueError(f"cron {name}: invalid value '{part}'")
        if not (low <= start <= high and low <= end <= high and start <= end):
            raise ValueError(f"cron {name}: '{part}' is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


class CronExpression:
    def __init__(self, expression: str):
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError(
                f"cron expression '{expression}' must have 5 fields: minute hour day-of-month month day-of-week"
            )
        self.expression = expression
        parsed = [_parse_field(p, *field) for p, field in zip(parts, _FIELDS)]
        self.minutes, self.hours, self.days, self.months, weekdays = parsed
        self.weekdays = frozenset(d % 7 for d in weekdays)  # 7 and 0 are both Sunday
        self._day_restricted = parts[2] != "*"
        self._weekday_restricted = parts[4] != "*"

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self.minutes or moment.hour not in self.hours or moment.month not in self.months:
            return False
        cron_weekday = (moment.weekday() + 1) % 7  # Python Monday=0 -> cron Sunday=0
        day_ok = moment.day in self.days
        weekday_ok = cron_weekday in self.weekdays
        if self._day_restricted and self._weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def next_after(self, moment: datetime) -> Optional[datetime]:
        """The first matching minute after `moment`, within about four years (for logs), or None."""
        current = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(4 * 366 * 24 * 60):
            if self.matches(current):
                return current
            current += timedelta(minutes=1)
        return None

    def __str__(self) -> str:
        return self.expression
