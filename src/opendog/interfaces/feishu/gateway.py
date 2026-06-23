from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from opendog.interfaces.feishu.adapter import FeishuAdapter, make_sync_message_handler


class FeishuGatewayError(RuntimeError):
    pass


@dataclass
class FeishuGateway:
    app_id: str
    app_secret: str
    adapter: FeishuAdapter

    def run(self) -> None:
        try:
            import lark_oapi as lark
        except ImportError as exc:
            raise FeishuGatewayError(
                "缺少飞书 SDK，请先安装依赖：pip install lark-oapi"
            ) from exc

        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(
            target=self._run_loop,
            args=(loop,),
            daemon=True,
        )
        loop_thread.start()
        handler = make_sync_message_handler(self.adapter, loop)

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(lambda data: handler(data))
            .build()
        )
        log_level = getattr(getattr(lark, "LogLevel", None), "INFO", None)
        client_kwargs = {"event_handler": event_handler}
        if log_level is not None:
            client_kwargs["log_level"] = log_level
        client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            **client_kwargs,
        )

        try:
            client.start()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            loop.close()

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
