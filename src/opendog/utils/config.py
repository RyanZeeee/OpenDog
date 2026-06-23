from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: int = 4096
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    extra: Dict[str, Any] = Field(default_factory=dict)


class PathConfig(BaseModel):
    agents_dir: Path = Path("agents")
    skills_dir: Path = Path("skills")
    history_dir: Path = Path(".history")


class BuiltinToolConfig(BaseModel):
    enabled: bool = True


class PluginToolConfig(BaseModel):
    enabled: bool = True
    paths: list[Path] = Field(default_factory=lambda: [Path("plugins")])


class MCPServerConfig(BaseModel):
    name: str = ""
    description: str = ""
    type: str = "stdio"
    enabled: bool = False
    agent_managed: bool = False
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None


class ToolConfig(BaseModel):
    builtin: BuiltinToolConfig = Field(default_factory=BuiltinToolConfig)
    plugins: PluginToolConfig = Field(default_factory=PluginToolConfig)


class HistoryConfig(BaseModel):
    max_tokens: int = 30000
    keep_recent_messages: int = 10
    summary_max_tokens: int = 2000


class FeishuConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: Optional[str] = None
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"
    streaming: bool = False

    def resolved_app_secret(self) -> str:
        return self.app_secret or ""


class AppConfig(BaseModel):
    llm: LLMConfig
    default_agent: str = "default"
    paths: PathConfig = Field(default_factory=PathConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    mcpServers: Dict[str, MCPServerConfig] = Field(default_factory=dict)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)

    @classmethod
    def load(cls, path: Union[str, Path]) -> "AppConfig":
        config_path = Path(path).resolve()
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)
