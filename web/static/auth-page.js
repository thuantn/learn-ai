"use strict";
const $ = id => document.getElementById(id);
// A share link must survive logging in and changing the temporary password.
const keepJoin = /^#join=[\w.-]+$/.test(location.hash) ? location.hash : "";

function show(message, kind) {
  const box = $("alertBox");
  box.className = "studio-alert " + (kind || "error");
  box.textContent = message;
}

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = {};
  try { data = await r.json(); } catch (e) { /* server sent no JSON */ }
  return { status: r.status, data };
}

document.querySelectorAll("[data-eye]").forEach(btn => btn.addEventListener("click", () => {
  const input = $(btn.dataset.eye);
  const hidden = input.type === "password";
  input.type = hidden ? "text" : "password";
  btn.textContent = hidden ? "Ẩn" : "Hiện";
}));

const loginForm = $("loginForm");
if (loginForm) loginForm.addEventListener("submit", async e => {
  e.preventDefault();
  const btn = $("submitBtn");
  btn.disabled = true;
  try {
    const { status, data } = await post("/login", { username: $("loginUser").value, password: $("loginPass").value });
    if (status === 200) { location.href = (data.must_change ? "/change-password" : "/") + keepJoin; return; }
    show(data.error || "Có lỗi. Thử lại sau.", status === 429 ? "wait" : "error");
  } catch (err) {
    show("Không kết nối được. Kiểm tra mạng rồi thử lại.");
  }
  btn.disabled = false;
});

const passwordForm = $("passwordForm");
let isVoluntary = false;
if (passwordForm) {
  fetch("/api/me").then(r => {
    if (r.status === 200) {
      isVoluntary = true;
      const p0 = $("pass0Block");
      if (p0) p0.hidden = false;
      const pill = document.querySelector(".status-pill");
      if (pill) pill.textContent = "Tài khoản";
      const lead = document.querySelector(".auth-lead");
      if (lead) lead.textContent = "Đổi mật khẩu của bạn. Sau khi đổi, các thiết bị khác sẽ phải đăng nhập lại.";
      const back = $("backHome");
      if (back) back.hidden = false;
    }
  }).catch(() => {});

  passwordForm.addEventListener("submit", async e => {
    e.preventDefault();
    const p1 = $("pass1").value, p2 = $("pass2").value;
    if (p1.length < 15) return show("Mật khẩu phải có ít nhất 15 ký tự.");
    if (p1 !== p2) return show("Hai ô mật khẩu không khớp. Hãy nhập lại.");
    const body = { password: p1 };
    if (isVoluntary) {
      body.current = $("pass0") ? $("pass0").value : "";
    }
    const btn = $("submitBtn");
    btn.disabled = true;
    try {
      const { status, data } = await post("/api/change-password", body);
      if (status === 200) {
        if (isVoluntary) {
          show("Đã đổi mật khẩu.", "ok");
          setTimeout(() => { location.href = "/"; }, 1000);
          return;
        }
        location.href = "/" + keepJoin;
        return;
      }
      show(data.error || "Có lỗi. Thử lại sau.", status === 429 ? "wait" : "error");
    } catch (err) {
      show("Không kết nối được. Kiểm tra mạng rồi thử lại.");
    }
    btn.disabled = false;
  });
}

const leave = $("leave");
if (leave) leave.addEventListener("click", async () => {
  await post("/logout", {});
  location.href = "/login";
});
