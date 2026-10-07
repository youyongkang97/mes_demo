# -*- coding: utf-8 -*-
"""数据库端服务器（端口 5002）—— 三端里唯一连 MySQL 的服务器

原则只有一条：**只搬数据，不做业务判断**。
  - 不判断密码对不对        → 那是后端的活
  - 不判断验证码过没过期    → 那是后端的活
  - 不判断谁有没有权限      → 那是后端的活
它只负责"取一行 / 存一行 / 删一行"，外加进门时的令牌检查。

这样分层规则只有一条，好记也好讲；业务规则全在 backend/app.py 一个文件里，
改规则不用动这里，改表结构也不用动后端。

运行：python database/server.py   →  http://127.0.0.1:5002
"""

import os
import sys

# 把项目根目录加进模块搜索路径，这样才能 import 到根目录的 config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import config
import db

app = Flask(__name__)
app.json.ensure_ascii = False       # 返回的中文直接显示，便于调试

db.init_db()                        # 启动时建库建表（失败只告警，服务照常起来）


# ==================== 进门检查 ====================

@app.before_request
def check_token():
    """内部令牌：除了健康检查，所有接口都必须带对 X-DB-Token

    数据库端监听在网络端口上，没有这道门的话，
    局域网里任何人扫到 5002 就能直接改数据。
    """
    if request.path == "/health":
        return None
    if request.headers.get("X-DB-Token") != config.INTERNAL_TOKEN:
        return {"ok": 0, "msg": "无权限访问数据库服务"}, 403
    return None


def body():
    """取请求体（不是合法 JSON 时返回空字典，不抛异常）"""
    return request.get_json(silent=True) or {}


@app.errorhandler(Exception)
def on_error(e):
    """没预料到的错误，也返回 JSON

    否则 Flask 会返回一个 HTML 错误页，后端 res.json() 解析失败，
    只能笼统地提示"数据库服务不可用"，看不出真正原因。
    """
    if isinstance(e, HTTPException):
        return e
    print("[数据库端] 未处理的错误：%s" % e)
    return {"ok": 0, "msg": "数据库端内部错误：%s" % e}, 500


# ==================== 账号 ====================

@app.post("/user/get")
def user_get():
    """按工号查一行（后端用它判断"有没有这个人"、校验密码）"""
    row = db.query_one("SELECT * FROM users WHERE username=%s", (body().get("username"),))
    return {"ok": 1, "row": db.clean(row)}


@app.post("/user/get_by_email")
def user_get_by_email():
    """按邮箱查一行（登录可以用邮箱，找回密码也用它）"""
    row = db.query_one("SELECT * FROM users WHERE email=%s", (body().get("email"),))
    return {"ok": 1, "row": db.clean(row)}


@app.post("/user/insert")
def user_insert():
    """新增一个账号

    工号或邮箱重复时 MySQL 会报唯一键冲突 —— 这里翻译成一句人话。
    不然它会变成一个 500 错误，用户看到"数据库服务不可用"会一头雾水。
    """
    d = body()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, email, real_name, department, role, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (d.get("username"), d.get("password_hash"), d.get("email"), d.get("real_name"),
             d.get("department"), d.get("role"), db.now()))
    except Exception as e:
        if "Duplicate entry" in str(e):     # 唯一索引冲突
            return {"ok": 0, "msg": "工号或邮箱已存在"}
        raise
    return {"ok": 1, "row": db.clean(db.query_one(
        "SELECT * FROM users WHERE username=%s", (d.get("username"),)))}


@app.post("/user/list")
def user_list():
    """全部账号（前端一次显示完，不做分页）"""
    return {"ok": 1, "rows": db.clean_all(db.query_all("SELECT * FROM users ORDER BY id DESC"))}


@app.post("/user/usernames_like")
def user_usernames_like():
    """按前缀取一批工号，例如前缀 admin 取回 admin、admin01、admin02…

    注意：这里只负责"取回来"，"下一个工号该是什么"是后端的规则。
    """
    rows = db.query_all("SELECT username FROM users WHERE username LIKE %s",
                        (body().get("prefix", "") + "%",))
    return {"ok": 1, "names": [r["username"] for r in rows]}


@app.post("/user/count_enabled")
def user_count_enabled():
    """某个角色下、处于启用状态的账号数（后端用"最后一个管理员"保护）"""
    row = db.query_one("SELECT COUNT(*) AS c FROM users WHERE role=%s AND disabled=0",
                       (body().get("role"),))
    return {"ok": 1, "count": row["c"]}


@app.post("/user/update_role")
def user_update_role():
    """改角色"""
    d = body()
    db.execute("UPDATE users SET role=%s WHERE username=%s", (d.get("role"), d.get("username")))
    return {"ok": 1}


@app.post("/user/update_password")
def user_update_password():
    """改密码，同时把 token_version +1

    token_version 是"登录失效开关"：改完密码，其它地方已经登录的会话
    下次刷新页面就会被踢回登录页。
    """
    d = body()
    db.execute("UPDATE users SET password_hash=%s, token_version=token_version+1 "
               "WHERE username=%s",
               (d.get("password_hash"), d.get("username")))
    return {"ok": 1}


@app.post("/user/update_profile")
def user_update_profile():
    """改昵称、性别"""
    d = body()
    db.execute("UPDATE users SET nickname=%s, gender=%s WHERE username=%s",
               (d.get("nickname"), d.get("gender"), d.get("username")))
    return {"ok": 1}


@app.post("/user/set_avatar")
def user_set_avatar():
    """记下头像文件名（图片本身存在文件系统 data/avatars/ 下）"""
    d = body()
    db.execute("UPDATE users SET avatar=%s WHERE username=%s",
               (d.get("filename"), d.get("username")))
    return {"ok": 1}


@app.post("/user/set_disabled")
def user_set_disabled():
    """启用 / 停用账号"""
    d = body()
    db.execute("UPDATE users SET disabled=%s WHERE username=%s",
               (1 if d.get("disabled") else 0, d.get("username")))
    return {"ok": 1}


@app.post("/user/delete")
def user_delete():
    """删除账号（登录审计不删，见 login_log 的说明）"""
    n = db.execute("DELETE FROM users WHERE username=%s", (body().get("username"),))
    return {"ok": 1, "affected": n}


@app.post("/user/touch_login")
def user_touch_login():
    """登录成功后：记最后登录时间、登录次数 +1"""
    db.execute("UPDATE users SET last_login=%s, login_count=login_count+1 WHERE username=%s",
               (db.now(), body().get("username")))
    return {"ok": 1}


# ==================== 登录审计 ====================

@app.post("/log/add")
def log_add():
    """记一条登录记录（成功和失败都记）"""
    d = body()
    db.execute("INSERT INTO login_log (username, ip, success, ts) VALUES (%s, %s, %s, %s)",
               (d.get("username"), d.get("ip", ""), 1 if d.get("success") else 0, db.now()))
    return {"ok": 1}


# ==================== 邮箱验证码 ====================

@app.post("/code/save")
def code_save():
    """存验证码：同一个邮箱只留最新的一条（所以重发会覆盖旧码）"""
    d = body()
    db.execute(
        "INSERT INTO email_code (email, code, created, last_sent, fails) "
        "VALUES (%s, %s, %s, %s, 0) "
        "ON DUPLICATE KEY UPDATE code=%s, created=%s, last_sent=%s, fails=0",
        (d.get("email"), d.get("code"), db.now(), db.now(),
         d.get("code"), db.now(), db.now()))
    return {"ok": 1}


@app.post("/code/get")
def code_get():
    """取验证码那一行；过期没过期、错了几次，都由后端判断"""
    row = db.query_one("SELECT * FROM email_code WHERE email=%s", (body().get("email"),))
    return {"ok": 1, "row": db.clean(row)}


@app.post("/code/bump_fails")
def code_bump_fails():
    """验证码输错一次，错误次数 +1"""
    db.execute("UPDATE email_code SET fails=fails+1 WHERE email=%s", (body().get("email"),))
    return {"ok": 1}


@app.post("/code/delete")
def code_delete():
    """删掉验证码（校验成功后立刻删，保证一个码只能用一次）"""
    db.execute("DELETE FROM email_code WHERE email=%s", (body().get("email"),))
    return {"ok": 1}


# ==================== 注册邀请码 ====================

@app.post("/invite/add")
def invite_add():
    """新增邀请码"""
    d = body()
    db.execute(
        "INSERT INTO invite_code (code, role, creator, expires, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (d.get("code"), d.get("role"), d.get("creator"), d.get("expires"), db.now()))
    return {"ok": 1}


@app.post("/invite/get")
def invite_get():
    """按码查一行"""
    row = db.query_one("SELECT * FROM invite_code WHERE code=%s", (body().get("code"),))
    return {"ok": 1, "row": db.clean(row)}


@app.post("/invite/list")
def invite_list():
    """全部邀请码（新的在前）"""
    return {"ok": 1, "rows": db.clean_all(
        db.query_all("SELECT * FROM invite_code ORDER BY id DESC"))}


@app.post("/invite/consume")
def invite_consume():
    """标记邀请码已被某个工号使用（用过的码就作废了）"""
    d = body()
    db.execute("UPDATE invite_code SET used_by=%s, used_at=%s WHERE code=%s",
               (d.get("username"), db.now(), d.get("code")))
    return {"ok": 1}


@app.post("/invite/delete")
def invite_delete():
    """作废邀请码"""
    n = db.execute("DELETE FROM invite_code WHERE code=%s", (body().get("code"),))
    return {"ok": 1, "affected": n}


# ==================== 健康检查 ====================

@app.get("/health")
def health():
    """免令牌：看看服务和 MySQL 是否正常（后端 /api/health 会转发这个结果）"""
    try:
        db.query_one("SELECT 1 AS one")
        mysql_ok, err = True, ""
    except Exception as e:
        mysql_ok, err = False, str(e)[:200]
    return {"ok": 1, "mysql": mysql_ok, "error": err, "time": db.now()}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.DBSERVER_PORT, debug=False)
