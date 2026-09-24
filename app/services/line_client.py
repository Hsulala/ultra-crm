"""LINE Messaging API 呼叫封裝（推播、圖文選單切換）。

Phase 1 現階段還沒有正式的 LINE_CHANNEL_ACCESS_TOKEN，所以這裡的函式在
沒設定金鑰時直接記錄警告並跳過，不會讓綁定流程失敗——金鑰到位後不用改
呼叫端的程式碼，直接就會生效。
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.line_channel_access_token}"}


def link_rich_menu_to_user(line_user_id: str, rich_menu_id: str) -> None:
    if not settings.line_channel_access_token:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 尚未設定，略過圖文選單切換（user=%s, menu=%s）", line_user_id, rich_menu_id)
        return
    url = f"{LINE_API_BASE}/user/{line_user_id}/richmenu/{rich_menu_id}"
    response = httpx.post(url, headers=_headers())
    if response.status_code != 200:
        logger.error("連結圖文選單失敗 user=%s menu=%s: %s", line_user_id, rich_menu_id, response.text)


def unlink_rich_menu_from_user(line_user_id: str) -> None:
    if not settings.line_channel_access_token:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 尚未設定，略過解除圖文選單（user=%s）", line_user_id)
        return
    url = f"{LINE_API_BASE}/user/{line_user_id}/richmenu"
    response = httpx.delete(url, headers=_headers())
    if response.status_code != 200:
        logger.error("解除圖文選單失敗 user=%s: %s", line_user_id, response.text)


def push_message(line_user_id: str, text: str) -> None:
    if not settings.line_channel_access_token:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN 尚未設定，略過推播（user=%s）: %s", line_user_id, text)
        return
    url = f"{LINE_API_BASE}/message/push"
    payload = {"to": line_user_id, "messages": [{"type": "text", "text": text}]}
    response = httpx.post(url, headers={**_headers(), "Content-Type": "application/json"}, json=payload)
    if response.status_code != 200:
        logger.error("推播訊息失敗 user=%s: %s", line_user_id, response.text)
