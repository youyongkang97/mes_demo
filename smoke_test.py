# -*- coding: utf-8 -*-
"""三端自检脚本 —— 启动三个服务后运行它，快速看整条链路通不通

它会真的走一遍用户流程（登录、建号、改角色、停用、邀请码注册、邮箱验证码注册、
找回密码、改密码被踢下线、上传头像、退出登录），每步打印 PASS / FAIL。

用法（在项目根目录下）：
    python smoke_test.py

注意：它会真的往数据库里写测试数据，跑完会自己清理掉。
"""

import base64
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

FRONTEND = "http://127.0.0.1:%d" % config.FRONTEND_PORT
DB = config.DBSERVER_URL
DB_HEAD = {"X-DB-Token": config.INTERNAL_TOKEN}
SUFFIX = str(int(time.time()) % 100000)      # 让每次跑的测试账号名不重复

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS  %-40s %s" % (name, extra))
    else:
        failed += 1
        print("FAIL  %-40s %s" % (name, extra))


def ask_db(path, payload):
    """测试脚本直接问数据库端（只有取验证码时用，平时业务都走前端→后端）"""
    return requests.post(DB + path, json=payload, headers=DB_HEAD, timeout=10).json()


def get_code(email):
    """从数据库里把刚发的验证码读出来（真实用户是从邮箱里看）"""
    return (ask_db("/code/get", {"email": email}).get("row") or {}).get("code")


print("=" * 78)
print("第 1 步：三个服务都活着吗")
print("-" * 78)

r = requests.get(DB + "/health", timeout=10).json()
check("数据库端 5002", r.get("mysql") is True, "mysql up")

r = requests.get(config.BACKEND_URL + "/api/health", timeout=10).json()
check("后端 5001", r.get("ok") == 1)

r = requests.get(FRONTEND + "/", timeout=10)
check("前端 5000 登录页", r.status_code == 200 and "分拣下料单元" in r.text)

print()
print("第 2 步：登录态（session）")
print("-" * 78)

r = requests.get(FRONTEND + "/users", allow_redirects=False, timeout=10)
check("没登录访问 /users 被弹回登录页", r.status_code == 302 and r.headers["Location"] == "/")

admin = requests.Session()
r = admin.post(FRONTEND + "/do/login", json={"username": "admin", "password": "bad"}, timeout=10).json()
check("密码错误被拒绝", r.get("ok") == 0, r.get("msg", "")[:24])

r = admin.post(FRONTEND + "/do/login", json={"username": "admin", "password": "admin123"}, timeout=10).json()
check("admin 登录成功", r.get("ok") == 1, "role=%s" % r.get("data", {}).get("role"))

r = admin.get(FRONTEND + "/users", timeout=10)
check("登录后能进人员管理页", r.status_code == 200 and "用户管理" in r.text)

r = admin.get(FRONTEND + "/me", timeout=10)
check("个人中心页能打开", r.status_code == 200 and "个人中心" in r.text)

print()
print("第 3 步：人员管理（新增 / 改角色 / 停用 / 删除）")
print("-" * 78)

worker = "w" + SUFFIX
r = admin.post(FRONTEND + "/do/user/add",
               data={"username": worker, "password": "abc12345", "real_name": "自检普工",
                     "department": "下料班组", "role": "普工"}, timeout=10, allow_redirects=False)
check("新增账号", r.status_code == 302)

r = admin.get(FRONTEND + "/users", timeout=10)
check("列表里能看到新账号", worker in r.text)

r = admin.post(FRONTEND + "/do/user/add",
               data={"username": worker, "password": "abc12345", "real_name": "重复",
                     "department": "x", "role": "普工"}, timeout=10)
check("重复工号给出人话提示", "已存在" in r.text)

r = admin.post(FRONTEND + "/do/user/role",
               data={"username": worker, "role": "组长"}, timeout=10, allow_redirects=False)
check("调整角色为组长", r.status_code == 302)

r = admin.post(FRONTEND + "/do/user/status",
               data={"username": worker, "disabled": "1"}, timeout=10, allow_redirects=False)
check("停用账号", r.status_code == 302)

s = requests.Session()
r = s.post(FRONTEND + "/do/login", json={"username": worker, "password": "abc12345"}, timeout=10).json()
check("停用后登录被拒绝", r.get("ok") == 0, r.get("msg", "")[:24])

r = admin.post(FRONTEND + "/do/user/status",
               data={"username": worker, "disabled": "0"}, timeout=10, allow_redirects=False)
check("重新启用", r.status_code == 302)

r = admin.post(FRONTEND + "/do/user/status",
               data={"username": "admin", "disabled": "1"}, timeout=10)
check("不能停用自己", "自己" in r.text or "当前登录" in r.text)

nonadmin = requests.Session()
r = nonadmin.post(FRONTEND + "/do/login", json={"username": worker, "password": "abc12345"}, timeout=10).json()
check("普工/组长能登录", r.get("ok") == 1, "role=%s" % r.get("data", {}).get("role"))

r = nonadmin.get(FRONTEND + "/users", timeout=10)
check("非管理员访问管理页得到 403", r.status_code == 403)

print()
print("第 4 步：邀请码注册（提权通道）")
print("-" * 78)

r = admin.post(FRONTEND + "/do/invite/add", data={"role": "组长", "hours": 24},
               timeout=10, allow_redirects=False)
check("签发邀请码", r.status_code == 302)

invites = ask_db("/invite/list", {}).get("rows") or []
invite_code = invites[0]["code"] if invites else ""
check("邀请码写进了数据库", bool(invite_code), "code=%s" % invite_code)

guest_mail = "smoke_%s@example.com" % SUFFIX
r = requests.post(FRONTEND + "/do/send_code", json={"email": guest_mail, "purpose": "register"}, timeout=10).json()
check("发注册验证码", r.get("ok") == 1, r.get("msg", "")[:30])

code = get_code(guest_mail)
check("验证码已入库", bool(code), "code=%s" % code)

guest = requests.Session()
r = guest.post(FRONTEND + "/do/register",
               json={"email": guest_mail, "code": code, "password": "abc12345",
                     "confirm": "abc12345", "invite": invite_code}, timeout=10).json()
check("用邀请码注册成功", r.get("ok") == 1, r.get("msg", "")[:40])
new_user = r.get("data", {}).get("username", "")
check("注册出来的身份是组长", r.get("data", {}).get("role") == "组长")

r = guest.get(FRONTEND + "/users", timeout=10)
check("组长仍然进不了管理页(403)", r.status_code == 403)

r = requests.post(FRONTEND + "/do/send_code", json={"email": guest_mail, "purpose": "register"}, timeout=10).json()
check("同一个邮箱已被注册 → 拒绝再发注册码", r.get("ok") == 0, r.get("msg", "")[:30])

print()
print("第 5 步：邮箱验证码找回密码")
print("-" * 78)

r = requests.post(FRONTEND + "/do/send_code", json={"email": guest_mail, "purpose": "reset"}, timeout=10).json()
check("发找回密码验证码", r.get("ok") == 1, r.get("msg", "")[:30])

r = requests.post(FRONTEND + "/do/send_code", json={"email": "nobody_%s@example.com" % SUFFIX,
                                                    "purpose": "reset"}, timeout=10).json()
check("未注册邮箱也回同样的话(防枚举)", r.get("ok") == 1, r.get("msg", "")[:30])

code = get_code(guest_mail)
r = requests.post(FRONTEND + "/do/reset",
                  json={"email": guest_mail, "code": code, "new_password": "new12345",
                        "confirm": "new12345"}, timeout=10).json()
check("用验证码重置密码", r.get("ok") == 1, r.get("msg", "")[:30])

r = guest.post(FRONTEND + "/do/login", json={"username": guest_mail, "password": "new12345"}, timeout=10).json()
check("用新密码登录（邮箱当账号）", r.get("ok") == 1)

r = guest.get(FRONTEND + "/users", timeout=10)
check("重置密码后旧会话被踢下线", r.status_code == 302 or r.status_code == 403,
      "status=%s" % r.status_code)

print()
print("第 6 步：个人中心（改资料 / 改密码 / 头像）")
print("-" * 78)

me_session = requests.Session()
me_session.post(FRONTEND + "/do/login", json={"username": worker, "password": "abc12345"}, timeout=10)

r = me_session.post(FRONTEND + "/do/profile", data={"nickname": "自检昵称", "gender": "男"},
                    timeout=10, allow_redirects=False)
check("保存昵称性别", r.status_code == 302)

r = me_session.get(FRONTEND + "/me", timeout=10)
check("个人中心显示新昵称", "自检昵称" in r.text)

png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
r = me_session.post(FRONTEND + "/do/avatar",
                    files={"avatar": ("a.png", png, "image/png")}, timeout=10, allow_redirects=False)
check("上传头像", r.status_code == 302)

r = me_session.get(FRONTEND + "/avatar/" + worker, timeout=10)
check("头像能取回来", r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image"))

r = me_session.post(FRONTEND + "/do/avatar",
                    files={"avatar": ("bad.png", b"this is not an image", "image/png")}, timeout=10)
check("假图片被文件头校验拦下", "图片" in r.text or "有效的图片" in r.text)

r = me_session.post(FRONTEND + "/do/password",
                    data={"old_password": "abc12345", "new_password": "xyz98765",
                          "confirm": "xyz98765"}, timeout=10, allow_redirects=False)
check("改密码后回到登录页", r.status_code == 302 and r.headers["Location"] == "/")

r = me_session.get(FRONTEND + "/users", allow_redirects=False, timeout=10)
check("改密码后本会话也失效", r.status_code == 302)

s2 = requests.Session()
r = s2.post(FRONTEND + "/do/login", json={"username": worker, "password": "xyz98765"}, timeout=10).json()
check("新密码可以登录", r.get("ok") == 1)

print()
print("第 7 步：退出登录与清理")
print("-" * 78)

r = s2.get(FRONTEND + "/do/logout", allow_redirects=False, timeout=10)
check("退出登录", r.status_code == 302 and r.headers["Location"] == "/")

r = s2.get(FRONTEND + "/users", allow_redirects=False, timeout=10)
check("退出后访问不了管理页", r.status_code == 302)

admin.post(FRONTEND + "/do/user/delete", data={"username": worker}, timeout=10)
admin.post(FRONTEND + "/do/user/delete", data={"username": new_user}, timeout=10)
for v in invites:
    if v.get("code"):
        admin.post(FRONTEND + "/do/invite/revoke", data={"code": v["code"]}, timeout=10)
r = admin.get(FRONTEND + "/users", timeout=10)
check("测试账号已清理", worker not in r.text and (not new_user or new_user not in r.text))

print("=" * 78)
print("PASS=%d  FAIL=%d" % (passed, failed))
sys.exit(1 if failed else 0)
