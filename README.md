# 下料站 MES（简单版）

一个"看得懂"的三端账号系统：登录注册、三级权限（管理员/组长/普工）、人员管理、邀请码、邮箱验证码找回密码、头像上传、登录审计。

代码刻意保持简单：**不用蓝图、不用装饰器、不用反射、不用熔断**，任何一个文件打开，从上往下读一遍就能明白。

---

## 一、三端是什么

```
浏览器 ──> 前端 5000 ──> 后端 5001 ──> 数据库端 5002 ──> 云端 MySQL
          页面/会话      业务判断        SQL / 建表
```

| 端 | 端口 | 目录 | 只做这些事 |
|---|---|---|---|
| 前端 | 5000 | `frontend/` | 渲染页面、记录"谁登录了"、把请求转发给后端 |
| 后端 | 5001 | `backend/` | 所有业务判断：密码对不对、有没有权限、验证码对不对 |
| 数据库端 | 5002 | `database/` | 只有它连 MySQL；只搬数据，不做任何业务判断 |

**为什么拆三端**：云数据库的密码只出现在数据库端，前端和后端即使被攻破也拿不到；而且数据库端挂掉时，页面还能正常打开并提示"数据库暂时不可用"。

---

## 二、第一次运行（三步）

### 第 1 步：填密钥

把 `secret_example.py` 复制一份、改名为 `secret_local.py`，填入两个值：

```python
DB_PASSWORD    = "云端 MySQL 的密码"
MAIL_AUTH_CODE = "邮箱 SMTP 授权码"
```

> 为什么要单独一个文件：这两个是"只能人工申请"的密码，放在代码里会被一起提交、一起分发。
> `secret_local.py` 已经在 `.gitignore` 里，不会跟着代码走。
> 其他密钥（服务间令牌、cookie 签名密钥）首次运行会**自动随机生成**，写在 `data/secret.txt`，不用管。

### 第 2 步：装依赖

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 如果已经有一个装好依赖的虚拟环境，也可以跳过这步，
> 直接把 `.venv` 放在本目录下，`start_all.bat` 会自动使用它。

### 第 3 步：一键启动

双击 **`start_all.bat`**，会打开三个窗口（数据库端 → 后端 → 前端），然后自动打开浏览器：

```
http://127.0.0.1:5000
```

默认管理员账号：**admin / admin123**（首次启动自动创建，请尽快改密码）。
数据库 `mes_simple` 和四张表也会在启动时自动创建。

---

## 三、目录说明

```
mes_simple/
├── config.py              三端共用配置：端口、地址、权限表、密钥读取
├── secret_example.py      密钥模板（进版本库）
├── secret_local.py        你填的真实密钥（不进版本库）
├── requirements.txt
├── start_all.bat
├── data/                  运行期自动生成：secret.txt、avatars/
├── frontend/
│   ├── server.py          页面路由 + session 登录态 + 转发给后端
│   ├── templates/         login.html / users.html / me.html / error.html
│   └── static/            css、js、images
├── backend/
│   ├── app.py             19 个业务接口，所有 if 判断都在这里
│   └── mail.py            发验证码邮件
└── database/
    ├── server.py          约 20 个 SQL 接口，一个接口一段 SQL
    ├── db.py              建库建表 + 连接
    └── manage_user.py     命令行应急工具（服务没起来时开号 / 改角色 / 重置密码）
```

---

## 四、自检与端口

### 一键自检

三个服务都启动后，再开一个命令行窗口，在项目根目录运行：

```bat
python smoke_test.py
```

它会真的走一遍完整流程（登录、建号、改角色、停用、邀请码注册、邮箱验证码注册、找回密码、
改密码被踢下线、上传头像、退出登录），每项打印 `PASS` / `FAIL`，跑完自动清理测试数据。
改了代码之后跑一下，就知道有没有改坏东西。

### 端口被占用怎么办

默认用 5000 / 5001 / 5002。如果被别的程序占了（比如你另一套 MES 还在跑），
可以用环境变量临时换一组，三个服务要设成**同一套**：

```bat
set MES_FRONTEND_PORT=5100
set MES_BACKEND_PORT=5101
set MES_DBSERVER_PORT=5102
python frontend\server.py
```

### 三端各自的健康检查

- 数据库端：`http://127.0.0.1:5002/health` —— 能连上 MySQL 吗
- 后端：`http://127.0.0.1:5001/api/health` —— 透传数据库端状态
- 前端：直接打开 `http://127.0.0.1:5000` 看登录页

---

## 五、常见问题

**Q：验证码邮件收不到？**
后端 5001 那个窗口会打印验证码（形如 `[邮件] ... 的验证码 = 123456`）。邮件发送失败时会自动降级到控制台，方便调试。

**Q：`无法连接数据库服务`？**
先看数据库端 5002 的窗口有没有报"数据库初始化失败"。也可以直接访问 `http://127.0.0.1:5002/health` 看 MySQL 连接状态。

**Q：管理员密码忘了？**
在 `database/` 目录下运行：

```bat
python manage_user.py --list
python manage_user.py --reset admin 新密码
```

**Q：能登录但看不到"人员管理"？**
那是权限设计：只有"管理员"有 `人员管理` 权限，组长和普工看不到。权限表在 `config.py` 的 `ROLE_PERMISSIONS`。

**Q：改了密码，另一台电脑还登录着？**
不会。改密码时 `token_version` 会 +1，其他浏览器下次刷新页面就会被踢回登录页。
