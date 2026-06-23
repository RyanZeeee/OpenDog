from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opendog.core.cron.definition import CronDef
from opendog.utils.def_loader import parse_definition


def discover_crons(
    crons_dir: Path,
    *,
    default_agent: str,
) -> list[CronDef]:
    if not crons_dir.exists():
        return []

    crons: list[CronDef] = []
    for cron_file in sorted(crons_dir.glob("*/CRON.md")):
        cron_def = load_cron(cron_file, default_agent=default_agent)
        if cron_def is not None:
            crons.append(cron_def)
    return crons


def load_cron(path: Path, *, default_agent: str) -> CronDef | None:
    metadata, body = parse_definition(path.read_text(encoding="utf-8"))
    cron_id = path.parent.name
    schedule = str(metadata.get("schedule") or "").strip()
    if not schedule:
        return None

    deliver_to = metadata.get("deliver_to") or {}
    if not isinstance(deliver_to, dict):
        deliver_to = {"type": str(deliver_to)}

    return CronDef(
        id=cron_id,
        name=str(metadata.get("name") or cron_id),
        description=str(metadata.get("description") or ""),
        agent=str(metadata.get("agent") or default_agent),
        schedule=schedule,
        enabled=bool(metadata.get("enabled", True)),
        one_off=bool(metadata.get("one_off", False)),
        min_interval_minutes=int(metadata.get("min_interval_minutes", 5)),
        deliver_to=deliver_to,
        prompt=body.strip(),
        path=path,
        metadata=dict(metadata),
    )


def disable_cron(cron: CronDef) -> None:
    metadata: dict[str, Any] = dict(cron.metadata)
    metadata["enabled"] = False
    text = cron.path.read_text(encoding="utf-8")
    _old_metadata, body = parse_definition(text)
    updated = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + body.strip()
        + "\n"
    )
    cron.path.write_text(updated, encoding="utf-8")
