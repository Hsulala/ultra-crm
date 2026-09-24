"""Railway Cron / 維運腳本專用的內部端點，用共用密鑰驗證，不是給一般使用者用的。

Phase 0 先建立骨架；到期提醒推播、自動解綁掃描的實際邏輯留到相關 Phase
（Phase 1 綁定機制、Phase 6 營收/會員卡提醒）再接上 app/services/scheduler.py。
"""

from fastapi import APIRouter, Header, HTTPException, status

from app.config import settings

router = APIRouter(prefix="/internal", tags=["internal"])


def _check_secret(x_internal_secret: str) -> None:
    if x_internal_secret != settings.internal_cron_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "密鑰錯誤")


@router.post("/cron/daily")
def run_daily_cron(x_internal_secret: str = Header(...)):
    _check_secret(x_internal_secret)
    # TODO：到期提醒推播、自動解綁掃描
    return {"status": "ok"}
