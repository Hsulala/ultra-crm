"""LINE LIFF ID Token 驗證。

Phase 0 先建立骨架（JWKS 抓取快取 + 驗證流程），Phase 1 綁定機制上線時
會接上 Member/VenueRentalCoach 查詢，把 verify_id_token() 回傳的 line_user_id
解析成實際身分。

規格參考：/Users/lala/.claude/plans/mellow-brewing-liskov.md 第三節「認證設計」。
"""

from typing import Optional

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app.config import settings

LINE_ISSUER = "https://access.line.me"
LINE_JWKS_URL = "https://api.line.me/oauth2/v2.1/certs"

_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(LINE_JWKS_URL)
    return _jwks_client


def verify_id_token(id_token: str) -> dict:
    """驗證 LINE ID Token，回傳 payload（含 sub = LINE userId）。
    驗證失敗一律丟 401，由呼叫端決定要不要當成訪客處理。"""
    if not settings.line_channel_id:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "LINE_CHANNEL_ID 尚未設定")

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            issuer=LINE_ISSUER,
            audience=settings.line_channel_id,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"LINE ID Token 驗證失敗：{exc}") from exc

    return payload


def get_line_user_id(
    authorization: Optional[str] = Header(None),
    x_dev_line_user_id: Optional[str] = Header(None, alias="X-Dev-Line-User-Id"),
) -> str:
    """FastAPI dependency：從 Authorization: Bearer <id_token> 取出並驗證，回傳 LINE userId。

    settings.dev_mode 開啟時，允許用 X-Dev-Line-User-Id 直接指定身分，
    跳過真的 LINE Token 驗證——只給本機開發測試用，正式環境不會開這個開關。"""
    if settings.dev_mode and x_dev_line_user_id:
        return x_dev_line_user_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Bearer Token")

    id_token = authorization.removeprefix("Bearer ").strip()
    payload = verify_id_token(id_token)
    return payload["sub"]
