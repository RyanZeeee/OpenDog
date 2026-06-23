from __future__ import annotations

import re
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from typing import Optional, Union

from opendog.utils.def_loader import parse_definition


@dataclass
class SkillDef:
    name: str
    description: str
    path: Path


class SkillRegistry:
    def __init__(self, skills: dict[str, SkillDef]) -> None:
        self._skills = skills

    @classmethod
    def load(
        cls,
        skills_dir: Union[str, Path],
        allowed_names: Optional[list[str]] = None,
    ) -> "SkillRegistry":
        skills_path = Path(skills_dir)
        skills = {}
        allowed = set(allowed_names) if allowed_names is not None else None

        if not skills_path.exists():
            return cls(skills)

        for skill_file in sorted(skills_path.glob("*/SKILL.md")):
            metadata, _body = parse_definition(skill_file.read_text(encoding="utf-8"))
            name = metadata.get("name", skill_file.parent.name)
            description = metadata.get("description", "")
            if allowed is not None and name not in allowed and skill_file.parent.name not in allowed:
                continue
            skills[name] = SkillDef(
                name=name,
                description=description,
                path=skill_file.resolve(),
            )

        return cls(skills)

    def list_skills(self) -> dict:
        return {
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "path": str(skill.path),
                }
                for skill in self._skills.values()
            ],
        }

    def find_by_skill_file(self, path: Union[str, Path]) -> Optional[SkillDef]:
        resolved = Path(path).resolve(strict=False)
        for skill in self._skills.values():
            if skill.path == resolved:
                return skill
        return None

    def find_relevant_skill(self, message: str) -> Optional[SkillDef]:
        if not message.strip():
            return None

        normalized_message = self.normalize_text(message)
        best_skill: Optional[SkillDef] = None
        best_score = 0

        for skill in self._skills.values():
            score = self.score_skill_match(skill, normalized_message)
            if score > best_score:
                best_skill = skill
                best_score = score

        if best_score > 0:
            return best_skill
        return None

    def score_skill_match(
        self,
        skill: SkillDef,
        normalized_message: str,
    ) -> int:
        normalized_name = self.normalize_text(skill.name)
        if normalized_name and normalized_name in normalized_message:
            return 100

        shared_tokens = self.shared_description_tokens()
        score = 0
        for token in self.description_tokens(skill.description):
            if token in shared_tokens:
                continue
            if self.message_contains_token(normalized_message, token):
                score += 1
        return score

    def description_tokens(self, description: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[a-z0-9][a-z0-9.+#/-]*", self.normalize_text(description)):
            if len(token) < 3:
                continue
            tokens.add(token)
            for part in re.split(r"[-/+.]", token):
                if len(part) >= 3:
                    tokens.add(part)
        return tokens

    def shared_description_tokens(self) -> set[str]:
        counter: Counter[str] = Counter()
        for skill in self._skills.values():
            counter.update(self.description_tokens(skill.description))
        return {token for token, count in counter.items() if count >= 3}

    def message_contains_token(self, normalized_message: str, token: str) -> bool:
        if re.fullmatch(r"[a-z0-9]+", token):
            return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", normalized_message) is not None
        return token in normalized_message

    def normalize_text(self, text: str) -> str:
        return text.lower()

    def build_prompt_section(self) -> str:
        if not self._skills:
            return ""

        lines = [
            "## Available Skills",
            "",
            "The following skill manuals are available in the current session. A skill is not a tool; it is an operating guide for using existing tools.",
            "",
            "After each user request, quickly check this list first:",
            "1. If the request clearly matches a skill name or description, your first step must be to call the read tool on that skill's SKILL.md.",
            "2. Before reading the matching SKILL.md, do not call write, edit, or bash to complete the task.",
            "3. After reading SKILL.md, continue with existing tools such as read, write, edit, and bash according to its instructions.",
            "4. Only use ordinary tools directly, or answer directly, when there is no clear matching skill.",
            "",
            "Do not read every skill by default. Read only the one that is clearly needed for the current task.",
            "",
        ]
        for skill in self._skills.values():
            lines.append(
                f"- {skill.name}: {skill.description}\n"
                f"  path: {skill.path}"
            )
        return "\n".join(lines)
