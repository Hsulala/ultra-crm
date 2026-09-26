"""正式環境開機時自動跑一次：如果指令碼屬性有設 ADMIN_BOOTSTRAP_USERNAME/
ADMIN_BOOTSTRAP_PASSWORD，而且目前完全沒有任何後台帳號，就建立第一個
超級管理者帳號（第一個帳號視為系統擁有者，權限最高）。已經有帳號的話
不會重複建立或覆蓋密碼；但如果那個帳號還不是 super_admin（例如舊部署
建立時還只有 manager 角色），會自動把它升級成 super_admin——可以放心
讓這支腳本每次部署都跑。"""

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
            existing = db.query(AdminUser).filter(AdminUser.username == username).first()
            if existing and existing.role != "super_admin":
                existing.role = "super_admin"
                db.commit()
                print(f"已將既有帳號升級為超級管理者：{username}")
            else:
                print("已經有後台帳號存在，略過 bootstrap。")
            return

        user = AdminUser(username=username, password_hash=hash_password(password), role="super_admin")
        db.add(user)
        db.commit()
        print(f"已建立第一個超級管理者帳號：{username}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
