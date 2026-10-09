from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi.templating import Jinja2Templates

from app.models import ADMIN_ROLE_LABELS, MOVEMENT_TYPE_LABELS
from app.models.schedule import SHIFT_LABELS
from app.services.cash_service import SHIFT_ORDER, to_taipei

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["ADMIN_ROLE_LABELS"] = ADMIN_ROLE_LABELS
templates.env.globals["MOVEMENT_TYPE_LABELS"] = MOVEMENT_TYPE_LABELS
templates.env.globals["SHIFT_LABELS"] = SHIFT_LABELS
templates.env.globals["SHIFT_ORDER"] = SHIFT_ORDER


def _ntd(value: Any) -> str:
    """金額顯示：整數不帶小數，有零頭才顯示兩位。"""
    if value is None:
        return "-"
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}"
    return f"{amount:,.2f}"


def _taipei(value: Optional[datetime], fmt: str = "%m/%d %H:%M") -> str:
    if value is None:
        return "-"
    return to_taipei(value).strftime(fmt)


templates.env.filters["ntd"] = _ntd
templates.env.filters["tpe"] = _taipei
