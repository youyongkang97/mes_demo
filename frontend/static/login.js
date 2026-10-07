/* ================= 背景车间场景(透视网格 / 传送带物料 / 悬浮粒子) ================= */
(function () {
  var cv = document.getElementById("scene");
  var ctx = cv.getContext("2d");
  var W = 0, H = 0;
  var mx = -9999, my = -9999;        // 鼠标位置(窗口坐标)

  function fit() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", fit); fit();

  window.addEventListener("mousemove", function (e) { mx = e.clientX; my = e.clientY; });
  window.addEventListener("mouseout", function () { mx = my = -9999; });

  function line(x1, y1, x2, y2) { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }

  // 传送带上的物料方块
  var cubes = [];
  function newCube(seed) {
    return {
      x: seed ? seed * (W + 240) - 120 : -120,
      s: 9 + Math.random() * 9,
      sp: 42 + Math.random() * 34,
      amber: Math.random() < 0.25,          // 少量琥珀色 = 不合格物料
      glow: 0, phase: Math.random() * 6.28
    };
  }
  function initCubes() {
    cubes = [];
    for (var i = 0; i < 11; i++) cubes.push(newCube(i / 11));
  }
  initCubes(); window.addEventListener("resize", initCubes);

  // 悬浮粒子
  var parts = [];
  for (var i = 0; i < 68; i++) {
    parts.push({ x: Math.random() * innerWidth, y: Math.random() * innerHeight,
                 v: 5 + Math.random() * 11, r: .8 + Math.random() * 1.7, a: .12 + Math.random() * .3 });
  }

  var beltY = 0, t0 = performance.now();
  function draw(now) {
    var t = (now - t0) / 1000, dt = Math.min((now - t0) / 1000 - (window.__lt || 0), .05);
    window.__lt = t;
    ctx.clearRect(0, 0, W, H);

    // ---- 透视网格(车间地面) ----
    var hy = H * 0.58, cx = W * 0.40;
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(56,189,248,.055)";
    for (var j = 1; j <= 9; j++) {
      var y = hy + (H - hy) * Math.pow(j / 9, 1.75);
      line(0, y, W, y);
    }
    for (var i = -14; i <= 14; i++) {
      line(cx + i * W * 0.013 + Math.sin(t * .22) * 8, hy, cx + i * W * 0.095, H);
    }

    // ---- 传送带 ----
    beltY = H * 0.78;
    ctx.fillStyle = "rgba(17,28,48,.6)";
    ctx.fillRect(0, beltY, W, 46);
    ctx.strokeStyle = "rgba(56,189,248,.26)";
    line(0, beltY, W, beltY); line(0, beltY + 46, W, beltY + 46);
    var off = (t * 56) % 36;
    ctx.strokeStyle = "rgba(56,189,248,.09)";
    for (var x = -36 + off; x < W + 36; x += 36) line(x, beltY + 46, x + 22, beltY);

    // ---- 物料方块(鼠标靠近 → 加速 + 发亮) ----
    for (var k = 0; k < cubes.length; k++) {
      var c = cubes[k];
      var near = (Math.abs(c.x - mx) < 190 && Math.abs(beltY - my) < 170) ? 1 : 0;
      c.glow += (near - c.glow) * .07;
      c.x += c.sp * (1 + c.glow * 1.15) * dt;
      if (c.x > W + 40) { c.x = -40; c.s = 9 + Math.random() * 9; }
      var col = c.amber ? "251,191,36" : "34,211,238";
      ctx.save();
      ctx.shadowColor = "rgba(" + col + "," + (.3 + .6 * c.glow) + ")";
      ctx.shadowBlur = 7 + 20 * c.glow;
      ctx.fillStyle = "rgba(" + col + "," + (.4 + .5 * c.glow) + ")";
      ctx.translate(c.x, beltY - c.s / 2 - 2);
      ctx.rotate(Math.sin(t * 1.6 + c.phase) * .07);
      ctx.fillRect(-c.s / 2, -c.s / 2, c.s, c.s);
      ctx.restore();
    }

    // ---- 粒子(鼠标轻吸引) ----
    for (var p = 0; p < parts.length; p++) {
      var q = parts[p];
      q.y -= q.v * dt; q.x += Math.sin(t + q.y * .01) * .3;
      var dx = mx - q.x, dy = my - q.y, d2 = dx * dx + dy * dy;
      var pull = d2 < 150 * 150 ? (1 - Math.sqrt(d2) / 150) : 0;
      if (pull > 0) { q.x += dx * pull * .012; q.y += dy * pull * .012; }
      if (q.y < -6) { q.y = H + 6; q.x = Math.random() * W; }
      if (q.x < -6) q.x = W + 6; if (q.x > W + 6) q.x = -6;
      ctx.beginPath();
      ctx.fillStyle = "rgba(125,211,252," + (q.a + pull * .5) + ")";
      ctx.arc(q.x, q.y, q.r + pull, 0, 6.283);
      ctx.fill();
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
})();

/* ================= 登录 / 注册交互 ================= */
(function () {
  var $ = function (id) { return document.getElementById(id); };   // 简化元素获取
  var alertBox = $("alert");

  function showAlert(msg, ok) {
    // ok 为 true 显示绿色成功样式,false 显示红色错误样式
    if (ok) {
      alertBox.className = "alert succ";
    } else {
      alertBox.className = "alert err";
    }
    alertBox.textContent = msg;
    if (!ok) { alertBox.style.animation = "none"; void alertBox.offsetWidth; alertBox.style.animation = ""; }
  }

  // ---- 面板切换(login / register / reset 三个面板;顶部标签随面板切换登录↔注册) ----
  var tabInk = $("tabInk");
  var mainTab = $("mainTab");
  var PANES = { login: $("loginForm"), register: $("regForm"), reset: $("resetForm") };
  function showPane(name) {
    if (name === "login" || name === "register") {
      if (name === "login") {
        mainTab.textContent = "登 录";
      } else {
        mainTab.textContent = "注 册";
      }
      mainTab.classList.add("active");
      tabInk.style.display = "";
    } else {                       // reset 面板不属于标签,下划线隐藏
      mainTab.classList.remove("active");
      tabInk.style.display = "none";
    }
    document.querySelectorAll(".pane").forEach(function (p) {
      p.classList.remove("active");
    });
    PANES[name].classList.add("active");
    alertBox.style.display = ""; alertBox.className = "alert";
    // 每个面板打开后自动聚焦到它自己的第一个输入框
    var focusId = "loginUser";
    if (name === "register") { focusId = "regEmail"; }
    if (name === "reset") { focusId = "resetEmail"; }
    $(focusId).focus();
  }
  // 点击顶部标签在登录/注册之间切换;找回密码面板点标签回登录
  mainTab.addEventListener("click", function () {
    var active = document.querySelector(".pane.active");
    if (!active || active.id === "resetForm") { showPane("login"); return; }
    if (active.id === "loginForm") {
      showPane("register");
    } else {
      showPane("login");
    }
  });
  $("toRegister").addEventListener("click", function () { showPane("register"); });
  $("toLogin").addEventListener("click", function () { showPane("login"); });
  $("toReset").addEventListener("click", function () { showPane("reset"); });
  $("resetToLogin").addEventListener("click", function () { showPane("login"); });
  if (/tab=register/.test(location.search)) showPane("register");
  $("loginUser").focus();

  // ---- 密码可见切换 ----
  document.querySelectorAll(".eye").forEach(function (b) {
    b.addEventListener("click", function () {
      var el = $(b.dataset.eye);
      if (el.type === "password") {
        el.type = "text";
      } else {
        el.type = "password";
      }
      if (el.type === "text") {
        b.style.opacity = "1";
      } else {
        b.style.opacity = ".72";
      }
    });
  });

  // ---- 注册密码强度 ----
  $("regPass").addEventListener("input", function () {
    var p = this.value, s = 0;
    if (p.length >= 8) s++;
    if (/[A-Za-z]/.test(p) && /\d/.test(p)) s++;
    if (p.length >= 12) s++;
    if (/[^A-Za-z0-9]/.test(p)) s++;
    // 有输入就显示强度条(pwbar s1~s4),没输入则不显示
    if (p) {
      $("pwbar").className = "pwbar s" + Math.min(s, 4);
    } else {
      $("pwbar").className = "pwbar";
    }
  });

  // ---- 请求封装(发给前端服务器,由它转发给后端) ----
  // 登录页只用这一种请求方式:POST 一个 JSON,拿回 {ok, msg, data}。
  // 登录态不用在这里管 —— 前端服务器会把"谁登录了"记在 session 里,
  // 浏览器之后每次请求会自动带上 cookie,不需要手动存令牌。
  function postJSON(url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {})
    }).then(function (r) { return r.json(); });
  }

  function busy(btn, on) {
    // on=true: 禁用按钮并显示"验证中";on=false: 恢复原文字
    btn.disabled = on;
    btn.dataset.text = btn.dataset.text || btn.textContent;
    if (on) {
      btn.textContent = "验 证 中 …";
    } else {
      btn.textContent = btn.dataset.text;
    }
  }

  // 登录 / 注册成功后的统一处理:提示一下 → 进人员管理页
  // (登录态已经由前端服务器写进 session,这里只管跳转)
  function onAuthed(res) {
    showAlert(res.msg, true);
    setTimeout(function () { location.href = "/users"; }, 450);
  }

  // ---- 邮箱验证码发送(注册/找回密码共用,含 60s 倒计时) ----
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  function attachSendCode(btnId, emailId, purpose) {
    var btn = $(btnId), timer = null, left = 0;
    function countdown() {
      left--;
      if (left <= 0) {
        clearInterval(timer); timer = null;
        btn.disabled = false; btn.textContent = "获取验证码";
      } else btn.textContent = left + "s 后重发";
    }
    btn.addEventListener("click", function () {
      var email = $(emailId).value.trim();
      if (!EMAIL_RE.test(email)) { showAlert("请先填写正确的邮箱"); $(emailId).focus(); return; }
      btn.disabled = true; btn.textContent = "发送中…";
      postJSON("/do/send_code", { email: email, purpose: purpose })
        .then(function (res) {
          showAlert(res.msg, res.ok === 1);
          if (res.ok !== 1) { btn.disabled = false; btn.textContent = "获取验证码"; return; }
          left = 60; btn.textContent = left + "s 后重发";
          timer = setInterval(countdown, 1000);
        })
        .catch(function () {
          showAlert("无法连接后端服务,请确认应用服务已启动");
          btn.disabled = false; btn.textContent = "获取验证码";
        });
    });
  }
  attachSendCode("regSendBtn", "regEmail", "register");
  attachSendCode("resetSendBtn", "resetEmail", "reset");

  // ---- 登录提交 ----
  $("loginForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var u = $("loginUser").value.trim(), p = $("loginPass").value;
    if (!u || !p) { showAlert("请输入工号与密码"); return; }
    busy($("loginBtn"), true);
    postJSON("/do/login", { username: u, password: p })
      .then(function (res) {
        if (res.ok === 1) { onAuthed(res); }
        else { busy($("loginBtn"), false); showAlert(res.msg); }
      })
      .catch(function () { busy($("loginBtn"), false); showAlert("无法连接后端服务,请确认应用服务已启动"); });
  });

  // ---- 注册提交(工号系统分配;身份由后端固定为普工,填了邀请码才按邀请码身份创建) ----
  $("regForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var mail = $("regEmail").value.trim(), code = $("regCode").value.trim();
    var invite = $("regInvite").value.trim();
    var p = $("regPass").value, p2 = $("regPass2").value;
    if (!EMAIL_RE.test(mail)) { showAlert("请填写正确的邮箱"); return; }
    if (!/^\d{6}$/.test(code)) { showAlert("请输入 6 位邮箱验证码(先点击「获取验证码」)"); return; }
    if (!/^(?=.*[A-Za-z])(?=.*\d).{8,32}$/.test(p)) { showAlert("密码需 8-32 位,且至少包含字母和数字"); return; }
    if (p !== p2) { showAlert("两次输入的密码不一致"); return; }
    busy($("regBtn"), true);
    postJSON("/do/register", { email: mail, code: code, password: p, confirm: p2, invite: invite })
      .then(function (res) {
        if (res.ok === 1) { onAuthed(res); }
        else { busy($("regBtn"), false); showAlert(res.msg); }
      })
      .catch(function () { busy($("regBtn"), false); showAlert("无法连接后端服务,请确认应用服务已启动"); });
  });

  // ---- 找回密码提交(成功后其它地方的登录全部失效,跳回登录) ----
  $("resetForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var mail = $("resetEmail").value.trim(), code = $("resetCode").value.trim();
    var p = $("resetPass").value, p2 = $("resetPass2").value;
    if (!EMAIL_RE.test(mail)) { showAlert("请填写正确的邮箱"); return; }
    if (!/^\d{6}$/.test(code)) { showAlert("请输入 6 位邮箱验证码"); return; }
    if (!/^(?=.*[A-Za-z])(?=.*\d).{8,32}$/.test(p)) { showAlert("新密码需 8-32 位,且至少包含字母和数字"); return; }
    if (p !== p2) { showAlert("两次输入的新密码不一致"); return; }
    busy($("resetBtn"), true);
    postJSON("/do/reset", { email: mail, code: code, new_password: p, confirm: p2 })
      .then(function (res) {
        busy($("resetBtn"), false);
        showAlert(res.msg, res.ok === 1);
        if (res.ok === 1) setTimeout(function () { showPane("login"); }, 1200);
      })
      .catch(function () { busy($("resetBtn"), false); showAlert("无法连接后端服务,请确认应用服务已启动"); });
  });
})();

// 立即执行函数（IIFE，Immediately Invoked Function Expression）是指在定义匿名函数后立即调用该函数。其主要作用是创建一个独立的作用域，从而避免变量污染全局作用域。
