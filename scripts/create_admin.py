"""建立第一個後台帳號用的小工具（目前沒有自助註冊流程）。

用法：
    python -m scripts.create_admin <username> <password> <role>
    role 為 manager / front_desk / coach 其中之一
"""

import sys

from app.auth.admin import hash_password
from app.database import SessionLocal
from app.models import ADMIN_ROLE_LABELS, AdminUser


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    username, password, role = sys.argv[1], sys.argv[2], sys.argv[3]
    if role not in ADMIN_ROLE_LABELS:
        print(f"role 必須是 {list(ADMIN_ROLE_LABELS)} 其中之一")
        sys.exit(1)

    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.username == username).first():
            print(f"帳號 {username} 已存在")
            sys.exit(1)

        user = AdminUser(username=username, password_hash=hash_password(password), role=role)
        db.add(user)
        db.commit()
        print(f"已建立帳號：{username}（{ADMIN_ROLE_LABELS[role]}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
