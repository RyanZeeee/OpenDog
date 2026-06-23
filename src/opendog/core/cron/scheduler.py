from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from opendog.core.cron.definition import CronDef


@dataclass
class DueCron:
    cron: CronDef
    run_minute: str


class CronScheduler:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state: dict = self.load_state()

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            return {}

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def due_crons(self, crons: list[CronDef], now: datetime) -> list[DueCron]:
        run_minute = minute_key(now)
        due: list[DueCron] = []
        for cron in crons:
            if not cron.enabled:
                continue
            if cron.min_interval_minutes < 1:
                continue
            if not schedule_respects_min_interval(cron.schedule, cron.min_interval_minutes):
                continue
            if not cron_matches(cron.schedule, now):
                continue
            if self.state.get(cron.id, {}).get("last_run_minute") == run_minute:
                continue
            due.append(DueCron(cron=cron, run_minute=run_minute))
        return due

    def mark_ran(self, cron_id: str, run_minute: str) -> None:
        self.state.setdefault(cron_id, {})["last_run_minute"] = run_minute
        self.save_state()


def minute_key(now: datetime) -> str:
    return now.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def cron_matches(schedule: str, now: datetime) -> bool:
    fields = schedule.split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    values = [
        now.minute,
        now.hour,
        now.day,
        now.month,
        (now.weekday() + 1) % 7,
    ]
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    return all(
        field_matches(field, value, min_value, max_value)
        for field, value, (min_value, max_value) in zip(fields, values, ranges)
    )


def field_matches(field: str, value: int, min_value: int, max_value: int) -> bool:
    for part in field.split(","):
        if value in expand_field(part.strip(), min_value, max_value):
            return True
        if max_value == 7 and value == 0 and 7 in expand_field(part.strip(), min_value, max_value):
            return True
    return False


def expand_field(field: str, min_value: int, max_value: int) -> set[int]:
    if not field:
        return set()
    if "/" in field:
        base, step_text = field.split("/", 1)
        try:
            step = int(step_text)
        except ValueError:
            return set()
    else:
        base, step = field, 1

    if step <= 0:
        return set()
    if base == "*":
        start, end = min_value, max_value
    elif "-" in base:
        start_text, end_text = base.split("-", 1)
        try:
            start, end = int(start_text), int(end_text)
        except ValueError:
            return set()
    else:
        try:
            value = int(base)
        except ValueError:
            return set()
        start, end = value, value

    start = max(min_value, start)
    end = min(max_value, end)
    if start > end:
        return set()
    return set(range(start, end + 1, step))


def schedule_respects_min_interval(schedule: str, min_interval_minutes: int) -> bool:
    fields = schedule.split()
    if len(fields) != 5:
        return False
    minute_field = fields[0]
    if minute_field == "*":
        return min_interval_minutes <= 1
    if minute_field.startswith("*/"):
        try:
            return int(minute_field[2:]) >= min_interval_minutes
        except ValueError:
            return False
    return True
