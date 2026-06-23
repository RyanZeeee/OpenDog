from __future__ import annotations

from pathlib import Path

import yaml


def parse_definition(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text.strip()

    lines = text.splitlines()
    end_index = None

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}, text.strip()

    metadata_text = "\n".join(lines[1:end_index])
    body_text = "\n".join(lines[end_index + 1 :])
    metadata = yaml.safe_load(metadata_text) or {}
    return metadata, body_text.strip()
