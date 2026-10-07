# -*- coding: utf-8 -*-
"""命令行应急工具（数据库端自带，网页端做不了的事用它）

什么时候用：
  - 服务没起来，想先开个号
  - 管理员账号被锁死 / 密码忘了，进不去网页端
  - 想看看到底有哪些账号

用法（在 database 目录下运行）：
    python manage_user.py --list
    python manage_user.py --reset 工号 新密码
    python manage_user.py --role 工号 组长
    python manage_user.py --add 工号 密码 姓名 部门 角色

角色只有三种：管理员 / 组长 / 普工（不填默认普工）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

import config
import db


def show_list():
    """打印所有账号"""
    rows = db.query_all("SELECT * FROM users ORDER BY id")
    if not rows:
        print("（暂无账号）")
        return
    print("%-4s %-14s %-10s %-8s %-8s %s" % ("ID", "工号", "姓名", "角色", "状态", "最后登录"))
    print("-" * 70)
    for r in rows:
        print("%-4s %-14s %-10s %-8s %-8s %s" % (
            r["id"], r["username"], r["real_name"] or "-", r["role"],
            "已停用" if r["disabled"] else "启用中",
            r["last_login"].strftime("%Y-%m-%d %H:%M") if r["last_login"] else "-"))


def reset_password(username, new_password):
    """重置密码（同时让其它地方的登录失效）"""
    db.execute("UPDATE users SET password_hash=%s, token_version=token_version+1 "
               "WHERE username=%s", (generate_password_hash(new_password), username))
    print("[成功] 已重置 %s 的密码" % username)


def set_role(username, role):
    """改角色"""
    db.execute("UPDATE users SET role=%s WHERE username=%s", (role, username))
    print("[成功] 已把 %s 的角色改成「%s」" % (username, role))


def add_user(username, password, real_name, department, role):
    """新增账号"""
    db.execute(
        "INSERT INTO users (username, password_hash, email, real_name, department, role, created_at) "
        "VALUES (%s, %s, NULL, %s, %s, %s, %s)",
        (username, generate_password_hash(password), real_name, department, role, db.now()))
    print("[成功] 已创建账号：%s（%s）" % (username, role))


def main():
    db.init_db()                    # 顺便确保表都存在（服务没起来也能用）
    args = sys.argv[1:]

    if not args or args[0] == "--list":
        show_list()
        return

    if args[0] == "--reset":
        if len(args) < 3:
            print("用法：python manage_user.py --reset 工号 新密码")
            return
        reset_password(args[1], args[2])
        return

    if args[0] == "--role":
        if len(args) < 3 or args[2] not in config.ROLES:
            print("用法：python manage_user.py --role 工号 角色（%s）" % " / ".join(config.ROLES))
            return
        set_role(args[1], args[2])
        return

    if args[0] == "--add":
        if len(args) < 4:
            print("用法：python manage_user.py --add 工号 密码 姓名 [部门] [角色]")
            return
        role = args[5] if len(args) > 5 else config.WORKER
        if role not in config.ROLES:
            print("角色只能是：%s" % " / ".join(config.ROLES))
            return
        add_user(args[1], args[2], args[3],
                 args[4] if len(args) > 4 else "未填写", role)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
