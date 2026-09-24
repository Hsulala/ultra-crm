"""LINE Messaging API webhook。

Phase 0 先做簽章驗證骨架；文字觸發（我要綁定/我的課程/上課記錄）與圖文選單
切換邏輯留到 Phase 1 隨綁定機制一起實作。
"""

import base64
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings

router = APIRouter(prefix="/line", tags=["line-webhook"])


def _verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(settings.line_channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    if not settings.line_channel_secret or not _verify_signature(body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "簽章驗證失敗")

    # TODO Phase 1：解析 events，處理文字觸發與 follow/unfollow 事件
    return {"status": "ok"}
