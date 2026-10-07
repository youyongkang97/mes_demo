# -*- coding: utf-8 -*-
"""后端应用服务（端口 5001）—— 所有业务判断都在这个文件里

三端数据流：
    浏览器 → 前端 5000 →【本服务】→ 数据库端 5002 → MySQL

本服务**不连数据库**：所有数据都用 post_db() 转发给数据库端，
数据库端只搬数据，判断（密码对不对、有没有权限、验证码过没过期）全在这里。
好处是"业务规则只有一处"，改规则不用碰数据库端，改表结构也不用碰这里。

运行：python backend/app.py   →  http://127.0.0.1:5001
"""

import datetime
import os
import re
import secrets
import sys
import time

# 把项目根目录加进模块搜索路径，这样才能 import 到根目录的 config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import Flask, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import config
import mail

app = Flask(__name__)
app.json.ensure_ascii = False       # 返回的中文直接显示，便于调试

# 密码规则：8~32 位，至少包含字母和数字；邮箱的简单格式校验
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,32}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# 登录失败记录（放在内存里：重启就清空，够用）
# 结构：{账号: [连续失败次数, 锁定到什么时候的时间戳]}
FAILS = {}


# ==========================================================================
# 一、小工具：统一返回格式、和数据库端通话
# ==========================================================================

def ok(data=None, msg="操作成功"):
    """成功：ok = 1"""
    return {"ok": 1, "msg": msg, "data": data}


def fail(msg="操作失败"):
    """失败：ok = 0，msg 直接给用户看"""
    return {"ok": 0, "msg": msg, "data": None}


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def post_db(path, payload=None):
    """调用数据库端接口（本服务访问数据的唯一出口）

    连不上时返回 {"ok": 0, ...}，让调用方按"数据没拿到"处理，
    而不是抛异常把整个接口弄成 500。
    """
    try:
        res = requests.post(config.DBSERVER_URL + path,
                            json=payload or {},
                            headers={"X-DB-Token": config.INTERNAL_TOKEN},
                            timeout=config.REQUEST_TIMEOUT)
        return res.json()
    except Exception as e:
        print("[后端] 调用数据库端失败：%s" % e)
        return {"ok": 0, "msg": "数据库服务暂时不可用，请稍后再试"}


def client_ip():
    """调用方的 IP。前端转发时会写上 X-Forwarded-For，否则就是前端服务器的地址"""
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


# ==========================================================================
# 二、身份与权限
# ==========================================================================

@app.before_request
def check_from_frontend():
    """只接受来自前端服务器的调用

    前端转发时会带 X-From（约定的服务间令牌）。这样别人即使扫到 5001，
    直连也调不动任何接口，必须先拿到令牌。
    """
    if request.path == "/api/health":
        return None
    if request.headers.get("X-From") != config.INTERNAL_TOKEN:
        return {"ok": 0, "msg": "无权访问，请通过前端页面操作"}
    return None


def current_user():
    """当前登录的人是谁

    前端把工号放在 X-User 头里，这里按工号**实时查库**：
      - 账号被删 → 查不到 → 返回 None（等于登录失效）
      - 账号被停用 → 返回 None
      - 角色被改 → 拿到的就是新角色，下一个请求立刻按新权限走
    这样做的前提是"令牌里不放角色"，见 /api/me 的说明。
    """
    username = request.headers.get("X-User")
    if not username:
        return None
    row = post_db("/user/get", {"username": username}).get("row")
    if not row or row["disabled"]:
        return None
    return row


def require_admin():
    """管理员接口统一的前置检查：返回 (当前用户, 错误响应)

    为什么不写成装饰器：这样每个接口开头两行就能看清它要什么权限，
    读代码不用来回跳文件；代价是五个接口各重复两行。
    """
    me = current_user()
    if not me:
        return None, fail("请先登录")
    if not config.can(me["role"], "人员管理"):
        return None, fail("当前身份「%s」没有人员管理权限" % me["role"])
    return me, None


def check_target(me, username, action):
    """人员管理的两条保护规则，返回 (目标账号, 错误响应)

    action 只在需要时报错，取值："role" / "status" / "delete"
      规则一：不能对自己下手（否则可能把自己锁在外面）
      规则二：系统必须始终保留一个"启用状态的管理员"
    """
    if username == me["username"]:
        return None, fail("不能对当前登录的账号执行这个操作")

    row = post_db("/user/get", {"username": username}).get("row")
    if not row:
        return None, fail("账号不存在：%s" % username)

    if row["role"] == config.ADMIN and not row["disabled"]:
        count = post_db("/user/count_enabled", {"role": config.ADMIN}).get("count", 0)
        if count <= 1:
            tips = {
                "role": "系统要至少保留一个启用的管理员，不能改他的角色",
                "status": "系统要至少保留一个启用的管理员，不能停用他",
                "delete": "系统要至少保留一个启用的管理员，不能删除他",
            }
            return None, fail(tips.get(action, "系统要至少保留一个启用的管理员"))
    return row, None


# ==========================================================================
# 三、几个共用的小逻辑
# ==========================================================================

def next_username(role):
    """按角色生成工号：管理员 admin / admin01…，组长 b001…，普工 p001…

    做法：把同前缀的工号全取回来，找数字最大的那个 +1。
    （两个人同时注册理论上可能撞号，但工号有唯一索引兜底，不会写坏数据。）
    """
    if role == config.ADMIN:
        names = post_db("/user/usernames_like", {"prefix": "admin"}).get("names") or []
        if "admin" not in names:
            return "admin"
        biggest = 0
        for n in names:
            tail = n[5:]                       # 去掉 "admin"
            if tail.isdigit():
                biggest = max(biggest, int(tail))
        return "admin%02d" % (biggest + 1)

    prefix = "b" if role == config.LEADER else "p"
    names = post_db("/user/usernames_like", {"prefix": prefix}).get("names") or []
    biggest = 0
    for n in names:
        tail = n[1:]                           # 去掉前缀字母
        if tail.isdigit():
            biggest = max(biggest, int(tail))
    return "%s%03d" % (prefix, biggest + 1)


def check_email_code(email, code):
    """校验邮箱验证码，返回 (对不对, 错误提示)

    规则：300 秒内有效、连续错 5 次作废、验证成功后立刻删除（一个码只能用一次）。
    """
    row = post_db("/code/get", {"email": email}).get("row")
    if not row:
        return False, "请先获取邮箱验证码"
    if row["fails"] >= config.CODE_MAX_FAILS:
        return False, "验证码错误次数过多，请重新获取"
    if row["code"] != code:
        post_db("/code/bump_fails", {"email": email})
        return False, "邮箱验证码不正确"

    created = datetime.datetime.strptime(row["created"], "%Y-%m-%d %H:%M:%S")
    if (datetime.datetime.now() - created).total_seconds() > config.CODE_TTL:
        return False, "验证码已过期，请重新获取"

    post_db("/code/delete", {"email": email})   # 一次性：用完就删
    return True, ""


def is_image(data, ext):
    """看文件开头几个字节，判断它是不是真的图片

    为什么光看扩展名不够：`病毒.exe` 改个名字就叫 `a.png` 了。
    这里比"文件头"，内容对不上就不收。
    """
    if ext == "jpeg":
        ext = "jpg"
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "jpg":
        return data.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return data.startswith(b"GIF87a") or data.startswith(b"GIF89a")
    if ext == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def lock_seconds_left(account):
    """这个账号还被锁着吗？还锁着就返回剩余秒数，否则返回 0"""
    cnt, until = FAILS.get(account, [0, 0])
    if until and time.time() < until:
        return int(until - time.time()) + 1
    return 0


def record_login_fail(account, msg):
    """记一次登录失败：够 5 次就锁 60 秒，并写审计"""
    cnt, until = FAILS.get(account, [0, 0])
    if until and time.time() >= until:       # 上次的锁已经过期，重新计数
        cnt, until = 0, 0
    cnt += 1
    if cnt >= config.MAX_LOGIN_FAILS:
        cnt, until = 0, time.time() + config.LOCK_SECONDS
        msg = "失败次数过多，账号已锁定 %d 秒" % config.LOCK_SECONDS
    FAILS[account] = [cnt, until]
    post_db("/log/add", {"username": account, "ip": client_ip(), "success": False})
    return fail(msg)


# ==========================================================================
# 四、登录态：/api/me
# ==========================================================================

@app.post("/api/me")
def api_me():
    """"我还登录着吗？我是谁？我能干什么？" —— 前端每次进受保护页面都调它

    ver 是登录时后端给的 token_version。改密码后它会 +1，
    于是其它浏览器上带着旧 ver 的会话下次进来就会被判为失效（踢下线）。
    """
    me = current_user()
    if not me:
        return fail("登录已失效，请重新登录")

    ver = (request.get_json(silent=True) or {}).get("ver")
    if int(me["token_version"]) != int(ver or 0):
        return fail("登录已失效，请重新登录")

    return ok({
        "username": me["username"],
        "real_name": me["real_name"],
        "department": me["department"],
        "email": me["email"],
        "nickname": me["nickname"],
        "gender": me["gender"],
        "avatar": me["avatar"],
        "role": me["role"],
        "permissions": config.permissions_of(me["role"]),
    })


# ==========================================================================
# 五、登录 / 注册 / 找回密码
# ==========================================================================

@app.post("/api/login")
def api_login():
    """登录：工号或邮箱都可以"""
    d = request.get_json(silent=True) or {}
    account = (d.get("username") or "").strip()
    password = d.get("password") or ""
    if not account or not password:
        return fail("请输入工号（或邮箱）与密码")

    left = lock_seconds_left(account)
    if left:
        return fail("失败次数过多，请 %d 秒后再试" % left)

    # 带 @ 的按邮箱查，否则按工号查（用等值查询，能走索引）
    if "@" in account:
        row = post_db("/user/get_by_email", {"email": account}).get("row")
    else:
        row = post_db("/user/get", {"username": account}).get("row")

    if not row:
        return record_login_fail(account, "账号不存在")
    if row["disabled"]:
        return record_login_fail(account, "该账号已停用，请联系管理员")
    if not check_password_hash(row["password_hash"], password):
        return record_login_fail(account, "密码错误")

    # 成功：清掉失败记录、写审计、更新最后登录时间
    FAILS.pop(account, None)
    post_db("/log/add", {"username": account, "ip": client_ip(), "success": True})
    post_db("/user/touch_login", {"username": row["username"]})

    name = row["nickname"] or row["real_name"] or row["username"]
    return ok({
        "username": row["username"],
        "ver": row["token_version"],          # ← 前端存进 session，/api/me 要用
        "role": row["role"],
        "permissions": config.permissions_of(row["role"]),
        "nickname": row["nickname"],
        "real_name": row["real_name"],
    }, "登录成功，欢迎 %s" % name)


@app.post("/api/send_code")
def api_send_code():
    """发邮箱验证码：purpose = register（注册）或 reset（找回密码）"""
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    purpose = (d.get("purpose") or "register").strip()

    if purpose not in ("register", "reset"):
        return fail("purpose 只能是 register 或 reset")
    if not EMAIL_RE.match(email):
        return fail("邮箱格式不正确")

    exists = bool(post_db("/user/get_by_email", {"email": email}).get("row"))

    if purpose == "register":
        if exists:
            return fail("该邮箱已被注册，可以直接登录")
    else:
        # 防枚举：邮箱没注册时也返回"已发送"，让人试不出哪些邮箱注册过
        if not exists:
            return ok(None, "若该邮箱已注册，验证码将发送至该邮箱")

    # 同一个邮箱 60 秒内只能发一次
    row = post_db("/code/get", {"email": email}).get("row")
    if row:
        last = datetime.datetime.strptime(row["last_sent"], "%Y-%m-%d %H:%M:%S")
        if (datetime.datetime.now() - last).total_seconds() < config.SEND_INTERVAL:
            return fail("发送过于频繁，请 %d 秒后再试" % config.SEND_INTERVAL)

    code = "%06d" % secrets.randbelow(1000000)      # 6 位随机数（用 secrets，不用 random）
    post_db("/code/save", {"email": email, "code": code})
    mail.send_code(email, code, purpose)            # 后台线程发信，失败会打印到控制台
    return ok(None, "验证码已发送至 %s，%d 分钟内有效" % (email, config.CODE_TTL // 60))


@app.post("/api/register")
def api_register():
    """注册：邮箱验证码 + 密码，可选邀请码

    权限重点：**角色只能由服务端决定**。
    默认普工；只有填了有效的邀请码，才按邀请码里写的角色（组长 / 普工）。
    这个接口从头到尾没有读过前端传来的任何"角色"字段 —— 否则改一个
    JSON 字段就能把自己注册成管理员。
    """
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    code = (d.get("code") or "").strip()
    password = d.get("password") or ""
    confirm = d.get("confirm") or ""
    invite = (d.get("invite") or "").strip()

    if not EMAIL_RE.match(email):
        return fail("邮箱格式不正确")
    if not code:
        return fail("请输入邮箱验证码")
    if not PASSWORD_RE.match(password):
        return fail("密码需 8-32 位，且至少包含字母和数字")
    if password != confirm:
        return fail("两次输入的密码不一致")

    good, msg = check_email_code(email, code)
    if not good:
        return fail(msg)

    # 角色：默认普工；邀请码是唯一的提权通道，而且只能提成组长
    role = config.WORKER
    if invite:
        inv = post_db("/invite/get", {"code": invite}).get("row")
        if not inv or inv["used_by"]:
            return fail("邀请码无效或已被使用")
        expires = datetime.datetime.strptime(inv["expires"], "%Y-%m-%d %H:%M:%S")
        if expires < datetime.datetime.now():
            return fail("邀请码已过期")
        if inv["role"] in (config.LEADER, config.WORKER):
            role = inv["role"]

    username = next_username(role)
    ret = post_db("/user/insert", {
        "username": username, "email": email,
        "password_hash": generate_password_hash(password),
        "real_name": "", "department": "未填写", "role": role,
    })
    if not ret.get("ok"):
        return fail(ret.get("msg") or "注册失败，请稍后再试")

    if invite:
        post_db("/invite/consume", {"code": invite, "username": username})

    row = ret["row"]
    return ok({
        "username": row["username"],
        "ver": row["token_version"],
        "role": row["role"],
        "permissions": config.permissions_of(row["role"]),
    }, "注册成功，你的工号是 %s，可以用工号或邮箱登录" % row["username"])


@app.post("/api/reset_password")
def api_reset_password():
    """忘记密码：邮箱验证码 + 新密码

    改完密码 token_version 会 +1，所以该账号**所有已经登录的地方下次刷新就掉线**。
    """
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    code = (d.get("code") or "").strip()
    new_password = d.get("new_password") or ""
    confirm = d.get("confirm") or ""

    if not EMAIL_RE.match(email):
        return fail("邮箱格式不正确")
    if not code:
        return fail("请输入邮箱验证码")
    if not PASSWORD_RE.match(new_password):
        return fail("新密码需 8-32 位，且至少包含字母和数字")
    if new_password != confirm:
        return fail("两次输入的密码不一致")

    good, msg = check_email_code(email, code)
    if not good:
        return fail(msg)

    row = post_db("/user/get_by_email", {"email": email}).get("row")
    if not row:
        return fail("该邮箱没有对应的账号，请联系管理员重置密码")

    post_db("/user/update_password",
            {"username": row["username"], "password_hash": generate_password_hash(new_password)})
    return ok(None, "密码已重置，其它地方的登录已失效，请用新密码登录")


@app.post("/api/password")
def api_password():
    """已经登录的人，自己改密码（要填原密码）"""
    me = current_user()
    if not me:
        return fail("请先登录")
    d = request.get_json(silent=True) or {}
    old = d.get("old_password") or ""
    new = d.get("new_password") or ""
    confirm = d.get("confirm") or ""

    if not check_password_hash(me["password_hash"], old):
        return fail("原密码不正确")
    if not PASSWORD_RE.match(new):
        return fail("新密码需 8-32 位，且至少包含字母和数字")
    if new != confirm:
        return fail("两次输入的新密码不一致")
    if new == old:
        return fail("新密码不能和原密码相同")

    post_db("/user/update_password",
            {"username": me["username"], "password_hash": generate_password_hash(new)})
    return ok(None, "密码已修改，请重新登录")


# ==========================================================================
# 六、个人资料与头像
# ==========================================================================

@app.post("/api/profile")
def api_profile():
    """改昵称、性别（工号是系统分配的，不给改）"""
    me = current_user()
    if not me:
        return fail("请先登录")
    d = request.get_json(silent=True) or {}
    nickname = (d.get("nickname") or "").strip()
    gender = (d.get("gender") or "保密").strip()

    if not nickname:
        return fail("昵称不能为空")
    if len(nickname) > 20:
        return fail("昵称最长 20 个字")
    if gender not in ("男", "女", "保密"):
        return fail("性别只能是 男 / 女 / 保密")

    post_db("/user/update_profile",
            {"username": me["username"], "nickname": nickname, "gender": gender})
    return ok(None, "个人信息已保存")


@app.post("/api/avatar")
def api_avatar():
    """上传头像：png / jpg / jpeg / webp / gif，最大 2MB"""
    me = current_user()
    if not me:
        return fail("请先登录")

    f = request.files.get("avatar")
    if not f or not f.filename:
        return fail("请选择图片文件")

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in config.AVATAR_EXTS:
        return fail("只支持 png / jpg / jpeg / webp / gif 图片")

    data = f.read()
    if len(data) > config.AVATAR_MAX_BYTES:
        return fail("图片不能超过 2MB")
    if not is_image(data, ext):
        return fail("文件内容不是有效的图片，请重新选择")

    os.makedirs(config.AVATAR_DIR, exist_ok=True)
    # 先删掉这个人的旧头像（换了格式时扩展名不同，不删会留下好几张）
    for old in os.listdir(config.AVATAR_DIR):
        if old.rsplit(".", 1)[0] == me["username"]:
            os.remove(os.path.join(config.AVATAR_DIR, old))

    filename = "%s.%s" % (me["username"], ext)
    with open(os.path.join(config.AVATAR_DIR, filename), "wb") as fp:
        fp.write(data)
    post_db("/user/set_avatar", {"username": me["username"], "filename": filename})
    return ok({"avatar": filename}, "头像已更新")


@app.get("/api/avatar/<username>")
def api_get_avatar(username):
    """取头像图片。前端服务器会替浏览器来取，所以这里照样要内部令牌（见 before_request）

    安全处理：工号只保留字母数字下划线，杜绝 ../ 这样的路径穿越。
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "", username)
    if safe:
        for ext in config.AVATAR_EXTS:
            path = os.path.join(config.AVATAR_DIR, "%s.%s" % (safe, ext))
            if os.path.isfile(path):
                return send_file(path)
    return fail("没有头像")


# ==========================================================================
# 七、人员管理（要"人员管理"权限，也就是只有管理员）
# ==========================================================================

@app.get("/api/users")
def api_users():
    """账号列表"""
    me, err = require_admin()
    if err:
        return err
    ret = post_db("/user/list")
    if not ret.get("ok"):
        return fail(ret.get("msg") or "读取账号列表失败")
    rows = ret["rows"]
    for r in rows:
        r.pop("password_hash", None)        # 密码哈希绝不出这个接口
    return ok(rows)


@app.post("/api/users")
def api_users_add():
    """新增账号。工号留空就按角色自动分配"""
    me, err = require_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    real_name = (d.get("real_name") or "").strip()
    department = (d.get("department") or "").strip()
    role = (d.get("role") or "").strip()

    if role not in config.ROLES:
        return fail("角色只能是：%s" % " / ".join(config.ROLES))
    if not PASSWORD_RE.match(password):
        return fail("密码需 8-32 位，且至少包含字母和数字")
    if not real_name:
        return fail("请填写真实姓名")
    if username and not re.match(r"^[A-Za-z0-9_]{3,20}$", username):
        return fail("工号需为 3-20 位的字母、数字或下划线")
    if not username:
        username = next_username(role)

    ret = post_db("/user/insert", {
        "username": username, "email": None,
        "password_hash": generate_password_hash(password),
        "real_name": real_name, "department": department or "未填写", "role": role,
    })
    if not ret.get("ok"):
        return fail(ret.get("msg") or "创建失败")
    return ok(None, "账号已创建：%s（%s）" % (username, role))


@app.post("/api/users/role")
def api_users_role():
    """调整角色"""
    me, err = require_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    role = (d.get("role") or "").strip()

    if role not in config.ROLES:
        return fail("角色只能是：%s" % " / ".join(config.ROLES))
    target, err = check_target(me, username, "role")
    if err:
        return err
    if target["role"] == role:
        return fail("该账号当前已经是「%s」" % role)

    post_db("/user/update_role", {"username": username, "role": role})
    return ok(None, "已把 %s 的角色调整为「%s」" % (username, role))


@app.post("/api/users/reset")
def api_users_reset():
    """重置某个账号的密码（管理员帮人找回密码的主要方式）

    这里不检查"不能操作自己"：重置自己的密码不会把系统弄坏，
    只是自己下次刷新页面要重新登录而已。
    """
    me, err = require_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""

    if not PASSWORD_RE.match(password):
        return fail("密码需 8-32 位，且至少包含字母和数字")
    if not post_db("/user/get", {"username": username}).get("row"):
        return fail("账号不存在：%s" % username)

    post_db("/user/update_password",
            {"username": username, "password_hash": generate_password_hash(password)})
    return ok(None, "已重置 %s 的密码" % username)


@app.post("/api/users/status")
def api_users_status():
    """启用 / 停用账号"""
    me, err = require_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    disabled = bool(d.get("disabled"))

    # 停用才需要"最后一个管理员"保护；启用是安全的，不用检查
    target, err = check_target(me, username, "status" if disabled else "")
    if err:
        return err

    post_db("/user/set_disabled", {"username": username, "disabled": disabled})
    return ok(None, "已%s账号 %s" % ("停用" if disabled else "启用", username))


@app.post("/api/users/delete")
def api_users_delete():
    """删除账号（登录审计不删）"""
    me, err = require_admin()
    if err:
        return err
    username = (request.get_json(silent=True) or {}).get("username", "").strip()

    target, err = check_target(me, username, "delete")
    if err:
        return err

    post_db("/user/delete", {"username": username})
    return ok(None, "已删除账号 %s" % username)


# ==========================================================================
# 八、注册邀请码（只有管理员能签发；不能签管理员）
# ==========================================================================

@app.get("/api/users/invites")
def api_invites():
    """邀请码列表"""
    me, err = require_admin()
    if err:
        return err
    ret = post_db("/invite/list")
    if not ret.get("ok"):
        return fail(ret.get("msg") or "读取邀请码失败")
    return ok(ret["rows"])


@app.post("/api/users/invites")
def api_invites_add():
    """签发邀请码：角色只能是组长 / 普工"""
    me, err = require_admin()
    if err:
        return err
    d = request.get_json(silent=True) or {}
    role = (d.get("role") or "").strip()

    if role not in (config.LEADER, config.WORKER):
        return fail("邀请码只能签「组长」或「普工」；管理员请在账号列表里调整角色")

    try:
        hours = int(d.get("hours") or 72)
    except (TypeError, ValueError):
        return fail("有效期小时数不合法")
    hours = max(1, min(hours, 24 * 30))         # 限 1 小时 ~ 30 天

    code = secrets.token_hex(4).upper()         # 8 位随机码
    expires = (datetime.datetime.now() + datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    post_db("/invite/add", {"code": code, "role": role, "creator": me["username"], "expires": expires})
    return ok({"code": code, "role": role, "hours": hours},
              "邀请码已生成（只显示这一次，请立即复制）")


@app.post("/api/users/invites/revoke")
def api_invites_revoke():
    """作废邀请码"""
    me, err = require_admin()
    if err:
        return err
    code = (request.get_json(silent=True) or {}).get("code", "").strip()
    ret = post_db("/invite/delete", {"code": code})
    if not ret.get("affected"):
        return fail("邀请码不存在：%s" % code)
    return ok(None, "邀请码 %s 已作废" % code)


# ==========================================================================
# 九、健康检查
# ==========================================================================

@app.get("/api/health")
def api_health():
    """本服务 + 数据库端 + MySQL 的状态（浏览器直接访问这个地址就能看）"""
    try:
        db_state = requests.get(config.DBSERVER_URL + "/health",
                                timeout=config.REQUEST_TIMEOUT).json()
    except Exception as e:
        db_state = {"ok": 0, "mysql": False, "error": str(e)[:200]}
    return ok({"service": "后端应用服务 5001", "db": db_state, "time": now_str()})


# ==========================================================================
# 十、兜底：任何没接住的错误也返回 JSON，便于后端/前端统一处理
# ==========================================================================

@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        return e
    print("[后端] 未处理的错误：%s" % e)
    return fail("服务内部错误：%s" % e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.BACKEND_PORT, debug=False)
