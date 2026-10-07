# -*- coding: utf-8 -*-
"""数据库端的连接与初始化

只做两件事：
  1. get_conn() / query / execute —— 拿连接、查、改
  2. init_db()                     —— 启动时建库、建表、建默认管理员

每次用完就 close：代码最简单，不用维护连接池。
本项目请求量很小（几十个人用），够用。

运行这个文件不需要，它被 server.py 和 manage_user.py import 使用。
"""

import datetime
import os
import sys

import pymysql
from werkzeug.security import generate_password_hash

# 把项目根目录加进模块搜索路径，这样才能 import 到根目录的 config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


# ==================== 连接与查询 ====================

def get_conn():
    """拿一个 MySQL 连接（autocommit 关着，改数据后要 commit）"""
    return pymysql.connect(**config.DB)


def query_all(sql, args=()):
    """查询多行，返回 list[dict]；row["username"] 这样取值，不用记下标"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, args=()):
    """查询一行，查不到返回 None"""
    conn = get_conn()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        conn.close()


def execute(sql, args=()):
    """增 / 删 / 改，返回影响行数（0 表示没有匹配的行）"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        n = cur.execute(sql, args)
        conn.commit()
        return n
    finally:
        conn.close()


# ==================== 时间处理 ====================

def now():
    """统一的时间字符串格式（存库、返回给后端都用它）"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean(row):
    """把一行里的时间字段转成字符串

    为什么需要：PyMySQL 取 DATETIME 回来是 Python 的 datetime 对象，
    而 JSON 不认识它 —— 直接返回会被 Flask 序列化成
    "Fri, 19 Sep 2026 20:31:24 GMT" 这种奇怪格式，后端不好解析。
    所以在这里统一转成 "2026-10-07 22:00:00"，三端都省心。
    """
    if row is None:
        return None
    return {k: (v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v)
            for k, v in row.items()}


def clean_all(rows):
    """一批行都做同样的处理"""
    return [clean(r) for r in rows]


# ==================== 初始化（建库 / 建表 / 默认管理员） ====================

DEFAULT_ADMIN = ("admin", "admin123")   # 首次启动自动创建，登录后请尽快改密码

_TABLES = [
    # 账号主表
    """CREATE TABLE IF NOT EXISTS users (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        username      VARCHAR(64)  NOT NULL UNIQUE,     -- 工号，系统分配，用户不可改
        password_hash VARCHAR(255) NOT NULL,            -- 只存哈希，绝不存明文
        email         VARCHAR(191) NULL UNIQUE,         -- 可空 + 唯一：管理员开的号没有邮箱
        real_name     VARCHAR(30)  NOT NULL DEFAULT '',
        department    VARCHAR(30)  NOT NULL DEFAULT '',
        role          VARCHAR(16)  NOT NULL DEFAULT '普工',
        disabled      TINYINT(1)   NOT NULL DEFAULT 0,  -- 1 = 已停用（软删除，可恢复）
        created_at    DATETIME     NOT NULL,
        last_login    DATETIME     NULL,
        login_count   INT          NOT NULL DEFAULT 0,
        token_version INT          NOT NULL DEFAULT 0,  -- 改密码后 +1，让其他地方的登录失效
        nickname      VARCHAR(30)  NOT NULL DEFAULT '',
        gender        VARCHAR(8)   NOT NULL DEFAULT '保密',
        avatar        VARCHAR(64)  NOT NULL DEFAULT ''
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # 登录审计：只增不改。不加外键，因为删账号时这条记录要保留
    """CREATE TABLE IF NOT EXISTS login_log (
        id       INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(64) NOT NULL,
        ip       VARCHAR(64) NOT NULL DEFAULT '',
        success  TINYINT(1)  NOT NULL DEFAULT 1,
        ts       DATETIME    NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # 邮箱验证码：邮箱做主键，所以"重发"可以用一条 SQL 覆盖旧码
    """CREATE TABLE IF NOT EXISTS email_code (
        email     VARCHAR(191) NOT NULL PRIMARY KEY,
        code      VARCHAR(16)  NOT NULL,
        created   DATETIME     NOT NULL,            -- 用来算 300 秒有效期
        last_sent DATETIME     NOT NULL,            -- 用来算 60 秒发送间隔
        fails     INT          NOT NULL DEFAULT 0   -- 连续错几次作废
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # 注册邀请码：一次性、有有效期、不能签管理员
    """CREATE TABLE IF NOT EXISTS invite_code (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        code       VARCHAR(8)  NOT NULL UNIQUE,
        role       VARCHAR(16) NOT NULL,
        creator    VARCHAR(64) NOT NULL,
        expires    DATETIME    NOT NULL,
        used_by    VARCHAR(64) NULL,
        used_at    DATETIME    NULL,
        created_at DATETIME    NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def _ensure_database():
    """建库（不指定库名连接，否则库不存在会直接连不上）"""
    cfg = dict(config.DB)
    cfg.pop("database")
    conn = pymysql.connect(**cfg)
    try:
        cur = conn.cursor()
        cur.execute("CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARACTER SET utf8mb4"
                    % config.DB["database"])
        conn.commit()
    finally:
        conn.close()


def _ensure_default_admin():
    """库里一个账号都没有时，建一个默认管理员"""
    if query_one("SELECT COUNT(*) AS c FROM users")["c"] == 0:
        execute(
            "INSERT INTO users (username, password_hash, real_name, department, role, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (DEFAULT_ADMIN[0], generate_password_hash(DEFAULT_ADMIN[1]),
             "系统管理员", "MES 运维", config.ADMIN, now()))
        print("[db] 已创建默认管理员：%s / %s（请尽快改密码）" % DEFAULT_ADMIN)


def init_db():
    """建库 → 建表 → 建默认管理员

    可以重复执行（CREATE ... IF NOT EXISTS）。
    失败只打印告警、不退出：数据库暂时连不上时服务照常启动，
    可以从 /health 看到具体原因，等数据库恢复后自动就好。
    """
    try:
        _ensure_database()
        for sql in _TABLES:
            execute(sql)
        _ensure_default_admin()
        print("[db] 初始化完成 → %s@%s/%s"
              % (config.DB["user"], config.DB["host"], config.DB["database"]))
    except Exception as e:
        print("[db] 初始化失败，服务降级运行：%s" % e)
