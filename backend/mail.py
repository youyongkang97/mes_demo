# -*- coding: utf-8 -*-
"""发验证码邮件

三件小事：
  1. SMTP 参数在 config.MAIL 里；
  2. 开一个后台线程去发，不让用户干等（发邮件要好几秒）；
  3. 发送失败、或者授权码没填，就把验证码打印到控制台 —— 保证流程能跑通、能演示。

用法（只有 backend/app.py 会用）：
    mail.send_code("123@qq.com", "654321", "register")
"""

import os
import smtplib
import sys
import threading
from email.header import Header
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

# 邮件里显示的用途名
_PURPOSE = {"register": "注册", "reset": "找回密码"}


def send_code(email_to, code, purpose):
    """发一封带验证码的邮件"""
    label = _PURPOSE.get(purpose, "账号")
    subject = "【下料站 MES】%s验证码" % label
    text = ("您的%s验证码是 %s，%d 分钟内有效，请勿泄露给他人。\n"
            "若非本人操作，请忽略本邮件。"
            % (label, code, max(1, config.CODE_TTL // 60)))

    if not config.MAIL.get("auth_code"):
        print("[邮件] 没配授权码，验证码只打印在控制台：%s → %s" % (email_to, code))
        return

    # 后台线程发送：主线程立刻返回，用户不用等
    threading.Thread(target=_send,
                     args=(email_to, subject, text, code),
                     daemon=True).start()


def _send(email_to, subject, text, code):
    """真正发信的过程（在后台线程里跑）"""
    try:
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = config.MAIL["user"]
        msg["To"] = email_to

        server = smtplib.SMTP_SSL(config.MAIL["host"], config.MAIL["port"], timeout=10)
        server.login(config.MAIL["user"], config.MAIL["auth_code"])
        server.sendmail(config.MAIL["user"], [email_to], msg.as_string())
        server.quit()
        print("[邮件] 验证码 %s 已发送至 %s" % (code, email_to))
    except Exception as e:
        # 发不出去也不影响注册流程：把验证码打出来，方便调试和演示
        print("[邮件] 发送失败（%s）" % e)
        print("[邮件] %s 的验证码 = %s" % (email_to, code))
