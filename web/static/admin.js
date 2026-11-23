"use strict";
// The admin page. Package titles, lesson text and report bodies are written by other people, so they only ever go in with textContent.
const $ = id => document.getElementById(id);
const ASK_LABEL = { none: "Chưa xin ô Hỏi", pending: "Chờ duyệt", approved: "Ô Hỏi đang bật", rejected: "Ô Hỏi đã tắt hoặc bị từ chối" };
const SAVE_ERROR = {
  key_required: "Đổi nhà cung cấp thì cần nhập khóa mới.",
  key_bad: "Khóa không hợp lệ.",
  model_bad: "Tên model không hợp lệ.",
  provider_bad: "Nhà cung cấp không hợp lệ.",
  master_key_missing: "Server chưa có KEY_ENCRYPTION_KEY nên chưa lưu được khóa.",
  master_key_bad: "KEY_ENCRYPTION_KEY trên server bị sai định dạng.",
};
const PROBLEM = {
  master_key_missing: "Server thiếu KEY_ENCRYPTION_KEY, ô Hỏi đang tắt.",
  master_key_bad: "KEY_ENCRYPTION_KEY trên server sai định dạng, ô Hỏi đang tắt.",
  key_unreadable: "Không giải mã được khóa đã lưu, ô Hỏi đang tắt. Hãy nhập lại khóa.",
};
const TEST_RESULT = {
  ok: "Kết nối được, model chạy được.",
  auth: "Nhà cung cấp từ chối khóa này.",
  zdr_no_endpoint: "Model này không chạy được theo yêu cầu ZDR, hoặc không tồn tại. Chọn model khác.",
  refused: "Nhà cung cấp từ chối yêu cầu. Kiểm tra số dư, hạn mức và tên model.",
  no_answer: "Khóa đúng và có kết nối, nhưng model không trả lời được chữ nào. Chọn model khác.",
  unreachable: "Không kết nối được tới nhà cung cấp.",
  no_config: "Chưa có khóa để thử.",
};
const LOG_LABEL = {
  ask_approve: "Duyệt ô Hỏi", ask_reject: "Từ chối ô Hỏi", ask_off: "Tắt ô Hỏi", package_remove: "Gỡ gói bài",
  ai_save: "Đổi nhà cung cấp hoặc khóa AI", set_admin: "Đổi quyền admin", set_quota: "Đổi hạn mức",
  user_add: "Tạo tài khoản", user_reset: "Đặt lại mật khẩu", user_end_sessions: "Đăng xuất mọi nơi", user_remove: "Xóa tài khoản",
};
const LOG_ACTOR = { cli: "Dòng lệnh trên server" };
const LOG_DETAIL = { on: "bật", off: "tắt" };
let providers = [];
let reviewing = null;
let me = null;
let removingUser = null;
let credCurrent = null;
// The result of the last action, shown on the row whose button caused it and kept across the re-render that follows.
// Starting another action clears it, so an old result never sits next to a newer state.
const notes = new Map();

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}

function button(label, className, onClick) {
  const b = el("button", className, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function dangerButton(label, onClick, icon) {
  const b = button(label, "btn-studio-secondary btn-danger-soft row-danger", onClick);
  if (icon) b.dataset.icon = icon;
  return b;
}

function userButton(label, act, onClick, danger) {
  const b = danger ? dangerButton(label, onClick, "trash") : button(label, "btn-studio-secondary", onClick);
  b.dataset.userAct = act;
  return b;
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 403 && d.code === "must_change") { location.href = "/change-password"; throw new Error("password"); }
  if (!r.ok) { const e = new Error(d.error || "Có lỗi. Thử lại sau."); e.code = d.code; throw e; }
  return d;
}
const send = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function size(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1).replace(".", ",") + " GB";
  return (bytes ? Math.max(1, Math.round(bytes / 1024 / 1024)) : 0) + " MB";
}
const when = t => new Date(t * 1000).toLocaleString("vi-VN");

function alertBox(box, kind, text) {
  box.className = "studio-alert" + (kind ? " " + kind : "");
  box.textContent = text || "";
  box.hidden = !text;
}

// Page-level message, for things that have no row any more (a removed account or package) or a failed load.
function showMsg(kind, text) {
  alertBox($("adminMsg"), kind, text);
}
const showError = e => showMsg("error", e.message);

function noteFor(key) {
  const n = notes.get(key);
  if (!n) return null;
  const p = el("p", `studio-alert ${n.kind} row-note`, n.text);
  p.setAttribute("role", n.kind === "error" ? "alert" : "status");
  return p;
}

function say(key, kind, text) {
  notes.set(key, { kind, text });
  document.querySelectorAll(`.stream-row[data-key="${CSS.escape(key)}"]`).forEach(r => {
    const old = r.querySelector(".row-note");
    if (old) old.remove();
    r.append(noteFor(key));
  });
}

function clearNotes() {
  notes.clear();
  document.querySelectorAll(".row-note").forEach(n => n.remove());
  showMsg("", "");
}

function pills(texts) {
  const box = el("div", "meta-pills");
  texts.filter(Boolean).forEach(t => box.append(el("span", "meta-pill", t)));
  return box;
}

function row(title, under, actions, key) {
  const r = el("article", "stream-row admin-row");
  if (key) r.dataset.key = key;
  const info = el("div", "lib-info");
  info.append(el("h3", "stream-title", title));
  under.forEach(x => info.append(x));
  r.append(info);
  if (actions && actions.length) {
    const act = el("div", "stream-actions");
    act.append(...actions);
    r.append(act);
  }
  const n = key && noteFor(key);
  if (n) r.append(n);
  return r;
}

function fill(listId, emptyId, items, make) {
  const list = $(listId);
  list.textContent = "";
  items.forEach(x => list.append(make(x)));
  if (emptyId) $(emptyId).hidden = items.length > 0;
}

function renderAi(status, list) {
  providers = list;
  const select = $("aiProvider");
  select.textContent = "";
  list.forEach(p => {
    const o = el("option", "", p.zdr ? p.label : `${p.label} (không xác nhận ZDR)`);
    o.value = p.id;
    select.append(o);
  });
  if (status.source === "admin") select.value = status.provider;
  $("aiModel").value = status.source === "admin" ? status.model : (list[0] && list[0].default_model) || "";
  $("aiKey").value = "";
  $("aiCurrent").textContent = status.provider
    ? `Đang dùng: ${status.source === "env" ? "khóa cài sẵn trên server" : status.provider}, model ${status.model}, khóa kết thúc bằng ${status.last4}.`
    : "Chưa có khóa, ô Hỏi đang tắt với mọi bài.";
  const warnings = [];
  if (status.problem) warnings.push(PROBLEM[status.problem]);
  if (status.provider && !status.zdr) warnings.push("Nhà cung cấp này không xác nhận ZDR. Nội dung bài và câu hỏi có thể được lưu ở phía họ.");
  alertBox($("aiWarn"), "wait", warnings.join(" "));
}

async function resetPassword(name) {
  const ok = await askConfirm({ title: `Đặt lại mật khẩu cho ${name}?`,
    text: "Mật khẩu hiện tại hết tác dụng ngay và mọi phiên của người này bị đăng xuất. Bạn sẽ nhận mật khẩu tạm để gửi cho họ.", ok: "Đặt lại mật khẩu" });
  if (!ok) return;
  const d = await api(`/api/admin/users/${encodeURIComponent(name)}/reset-password`, send("POST", {}));
  openCredDialog(d.name, d.password, "Mật khẩu tạm mới");
  say(name, "ok", "Đã đặt lại mật khẩu. Người này cần đăng nhập bằng mật khẩu tạm.");
  await load();
}

async function endSessions(name, isSelf) {
  const ok = await askConfirm({ title: "Đăng xuất mọi nơi?",
    text: isSelf ? "Mọi phiên của bạn, kể cả trang này, sẽ bị đăng xuất. Bạn sẽ cần đăng nhập lại." : `Mọi thiết bị đang đăng nhập bằng ${name} sẽ phải đăng nhập lại.`,
    ok: "Đăng xuất mọi nơi" });
  if (!ok) return;
  await api(`/api/admin/users/${encodeURIComponent(name)}/end-sessions`, send("POST", {}));
  if (isSelf) { location.href = "/login"; return; }
  say(name, "ok", "Đã đăng xuất mọi phiên.");
  await load();
}

async function toggleAdmin(name, turnOn) {
  const ok = await askConfirm(turnOn
    ? { title: `Cấp quyền admin cho ${name}?`, text: "Người này sẽ quản lý được mọi tài khoản, gói bài và khóa AI.", ok: "Bật admin" }
    : { title: `Gỡ quyền admin của ${name}?`, text: "Người này sẽ không vào được trang Quản trị nữa.", ok: "Tắt admin" });
  if (!ok) return;
  await api(`/api/admin/users/${encodeURIComponent(name)}`, send("PUT", { admin: turnOn }));
  say(name, "ok", turnOn ? "Đã bật quyền admin." : "Đã tắt quyền admin.");
  await load();
}

async function setQuota(name, currentBytes) {
  const currentGb = Math.round(currentBytes / (1024 ** 3)) || 5;
  const ans = await askConfirm({ title: `Hạn mức dung lượng của ${name}`, ok: "Lưu hạn mức", field: {
    label: "Số GB, từ 1 đến 100", value: String(currentGb), inputmode: "numeric",
    check: v => (/^\d+$/.test(v) && +v >= 1 && +v <= 100 ? "" : "Hạn mức phải là số nguyên từ 1 đến 100."),
  } });
  if (!ans) return;
  await api(`/api/admin/users/${encodeURIComponent(name)}`, send("PUT", { quota_gb: +ans }));
  say(name, "ok", `Hạn mức mới: ${+ans} GB.`);
  await load();
}

function openRemoveDialog(name) {
  removingUser = name;
  $("userRemoveConfirm").value = "";
  $("userRemoveGo").disabled = true;
  $("userRemoveDialog").showModal();
}

function openCredDialog(name, password, title) {
  $("credTitle").textContent = title || "Đã tạo tài khoản";
  $("credName").textContent = name;
  $("credPass").value = password;
  const invite = "Chào bạn,\n\nTài khoản Học AI của bạn đã sẵn sàng.\nĐịa chỉ: " + location.origin + "/login\nTên đăng nhập: " + name + "\nMật khẩu tạm: " + password + "\n\nLần đầu đăng nhập, app sẽ yêu cầu bạn đặt mật khẩu mới.";
  $("credMail").href = "mailto:" + encodeURIComponent(name) + "?subject=" + encodeURIComponent("Tài khoản Học AI") + "&body=" + encodeURIComponent(invite);
  credCurrent = { name, password, invite };
  $("credDialog").showModal();
}

function clearCredDialog() {
  $("credPass").value = "";
  $("credMail").removeAttribute("href");
  $("credName").textContent = "";
  credCurrent = null;
}

async function copyText(text, fallbackElem) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (e) {}
  }
  if (fallbackElem && fallbackElem.select) {
    fallbackElem.select();
    document.execCommand("copy");
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

function filterUsers() {
  const q = $("userSearch").value.trim().toLowerCase();
  let shown = 0;
  $("userList").querySelectorAll(".stream-row").forEach(r => {
    const hit = !q || r.dataset.key.includes(q);
    r.hidden = !hit;
    if (hit) shown++;
  });
  $("userNoMatch").hidden = shown > 0;
}

async function load() {
  if (!me) me = await api("/api/me");
  const d = await api("/api/admin/overview");
  const counts = { pending: d.pending.length, users: d.users.length, abuse: d.abuse.length, packages: d.packages.length };
  document.querySelectorAll("[data-count]").forEach(s => { s.textContent = counts[s.dataset.count] || ""; });
  // Work waiting for the admin stands out on its tab.
  ["pending", "abuse"].forEach(k => $("tab-" + k).classList.toggle("has-work", counts[k] > 0));
  fill("pendingList", "pendingEmpty", d.pending, p => row(p.title, [pills([
    p.owner,
    p.lessons ? `${p.lessons} bài` : null,
    p.tests ? `${p.tests} đề` : null,
  ])], [
    button("Đọc và duyệt", "btn-studio-primary", guarded(() => openReview(p.id))),
  ], "pending:" + p.id));
  fill("userList", null, d.users, u => {
    const isSelf = !!(me && (me.id === u.name || me.name === u.name));
    const pillList = [
      isSelf && "Bạn",
      u.admin && "Admin",
      u.must_change && "Chưa đổi mật khẩu tạm",
      `${u.sessions || 0} phiên`,
      `${size(u.used)} / ${size(u.quota)}`,
    ];
    const key = u.name;
    const actions = isSelf ? [
      userButton("Đăng xuất mọi nơi", "end", guarded(() => endSessions(u.name, true), key)),
      userButton("Hạn mức", "quota", guarded(() => setQuota(u.name, u.quota), key)),
    ] : [
      userButton("Đặt lại mật khẩu", "reset", guarded(() => resetPassword(u.name), key)),
      userButton("Đăng xuất mọi nơi", "end", guarded(() => endSessions(u.name, false), key)),
      userButton(u.admin ? "Tắt admin" : "Bật admin", "admin", guarded(() => toggleAdmin(u.name, !u.admin), key)),
      userButton("Hạn mức", "quota", guarded(() => setQuota(u.name, u.quota), key)),
      userButton("Xóa", "remove", guarded(() => openRemoveDialog(u.name), key), true),
    ];
    return row(u.name, [pills(pillList)], actions, key);
  });
  $("userSearchBox").hidden = d.users.length < 8;
  filterUsers();
  renderAi(d.ai, d.providers);
  fill("abuseList", "abuseEmpty", d.abuse, x => row(x.title, [
    pills([`Tác giả: ${x.owner}`, `Người báo: ${x.author || "đã xóa"}`, when(x.created_at)]),
    el("p", "fb-body", x.body),
  ], [
    button("Đọc nội dung", "btn-studio-secondary", guarded(() => openReview(x.package_id))),
    dangerButton("Gỡ gói bài", guarded(() => removePackage(x.package_id, x.title), "abuse:" + x.package_id), "trash"),
  ], "abuse:" + x.package_id));
  fill("packageList", "packagesEmpty", d.packages, p => {
    const key = "pkg:" + p.id;
    const actions = [button("Đọc nội dung", "btn-studio-secondary", guarded(() => openReview(p.id), key))];
    if (p.ask_status === "approved") actions.push(button("Tắt ô Hỏi", "btn-studio-secondary", guarded(() => askOff(p.id, p.title), key)));
    actions.push(dangerButton("Gỡ gói bài", guarded(() => removePackage(p.id, p.title), key), "trash"));
    return row(p.title, [pills([
      p.owner,
      p.lessons ? `${p.lessons} bài` : null,
      p.tests ? `${p.tests} đề` : null,
      size(p.size_bytes),
      `Bản ${p.version}`,
      ASK_LABEL[p.ask_status],
    ])], actions, key);
  });
  fill("logList", "logEmpty", d.log, x => row(LOG_LABEL[x.action] || x.action, [
    pills([LOG_ACTOR[x.actor] || x.actor, when(x.at)]),
    el("p", "fb-body", [x.target, LOG_DETAIL[x.detail] || x.detail].filter(Boolean).join(" · ")),
  ]));
  return counts;
}

// One tab per section. The open tab is kept in the URL (#users, #log...) so a reload or a shared link opens it.
const TABS = () => [...document.querySelectorAll(".admin-tab")];

function showTab(name, focus) {
  TABS().forEach(t => {
    const on = t.dataset.tab === name;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    $("panel-" + t.dataset.tab).hidden = !on;
    if (on && focus) t.focus();
    // On a phone the tab bar scrolls sideways: keep the open tab in view.
    if (on) t.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
}

function tabFromHash() {
  const name = location.hash.slice(1);
  return TABS().some(t => t.dataset.tab === name) ? name : "";
}

function initTabs() {
  const tabs = TABS();
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => showTab(t.dataset.tab));
    t.addEventListener("keydown", e => {
      const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
      if (to === undefined) return;
      e.preventDefault();
      showTab(tabs[(to + tabs.length) % tabs.length].dataset.tab, true);
    });
  });
  window.addEventListener("hashchange", () => { const n = tabFromHash(); if (n) showTab(n); });
}

// The review lists everything the AI will read. Each lesson or test folds, and starts open.
function part(title, open) {
  const box = el("details", "fb-card admin-review-item");
  box.open = open;
  box.append(el("summary", "stream-title", title));
  return box;
}

function section(title, lines) {
  const box = el("div", "admin-review-part");
  box.append(el("h4", "dock-kicker", title));
  lines.forEach(t => box.append(el("p", "fb-body", t)));
  return box;
}

function choices(options, isRight, why) {
  const list = el("ul", "admin-choices");
  options.forEach((text, i) => {
    const li = el("li", isRight(i) ? "is-right" : "");
    li.append(el("span", "", text));
    if (isRight(i)) li.append(el("span", "meta-pill", "✓ Đáp án đúng"));
    if (why && why(i)) li.append(el("span", "admin-why", why(i)));
    list.append(li);
  });
  return list;
}

async function openReview(id) {
  reviewing = null;
  const d = await api(`/api/admin/packages/${id}/review`);
  reviewing = { id, hash: d.ask_hash };
  $("reviewTitle").textContent = d.title;
  const counts = [(d.lessons || []).length && `${d.lessons.length} bài`, (d.tests || []).length && `${d.tests.length} đề`].filter(Boolean).join(", ");
  $("reviewAuthor").textContent = `Tác giả: ${d.author}. ${ASK_LABEL[d.ask_status]}.${counts ? ` ${counts}.` : ""}`;
  $("reviewZdr").hidden = d.zdr;
  $("reviewError").hidden = true;
  const body = $("reviewBody");
  body.textContent = "";
  (d.lessons || []).forEach(l => {
    const box = part(l.title, true);
    box.append(section("Tóm tắt", l.summary));
    box.append(section("Thẻ", l.cards.map(c => `${c.q} → ${c.a}`)));
    if (l.quiz.length) {
      const quiz = section("Quiz", []);
      l.quiz.forEach(q => {
        quiz.append(el("p", "fb-body admin-q", q.q));
        quiz.append(choices(q.options, i => i === q.answer));
        if (q.why) quiz.append(el("p", "admin-why", `Giải thích: ${q.why}`));
      });
      box.append(quiz);
    }
    box.append(section("Nội dung AI đọc", [l.content || "Bài này không có content.md."]));
    body.append(box);
  });
  (d.tests || []).forEach(t => {
    const box = part(`Bộ đề: ${t.title}`, true);
    const testMeta = [];
    if (t.description) testMeta.push(`Mô tả: ${t.description}`);
    testMeta.push(`Số câu: ${t.items ? t.items.length : 0}`);
    if (t.time_limit_minutes) testMeta.push(`Thời gian: ${t.time_limit_minutes} phút`);
    testMeta.push(`Ngưỡng đậu: ${t.pass_percent || 70}%`);
    box.append(section("Thông tin đề", testMeta));
    (t.items || []).forEach((it, idx) => {
      const q = section(`Câu ${idx + 1}${it.domain ? ` · ${it.domain}` : ""}`, [it.question]);
      const opts = it.options || [];
      q.append(choices(opts.map(o => `${o.id}. ${o.text}`), i => !!(it.correct && it.correct.includes(opts[i].id)), i => opts[i].why && `Vì sao: ${opts[i].why}`));
      if (it.explanation) q.append(el("p", "fb-body", `Lời giải: ${it.explanation}`));
      if (it.best_practice) q.append(el("p", "fb-body", `Best practice: ${it.best_practice}`));
      if (it.docs && it.docs.length) q.append(el("p", "fb-body", `Tài liệu: ${it.docs.join("; ")}`));
      box.append(q);
    });
    body.append(box);
  });
  $("reviewApprove").hidden = d.ask_status !== "pending";
  $("reviewReject").hidden = d.ask_status !== "pending";
  $("reviewDialog").showModal();
}

async function decide(id, decision, hash) {
  await api(`/api/admin/packages/${id}/ask`, send("POST", { decision, ask_hash: hash }));
  await load();
}

async function askOff(id, title) {
  const ok = await askConfirm({ title: `Tắt ô Hỏi của "${title}"?`, text: "Người học không hỏi được nữa. Muốn bật lại, tác giả phải xin duyệt lại.", ok: "Tắt ô Hỏi" });
  if (!ok) return;
  await decide(id, "off");
  say("pkg:" + id, "ok", "Đã tắt ô Hỏi.");
}

async function removePackage(id, title) {
  const reason = await askConfirm({ title: `Gỡ "${title}"?`, danger: true, icon: "trash", ok: "Gỡ gói bài",
    text: "Toàn bộ bài, tiến độ và góp ý của gói này bị xóa. Không hoàn tác được.",
    field: { label: "Lý do (ghi vào nhật ký)", check: v => (v ? "" : "Cần ghi lý do.") } });
  if (!reason) return;
  await api(`/api/admin/packages/${id}`, send("DELETE", { reason }));
  await load();
  showMsg("ok", `Đã gỡ "${title}".`);
}

// Runs an action; its error shows on the row (key) it came from, or at the top of the page.
function guarded(run, key) {
  return e => {
    if (e && e.preventDefault) e.preventDefault();
    clearNotes();
    Promise.resolve().then(run).catch(err => {
      if (err.message === "login" || err.message === "password") return;
      if (key) say(key, "error", err.message); else showError(err);
    });
  };
}

async function reviewDecision(decision) {
  try {
    await decide(reviewing.id, decision, reviewing.hash);
    $("reviewDialog").close();
    showMsg("ok", decision === "approve" ? "Đã duyệt, ô Hỏi đã bật cho gói này." : "Đã từ chối.");
  } catch (e) {
    $("reviewError").textContent = e.message;
    $("reviewError").hidden = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("reviewClose").addEventListener("click", () => $("reviewDialog").close());
  $("reviewApprove").addEventListener("click", () => reviewDecision("approve"));
  $("reviewReject").addEventListener("click", () => reviewDecision("reject"));
  $("aiProvider").addEventListener("change", () => {
    const p = providers.find(x => x.id === $("aiProvider").value);
    if (p) $("aiModel").value = p.default_model;
  });
  $("aiForm").addEventListener("submit", guarded(async () => {
    alertBox($("aiResult"), "", "");
    const body = { provider: $("aiProvider").value, model: $("aiModel").value.trim() };
    if ($("aiKey").value.trim()) body.key = $("aiKey").value.trim();
    try {
      await api("/api/admin/ai", send("PUT", body));
      await load();
      alertBox($("aiResult"), "ok", "Đã lưu.");
    } catch (e) {
      alertBox($("aiResult"), "error", SAVE_ERROR[e.code] || e.message);
    }
  }));
  $("aiTest").addEventListener("click", guarded(async () => {
    alertBox($("aiResult"), "wait", "Đang thử…");
    try {
      const d = await api("/api/admin/ai/test", send("POST", {}));
      alertBox($("aiResult"), d.code === "ok" ? "ok" : "error", TEST_RESULT[d.code] || "Không rõ kết quả.");
    } catch (e) {
      alertBox($("aiResult"), "error", e.message);
    }
  }));

  $("userAddForm").addEventListener("submit", guarded(async () => {
    const input = $("userAddName");
    const name = input.value.trim().toLowerCase();
    alertBox($("userAddMsg"), "", "");
    if (!name) return;
    try {
      const d = await api("/api/admin/users", send("POST", { name }));
      input.value = "";
      openCredDialog(d.name, d.password);
      say(d.name, "ok", "Tài khoản mới. Gửi mật khẩu tạm cho người này.");
      await load();
    } catch (e) {
      alertBox($("userAddMsg"), "error", e.message);
    }
  }));
  $("userSearch").addEventListener("input", filterUsers);

  $("userRemoveConfirm").addEventListener("input", () => {
    $("userRemoveGo").disabled = $("userRemoveConfirm").value !== removingUser;
  });
  $("userRemoveCancel").addEventListener("click", () => {
    $("userRemoveDialog").close();
  });
  $("userRemoveGo").addEventListener("click", guarded(async () => {
    const name = removingUser;
    const confirm = $("userRemoveConfirm").value;
    $("userRemoveDialog").close();
    try {
      await api(`/api/admin/users/${encodeURIComponent(name)}`, send("DELETE", { confirm }));
    } catch (e) {
      say(name, "error", e.message);
      return;
    }
    await load();
    showMsg("ok", `Đã xóa tài khoản ${name}.`);
  }));

  $("credClose").addEventListener("click", () => {
    $("credDialog").close();
    clearCredDialog();
  });
  $("credDialog").addEventListener("close", clearCredDialog);
  const copied = (id, label) => {
    $(id).textContent = "Đã chép";
    setTimeout(() => { $(id).textContent = label; }, 2000);
  };
  $("credCopy").addEventListener("click", guarded(async () => {
    if (credCurrent) { await copyText(credCurrent.password, $("credPass")); copied("credCopy", "Chép mật khẩu"); }
  }));
  $("credCopyInvite").addEventListener("click", guarded(async () => {
    if (credCurrent) { await copyText(credCurrent.invite); copied("credCopyInvite", "Chép lời mời"); }
  }));

  initTabs();
  // Without a tab in the URL, open where work is waiting.
  load().catch(e => { showError(e); return {}; }).then(c => {
    showTab(tabFromHash() || (c.pending ? "pending" : c.abuse ? "abuse" : "users"));
  });
});
