# -*- coding: utf-8 -*-
"""三端共用配置：前端 5000 / 后端 5001 / 数据库端 5002

三个服务都 import 这一个文件，所以配置只有一份，
不会出现"改了这边忘了那边"（旧版把令牌抄在两个 config 里，就是这个坑）。

需要改端口、改数据库地址、改权限，都只改这里。
密码类的东西**不写在这个文件里**，见下面"密钥"两段的说明。
"""

import os
import secrets

# ==================== 目录 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")            # 运行期生成的东西都放这里
SECRET_FILE = os.path.join(DATA_DIR, "secret.txt")   # 服务间密钥（自动生成）
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")       # 头像文件


# ==================== 密钥（一）：需要你自己填的 ====================
# 数据库密码、邮箱授权码这种"只能人工申请"的东西，放在 secret_local.py 里。
# secret_local.py 已经在 .gitignore 中，不会跟着代码走。
# 第一次使用：把 secret_example.py 复制一份、改名为 secret_local.py、填上密码。
try:
    from secret_local import DB_PASSWORD, MAIL_AUTH_CODE
except ImportError:
    raise SystemExit(
        "\n[配置缺失] 找不到 secret_local.py\n"
        "请把 secret_example.py 复制一份、改名为 secret_local.py，并填好：\n"
        "  DB_PASSWORD    —— 云端 MySQL 的密码\n"
        "  MAIL_AUTH_CODE —— 邮箱 SMTP 授权码\n")

if not DB_PASSWORD or not MAIL_AUTH_CODE:
    raise SystemExit(
        "\n[配置未填完] secret_local.py 里的 DB_PASSWORD / MAIL_AUTH_CODE 还是空的，请填好再启动。\n")


# ==================== 密钥（二）：能自动生成的 ====================
def _load_or_create_secrets():
    """生成 / 读取两把随机密钥：服务间令牌、Flask session 签名密钥

    - 第一次运行时随机生成并写到 data/secret.txt，之后每次读同一份；
    - 三个服务读的是**同一个文件**，所以密钥天然一致，不需要手抄；
    - 两把密钥分开存：服务间令牌和 cookie 签名密钥用途不同，
      万一其中一个泄露，另一个不受影响。
    """
    if not os.path.exists(SECRET_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32) + "\n")   # 第 1 行：服务间令牌
            f.write(secrets.token_hex(32) + "\n")   # 第 2 行：Flask 签名密钥
    with open(SECRET_FILE, "r", encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]
    return lines[0], lines[1]


INTERNAL_TOKEN, FLASK_SECRET = _load_or_create_secrets()


# ==================== 三端地址 ====================
# 默认就是 5000 / 5001 / 5002；一般不用改。
# 如果这几个端口被别的程序占用了（比如旧项目正在跑），可以临时换一组，
# 三个都要设成同一套，例如在命令行里：
#     set MES_BACKEND_PORT=5101 && set MES_DBSERVER_PORT=5102 && python backend\app.py
FRONTEND_PORT = int(os.environ.get("MES_FRONTEND_PORT", 5000))
BACKEND_PORT = int(os.environ.get("MES_BACKEND_PORT", 5001))
DBSERVER_PORT = int(os.environ.get("MES_DBSERVER_PORT", 5002))

BACKEND_URL = "http://127.0.0.1:%d" % BACKEND_PORT      # 前端转发到后端
DBSERVER_URL = "http://127.0.0.1:%d" % DBSERVER_PORT    # 后端转发到数据库端
REQUEST_TIMEOUT = 5                                     # 服务间调用超时（秒）


# ==================== 云端 MySQL（只有数据库端 5002 用得到） ====================
# 数据库名用独立的一个库，不和旧项目共用，避免互相影响。
DB = {
    "host": "203.195.204.32",
    "port": 3306,
    "user": "root",
    "password": DB_PASSWORD,        # ← 来自 secret_local.py
    "database": "mes_simple",       # ← 新库，首次启动自动创建
    "charset": "utf8mb4",
}


# ==================== 邮箱验证码 ====================
MAIL = {
    "host": "smtp.qq.com",
    "port": 465,                    # 465 用 SSL
    "user": "ingrin@foxmail.com",  # 发信邮箱
    "auth_code": MAIL_AUTH_CODE,    # ← 来自 secret_local.py
}

CODE_TTL = 300          # 验证码有效期（秒）
SEND_INTERVAL = 60      # 同一邮箱两次发码的最小间隔（秒）
CODE_MAX_FAILS = 5      # 同一个码最多允许输错几次

MAX_LOGIN_FAILS = 5     # 登录连续失败几次
LOCK_SECONDS = 60       # 锁定时长（秒）


# ==================== 角色与权限（全项目唯一的权限定义） ====================
ADMIN, LEADER, WORKER = "管理员", "组长", "普工"
ROLES = (ADMIN, LEADER, WORKER)

# 谁能做什么：key 是角色，value 是这个角色拥有的功能名。
# 只有这一张表 —— 接口里写 can(角色, "人员管理")，加功能只改这里。
ROLE_PERMISSIONS = {
    ADMIN:  ["人员管理"],
    LEADER: [],
    WORKER: [],
}


def can(role, perm):
    """这个角色有没有某项功能"""
    return perm in ROLE_PERMISSIONS.get(role, [])


def permissions_of(role):
    """这个角色拥有哪些功能（登录后发给前端，用来决定显示哪些菜单/按钮）"""
    return list(ROLE_PERMISSIONS.get(role, []))


# ==================== 头像上传 ====================
AVATAR_EXTS = ("png", "jpg", "jpeg", "webp", "gif")
AVATAR_MAX_BYTES = 2 * 1024 * 1024      # 2MB
