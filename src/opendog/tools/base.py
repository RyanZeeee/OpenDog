from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Union


class BaseTool(ABC):
    name: str
    description: str
    parameters: dict

    def get_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, session: Any, **kwargs: Any) -> str:
        raise NotImplementedError


class FunctionTool(BaseTool):
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        function: Callable[..., Union[Awaitable[str], str]],
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function

    async def execute(self, session: Any, **kwargs: Any) -> str:
        result = self.function(session=session, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return str(result)


def tool(name: str, description: str, parameters: dict):
    def decorator(function: Callable[..., Union[Awaitable[str], str]]) -> FunctionTool:
        return FunctionTool(
            name=name,
            description=description,
            parameters=parameters,
            function=function,
        )

    return decorator
