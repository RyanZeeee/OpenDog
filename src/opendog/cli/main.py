from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import typer

logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)

from opendog.cli.session_picker import select_session_sync
from opendog.cli.tui import TuiChatLoop
from opendog.core.agent import Agent
from opendog.core.agent_loader import load_agent_definition
from opendog.core.cron.runner import CronRunner
from opendog.core.session_store import SessionStore
from opendog.core.shared_context import SharedContext
from opendog.interfaces.feishu.adapter import FeishuAdapter
from opendog.interfaces.feishu.client import FeishuClient
from opendog.interfaces.feishu.gateway import FeishuGateway
from opendog.provider.llm.base import LLMProvider
from opendog.tools import load_tool_registry
from opendog.utils.config import AppConfig

app = typer.Typer(
    help="Terminal chat bot for the opendog rebuild project.",
    invoke_without_command=True,
)


def build_agent(context: SharedContext, agent_id: str | None = None) -> Agent:
    selected_agent = agent_id or context.config.default_agent
    agent_path = (
        context.workspace_root
        / context.config.paths.agents_dir
        / selected_agent
        / "AGENT.md"
    )
    agent_def = load_agent_definition(agent_path)
    provider = LLMProvider(context.config.llm)
    tools = load_tool_registry(context.config, context.workspace_root)
    return Agent(
        agent_def=agent_def,
        llm=provider,
        skills_dir=context.workspace_root / context.config.paths.skills_dir,
        workspace_root=context.workspace_root,
        working_dir=context.working_dir,
        tools=tools,
        history=context.config.history,
    )


import opendog

def run_chat(context: SharedContext) -> None:
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("litellm").setLevel(logging.ERROR)
    agent = build_agent(context)
    store = SessionStore(Path(opendog.__file__).parent / context.config.paths.history_dir)
    context.session_store = store

    session_id = select_session_sync(store, agent.agent_def.name)

    if session_id:
        session = agent.create_session(
            session_id=session_id, session_store=store, resume=True
        )
    else:
        session = agent.create_session(session_store=store)

    chat_loop = TuiChatLoop(context, agent, session)
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)

    def handle_asyncio_exception(loop, context):
        message = context.get("message", "")
        exception = context.get("exception")
        if (
            "SSL transport" in message
            or isinstance(exception, RuntimeError)
            and str(exception) == "Event loop is closed"
        ):
            return
        loop.default_exception_handler(context)

    event_loop.set_exception_handler(handle_asyncio_exception)

    try:
        event_loop.run_until_complete(chat_loop.run())
        event_loop.run_until_complete(asyncio.sleep(0.25))
    finally:
        pending_tasks = asyncio.all_tasks(event_loop)
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            event_loop.run_until_complete(
                asyncio.gather(*pending_tasks, return_exceptions=True)
            )
        event_loop.run_until_complete(event_loop.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        event_loop.close()


def run_feishu(context: SharedContext) -> None:
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("litellm").setLevel(logging.ERROR)

    feishu_config = context.config.feishu
    if not feishu_config.enabled:
        raise typer.BadParameter("feishu.enabled 为 false，请先在 workspace/config.user.yaml 中启用。")
    app_secret = feishu_config.resolved_app_secret()
    if not feishu_config.app_id or not app_secret:
        raise typer.BadParameter("缺少 feishu.app_id 或 feishu.app_secret。")

    agent = build_agent(context)
    store = SessionStore(Path(opendog.__file__).parent / context.config.paths.history_dir)
    context.session_store = store

    mcp_manager = getattr(agent.tools, "_mcp_manager", None)
    if mcp_manager is not None:
        mcp_manager.start_enabled_servers_background()

    client = FeishuClient(
        app_id=feishu_config.app_id,
        app_secret=app_secret,
    )
    adapter = FeishuAdapter(
        context=context,
        agent=agent,
        session_store=store,
        client=client,
    )
    gateway = FeishuGateway(
        app_id=feishu_config.app_id,
        app_secret=app_secret,
        adapter=adapter,
    )

    typer.echo("Feishu gateway starting... 输入 Ctrl+C 结束。")
    try:
        gateway.run()
    except KeyboardInterrupt:
        typer.echo("Feishu gateway stopped.")


def build_feishu_client_if_configured(context: SharedContext) -> FeishuClient | None:
    feishu_config = context.config.feishu
    app_secret = feishu_config.resolved_app_secret()
    if not feishu_config.enabled or not feishu_config.app_id or not app_secret:
        return None
    return FeishuClient(
        app_id=feishu_config.app_id,
        app_secret=app_secret,
    )


def run_cron(context: SharedContext) -> None:
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("litellm").setLevel(logging.ERROR)
    agent = build_agent(context)
    store = SessionStore(Path(opendog.__file__).parent / context.config.paths.history_dir)
    context.session_store = store

    mcp_manager = getattr(agent.tools, "_mcp_manager", None)
    if mcp_manager is not None:
        mcp_manager.start_enabled_servers_background()

    runner = CronRunner(
        context=context,
        agent=agent,
        session_store=store,
        feishu_client=build_feishu_client_if_configured(context),
    )
    try:
        asyncio.run(runner.run_forever())
    except KeyboardInterrupt:
        typer.echo("Cron runner stopped.")


@app.command()
def feishu(ctx: typer.Context) -> None:
    """Start Feishu/Lark long-connection gateway."""

    run_feishu(ctx.obj)


@app.command()
def cron(ctx: typer.Context) -> None:
    """Start cron task runner."""

    run_cron(ctx.obj)


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Path = typer.Option(
        Path(os.environ.get("OPENDOG_DEFAULT_WORKSPACE", "workspace")),
        "--workspace",
        help="Path to workspace directory.",
    ),
    config: str = typer.Option("config.user.yaml", "--config", help="Config filename inside workspace."),
) -> None:
    workspace_root = workspace.resolve()
    ctx.obj = SharedContext(
        workspace_root=workspace_root,
        working_dir=Path.cwd().resolve(),
        config=AppConfig.load(workspace_root / config),
    )

    if ctx.invoked_subcommand is None:
        run_chat(ctx.obj)
