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
if (passwordForm) passwordForm.addEventListener("submit", async e => {
  e.preventDefault();
  const p1 = $("pass1").value, p2 = $("pass2").value;
  if (p1.length < 15) return show("Mật khẩu phải có ít nhất 15 ký tự.");
  if (p1 !== p2) return show("Hai ô mật khẩu không khớp. Hãy nhập lại.");
  const btn = $("submitBtn");
  btn.disabled = true;
  try {
    const { status, data } = await post("/api/change-password", { password: p1 });
    if (status === 200) { location.href = "/" + keepJoin; return; }
    show(data.error || "Có lỗi. Thử lại sau.");
  } catch (err) {
    show("Không kết nối được. Kiểm tra mạng rồi thử lại.");
  }
  btn.disabled = false;
});

const leave = $("leave");
if (leave) leave.addEventListener("click", async () => {
  await post("/logout", {});
  location.href = "/login";
});
