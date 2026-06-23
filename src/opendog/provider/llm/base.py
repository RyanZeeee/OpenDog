from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from opendog.utils.config import LLMConfig

from litellm import acompletion


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None


@dataclass
class LLMStreamChunk:
    content: str = ""
    tool_call_index: Optional[int] = None
    tool_call_id: Optional[str] = None
    tool_call_name: Optional[str] = None
    tool_call_arguments: str = ""
    stop_reason: Optional[str] = None


class LLMProvider:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    async def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        request_kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        response = await acompletion(**request_kwargs)
        return self._parse_response(response)

    async def stream_chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        request_kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        request_kwargs["stream"] = True

        response = await acompletion(**request_kwargs)
        async for chunk in response:
            stream_chunk = parse_stream_chunk(chunk)
            if stream_chunk is not None:
                yield stream_chunk

    def _parse_response(self, response: object) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls = []

        for tool_call in raw_tool_calls:
            tool_calls.append(
                LLMToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments or "{}",
                )
            )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            stop_reason=getattr(choice, "finish_reason", None),
        )

    def _build_request_kwargs(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> dict:
        request_kwargs = {
            "model": self._build_model_name(),
            "messages": messages,
            "max_tokens": self.config.max_tokens,
        }

        if self.config.temperature is not None:
            request_kwargs["temperature"] = self.config.temperature

        api_key = self._get_api_key()
        if api_key:
            request_kwargs["api_key"] = api_key

        api_base = self._get_api_base()
        if api_base:
            request_kwargs["api_base"] = api_base

        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = tool_choice or "auto"

        request_kwargs.update(self.config.extra)
        return request_kwargs

    def _build_model_name(self) -> str:
        provider = self.config.provider.strip()
        model = self.config.model.strip()

        if not provider or provider == "openai" or "/" in model:
            return model

        return f"{provider}/{model}"

    def _get_api_base(self) -> Optional[str]:
        return self.config.api_base

    def _get_api_key(self, required: bool = True) -> Optional[str]:
        api_key = self.config.api_key
        if required and not api_key:
            raise ValueError("Missing API key. Please set llm.api_key in workspace/config.user.yaml.")
        return api_key


def parse_stream_chunk(chunk: object) -> Optional[LLMStreamChunk]:
    choices = get_value(chunk, "choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = get_value(choice, "delta", None)
    stop_reason = get_value(choice, "finish_reason", None)

    content = get_value(delta, "content", "") if delta is not None else ""
    if content:
        return LLMStreamChunk(content=content, stop_reason=stop_reason)

    tool_calls = get_value(delta, "tool_calls", None) if delta is not None else None
    if tool_calls:
        tool_call = tool_calls[0]
        function = get_value(tool_call, "function", None)
        return LLMStreamChunk(
            tool_call_index=get_value(tool_call, "index", 0),
            tool_call_id=get_value(tool_call, "id", None),
            tool_call_name=get_value(function, "name", None),
            tool_call_arguments=get_value(function, "arguments", "") or "",
            stop_reason=stop_reason,
        )

    if stop_reason:
        return LLMStreamChunk(stop_reason=stop_reason)

    return None


def get_value(obj: object, name: str, default: object = None) -> object:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
