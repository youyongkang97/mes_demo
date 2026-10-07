# -*- coding: utf-8 -*-
"""前端服务器（端口 5000）—— 三端里的"大门"

它做四件事：
  1. 渲染页面（Jinja 模板）；
  2. 记住"谁登录了"（Flask 的 session，本质是一个签过名的 cookie，
     浏览器之后每次请求会自动带上，所以代码里不用管令牌）；
  3. 把请求转发给后端 5001，转发时带两样东西：
        X-From: 服务间令牌   —— 证明"我是前端服务器"
        X-User: 当前登录工号 —— 告诉后端"这次是谁在操作"
  4. 显示 403 / 404 / 500 错误页。

因为浏览器只跟这一台服务器说话，后端 5001 和数据库端 5002 都不必对外开放。

两种交互方式（刻意分开）：
  - 登录页：用 fetch + JSON，为了保留"不刷新 + 就地红/绿提示"的设计；
  - 管理页与个人中心：表单 POST + 重定向 + flash 提示，JS 尽量少。

运行：python frontend/server.py   →  http://127.0.0.1:5000
"""

import os
import sys

# 把项目根目录加进模块搜索路径，这样才能 import 到根目录的 config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import (Flask, Response, flash, get_flashed_messages, redirect,
                   render_template, request, session)

import config

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET                 # session 用它签名（自动生成的那把）
app.json.ensure_ascii = False
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"        # 本站内正常携带 cookie
app.config["SESSION_COOKIE_HTTPONLY"] = True         # JS 读不到 cookie，减少被偷的风险

SESSION_USER = "username"       # session 里存：当前登录的工号
SESSION_VER = "ver"             # session 里存：登录时拿到的 token_version


# ==========================================================================
# 一、和后端通话
# ==========================================================================

def ask_backend(path, payload=None, method="POST", files=None):
    """调用后端接口，自动带上"我是前端"和"当前是谁"

    后端连不上时返回 {"ok": 0, ...}，页面正常显示一句提示，不会崩。
    """
    headers = {"X-From": config.INTERNAL_TOKEN}
    username = session.get(SESSION_USER)
    if username:
        headers["X-User"] = username
        headers["X-Forwarded-For"] = request.remote_addr or ""   # 让审计日志能记到真实 IP

    try:
        if method == "GET":
            res = requests.get(config.BACKEND_URL + path, headers=headers,
                               timeout=config.REQUEST_TIMEOUT)
        elif files is not None:
            res = requests.post(config.BACKEND_URL + path, files=files, headers=headers,
                                timeout=config.REQUEST_TIMEOUT)
        else:
            res = requests.post(config.BACKEND_URL + path, json=payload or {},
                                headers=headers, timeout=config.REQUEST_TIMEOUT)
        return res.json()
    except Exception as e:
        print("[前端] 调用后端失败：%s" % e)
        return {"ok": 0, "msg": "后端服务不可用，请确认三个服务都已启动"}


def load_me():
    """看看"我"还有没有效，顺便拿到最新的角色和资料；无效就顺手清掉 session

    每个页面都会走一次，所以：
      - 账号被停用 / 被删除 → 下次刷新页面就掉线；
      - 角色被改 → 下次刷新就按新权限显示菜单；
      - 别处改了密码（token_version 变了）→ 这里的 ver 对不上，也会掉线。
    """
    if not session.get(SESSION_USER):
        return None
    res = ask_backend("/api/me", {"ver": session.get(SESSION_VER)})
    if res.get("ok") != 1:
        session.clear()
        return None
    return res["data"]


def pop_flash():
    """取出服务端提示（模板里渲染成一条消息条），返回 (文字, 是不是错误)"""
    msgs = get_flashed_messages(with_categories=True)
    if not msgs:
        return "", False
    category, text = msgs[-1]
    return text, (category == "error")


def tell(res, url):
    """把后端的提示原样显示出来，然后跳回某个页面"""
    flash(res.get("msg") or "操作完成", "error" if res.get("ok") != 1 else "success")
    return redirect(url)


def admin_guard():
    """管理员动作的统一前置检查，返回 (当前用户, 不合格时的响应)"""
    me = load_me()
    if not me:
        flash("请先登录", "error")
        return None, redirect("/")
    if not config.can(me["role"], "人员管理"):
        flash("当前身份「%s」没有人员管理权限" % me["role"], "error")
        return None, redirect("/users")
    return me, None


# ==========================================================================
# 二、页面
# ==========================================================================

@app.get("/")
def page_login():
    """登录页；已经登录过就直接进人员管理页"""
    if session.get(SESSION_USER):
        return redirect("/users")
    flash_msg, flash_err = pop_flash()
    return render_template("login.html", flash_msg=flash_msg, flash_err=flash_err)


@app.get("/users")
def page_users():
    """人员管理页（只有管理员能进）"""
    me = load_me()
    if not me:
        flash("请先登录", "error")
        return redirect("/")

    if not config.can(me["role"], "人员管理"):
        return render_template("403.html"), 403

    users = ask_backend("/api/users", method="GET")
    invites = ask_backend("/api/users/invites", method="GET")
    flash_msg, flash_err = pop_flash()
    return render_template(
        "users.html",
        me=me,
        users=users.get("data") or [],
        invites=invites.get("data") or [],
        role_table=[{"role": r, "perms": config.permissions_of(r)} for r in config.ROLES],
        flash_msg=flash_msg, flash_err=flash_err)


@app.get("/me")
def page_me():
    """个人中心：改资料、改密码、换头像"""
    me = load_me()
    if not me:
        flash("请先登录", "error")
        return redirect("/")
    flash_msg, flash_err = pop_flash()
    return render_template("me.html", me=me, flash_msg=flash_msg, flash_err=flash_err)


# ==========================================================================
# 三、登录页用的接口（返回 JSON，页面自己处理提示）
# ==========================================================================

@app.post("/do/login")
def do_login():
    """登录：问后端；成功就把工号和 ver 记进 session"""
    res = ask_backend("/api/login", request.get_json(silent=True) or {})
    if res.get("ok") == 1:
        session[SESSION_USER] = res["data"]["username"]
        session[SESSION_VER] = res["data"]["ver"]
    return res


@app.post("/do/register")
def do_register():
    """注册：成功后直接算登录（后端已经把号建好了）"""
    res = ask_backend("/api/register", request.get_json(silent=True) or {})
    if res.get("ok") == 1:
        session[SESSION_USER] = res["data"]["username"]
        session[SESSION_VER] = res["data"]["ver"]
    return res


@app.post("/do/send_code")
def do_send_code():
    """发邮箱验证码（注册 / 找回密码共用）"""
    return ask_backend("/api/send_code", request.get_json(silent=True) or {})


@app.post("/do/reset")
def do_reset():
    """找回密码：邮箱验证码 + 新密码"""
    return ask_backend("/api/reset_password", request.get_json(silent=True) or {})


# ==========================================================================
# 四、管理页 / 个人中心用的动作（都是表单提交 → 重定向 → 提示）
# ==========================================================================

@app.get("/do/logout")
def do_logout():
    """退出登录：清掉 session 就完事了"""
    session.clear()
    flash("已退出登录", "success")
    return redirect("/")


@app.post("/do/profile")
def do_profile():
    """保存昵称、性别"""
    me = load_me()
    if not me:
        return redirect("/")
    res = ask_backend("/api/profile", {
        "nickname": request.form.get("nickname", ""),
        "gender": request.form.get("gender", "保密"),
    })
    return tell(res, "/me")


@app.post("/do/password")
def do_password():
    """修改自己的密码"""
    me = load_me()
    if not me:
        return redirect("/")
    res = ask_backend("/api/password", {
        "old_password": request.form.get("old_password", ""),
        "new_password": request.form.get("new_password", ""),
        "confirm": request.form.get("confirm", ""),
    })
    if res.get("ok") == 1:
        # 改完密码 token_version 变了，当前这个 session 也该重新登录
        session.clear()
        flash(res.get("msg") or "密码已修改，请重新登录", "success")
        return redirect("/")
    return tell(res, "/me")


@app.post("/do/avatar")
def do_avatar():
    """上传头像（文件转发给后端，由后端校验大小、格式、文件头）"""
    me = load_me()
    if not me:
        return redirect("/")
    f = request.files.get("avatar")
    if not f or not f.filename:
        flash("请选择图片文件", "error")
        return redirect("/me")
    res = ask_backend("/api/avatar", files={"avatar": (f.filename, f.read(), f.mimetype)})
    return tell(res, "/me")


@app.post("/do/user/add")
def do_user_add():
    """新增账号"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users", {
        "username": request.form.get("username", "").strip(),
        "password": request.form.get("password", ""),
        "real_name": request.form.get("real_name", "").strip(),
        "department": request.form.get("department", "").strip(),
        "role": request.form.get("role", ""),
    })
    return tell(res, "/users")


@app.post("/do/user/role")
def do_user_role():
    """调整角色"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users/role", {
        "username": request.form.get("username", ""),
        "role": request.form.get("role", ""),
    })
    return tell(res, "/users")


@app.post("/do/user/reset")
def do_user_reset():
    """重置某个账号的密码（找回密码的兜底通道）"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users/reset", {
        "username": request.form.get("username", ""),
        "password": request.form.get("password", ""),
    })
    return tell(res, "/users")


@app.post("/do/user/status")
def do_user_status():
    """启用 / 停用账号"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users/status", {
        "username": request.form.get("username", ""),
        "disabled": request.form.get("disabled") == "1",     # 表单里来的是字符串
    })
    return tell(res, "/users")


@app.post("/do/user/delete")
def do_user_delete():
    """删除账号"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users/delete", {"username": request.form.get("username", "")})
    return tell(res, "/users")


@app.post("/do/invite/add")
def do_invite_add():
    """签发注册邀请码"""
    me, err = admin_guard()
    if err:
        return err
    try:
        hours = int(request.form.get("hours") or 72)
    except ValueError:
        hours = 72
    res = ask_backend("/api/users/invites", {
        "role": request.form.get("role", ""),
        "hours": hours,
    })
    if res.get("ok") == 1:
        # 邀请码只显示这一次，放进提示里让管理员马上复制
        flash("邀请码：%s（%s，%d 小时内有效，请立即复制）"
              % (res["data"]["code"], res["data"]["role"], res["data"]["hours"]), "success")
        return redirect("/users")
    return tell(res, "/users")


@app.post("/do/invite/revoke")
def do_invite_revoke():
    """作废邀请码"""
    me, err = admin_guard()
    if err:
        return err
    res = ask_backend("/api/users/invites/revoke", {"code": request.form.get("code", "")})
    return tell(res, "/users")


# ==========================================================================
# 五、头像图片
# ==========================================================================

@app.get("/avatar/<name>")
def avatar(name):
    """把头像转发给浏览器

    <img> 标签没法自定义请求头，所以由前端服务器替浏览器去后端取。
    好处是：后端所有接口都能一律要求内部令牌，不用为头像开例外。
    """
    try:
        res = requests.get(config.BACKEND_URL + "/api/avatar/" + name,
                           headers={"X-From": config.INTERNAL_TOKEN},
                           timeout=config.REQUEST_TIMEOUT)
    except Exception:
        return "", 404
    if res.status_code != 200:
        return "", 404
    return Response(res.content, mimetype=res.headers.get("Content-Type", "image/png"))


# ==========================================================================
# 六、错误页
# ==========================================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FRONTEND_PORT, debug=False)
