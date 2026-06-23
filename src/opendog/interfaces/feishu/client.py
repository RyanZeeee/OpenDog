from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


class FeishuClientError(RuntimeError):
    pass


@dataclass
class FeishuClient:
    app_id: str
    app_secret: str
    api_base: str = "https://open.feishu.cn/open-apis"

    _tenant_access_token: Optional[str] = None

    def tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token

        response = self._request_json(
            "POST",
            f"{self.api_base}/auth/v3/tenant_access_token/internal",
            {
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            auth=False,
        )
        token = response.get("tenant_access_token")
        if not token:
            raise FeishuClientError(f"Failed to get tenant_access_token: {response}")
        self._tenant_access_token = str(token)
        return self._tenant_access_token

    def send_text_to_chat(self, chat_id: str, text: str) -> dict:
        content = json.dumps({"text": text}, ensure_ascii=False)
        return self._request_json(
            "POST",
            f"{self.api_base}/im/v1/messages?receive_id_type=chat_id",
            {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": content,
            },
        )

    def reply_text(self, message_id: str, text: str) -> dict:
        content = json.dumps({"text": text}, ensure_ascii=False)
        return self._request_json(
            "POST",
            f"{self.api_base}/im/v1/messages/{message_id}/reply",
            {
                "msg_type": "text",
                "content": content,
            },
        )

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict,
        *,
        auth: bool = True,
    ) -> dict:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers["Authorization"] = f"Bearer {self.tenant_access_token()}"
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FeishuClientError(f"Feishu API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise FeishuClientError(f"Feishu API request failed: {exc}") from exc

        data = json.loads(body or "{}")
        code = data.get("code", 0)
        if code not in (0, None):
            raise FeishuClientError(f"Feishu API error: {data}")
        return data
