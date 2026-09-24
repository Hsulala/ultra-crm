"""正式環境開機時自動跑一次：如果指令碼屬性有設 ADMIN_BOOTSTRAP_USERNAME/
ADMIN_BOOTSTRAP_PASSWORD，而且目前完全沒有任何後台帳號，就建立第一個
店長帳號。已經有帳號的話什麼都不做——可以放心讓這支腳本每次部署都跑，
不會重複建立或覆蓋密碼。"""

import os

from app.auth.admin import hash_password
from app.database import SessionLocal
from app.models import AdminUser


def main() -> None:
    username = os.environ.get("ADMIN_BOOTSTRAP_USERNAME")
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    if not username or not password:
        print("未設定 ADMIN_BOOTSTRAP_USERNAME/PASSWORD，略過建立帳號。")
        return

    db = SessionLocal()
    try:
        if db.query(AdminUser).count() > 0:
            print("已經有後台帳號存在，略過 bootstrap。")
            return

        user = AdminUser(username=username, password_hash=hash_password(password), role="manager")
        db.add(user)
        db.commit()
        print(f"已建立第一個店長帳號：{username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
