"""角色 -> Rich Menu ID 的對應。

實際的 richMenuId 要跑過 scripts/setup_rich_menus.py 一次性建立後才會知道，
現階段先用 Script Properties／環境變數占位，未設定時 line_client 會自己跳過。
"""

from typing import Optional

from app.config import settings

ROLE_TO_RICH_MENU_ENV = {
    None: "line_rich_menu_id_default",
    "student": "line_rich_menu_id_member",
    "coach": "line_rich_menu_id_coach",
    "venue_coach": "line_rich_menu_id_venue_coach",
}


def rich_menu_id_for_role(role: Optional[str]) -> Optional[str]:
    env_key = ROLE_TO_RICH_MENU_ENV.get(role)
    if env_key is None:
        return None
    return getattr(settings, env_key, None) or None
