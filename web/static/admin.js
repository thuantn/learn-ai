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
  refused: "Nhà cung cấp từ chối yêu cầu. Kiểm tra số dư và hạn mức.",
  unreachable: "Không kết nối được tới nhà cung cấp.",
  no_config: "Chưa có khóa để thử.",
};
const LOG_LABEL = {
  ask_approve: "Duyệt ô Hỏi", ask_reject: "Từ chối ô Hỏi", ask_off: "Tắt ô Hỏi", package_remove: "Gỡ package",
  ai_save: "Đổi nhà cung cấp hoặc khóa AI", set_admin: "Đổi quyền admin", set_quota: "Đổi hạn mức",
};
let providers = [];
let reviewing = null;

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

function showError(e) {
  $("adminError").textContent = e.message;
  $("adminError").hidden = false;
}

function pills(texts) {
  const box = el("div", "meta-pills");
  texts.filter(Boolean).forEach(t => box.append(el("span", "meta-pill", t)));
  return box;
}

function row(title, under, actions) {
  const r = el("article", "stream-row");
  const info = el("div", "lib-info");
  info.append(el("h3", "stream-title", title));
  under.forEach(x => info.append(x));
  r.append(info);
  if (actions && actions.length) {
    const act = el("div", "stream-actions");
    act.append(...actions);
    r.append(act);
  }
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
    ? `Đang dùng: ${status.source === "env" ? "khóa trong .env" : status.provider}, model ${status.model}, khóa kết thúc bằng ${status.last4}.`
    : "Chưa có khóa, ô Hỏi đang tắt với mọi bài.";
  const warnings = [];
  if (status.problem) warnings.push(PROBLEM[status.problem]);
  if (status.provider && !status.zdr) warnings.push("Nhà cung cấp này không xác nhận ZDR. Nội dung bài và câu hỏi có thể được lưu ở phía họ.");
  $("aiWarn").textContent = warnings.join(" ");
  $("aiWarn").hidden = !warnings.length;
}

async function load() {
  const d = await api("/api/admin/overview");
  fill("pendingList", "pendingEmpty", d.pending, p => row(p.title, [pills([p.owner, `${p.lessons} bài`])], [
    button("Đọc và duyệt", "btn-studio-primary", () => openReview(p.id)),
  ]));
  renderAi(d.ai, d.providers);
  fill("abuseList", "abuseEmpty", d.abuse, x => row(x.title, [
    pills([`Tác giả: ${x.owner}`, `Người báo: ${x.author || "đã xóa"}`, when(x.created_at)]),
    el("p", "fb-body", x.body),
  ], [
    button("Đọc nội dung", "btn-studio-secondary", () => openReview(x.package_id)),
    button("Gỡ package", "btn-studio-secondary btn-danger-soft", () => removePackage(x.package_id, x.title)),
  ]));
  fill("packageList", "packagesEmpty", d.packages, p => {
    const actions = [button("Đọc nội dung", "btn-studio-secondary", () => openReview(p.id))];
    if (p.ask_status === "approved") actions.push(button("Tắt ô Hỏi", "btn-studio-secondary", () => decide(p.id, "off")));
    actions.push(button("Gỡ", "btn-studio-secondary btn-danger-soft", () => removePackage(p.id, p.title)));
    return row(p.title, [pills([p.owner, `${p.lessons} bài`, size(p.size_bytes), `Bản ${p.version}`, ASK_LABEL[p.ask_status]])], actions);
  });
  fill("userList", null, d.users, u => row(u.name, [pills([u.admin && "Admin", `${size(u.used)} / ${size(u.quota)}`])]));
  fill("logList", "logEmpty", d.log, x => row(LOG_LABEL[x.action] || x.action, [pills([x.actor, when(x.at)]), el("p", "fb-body", [x.target, x.detail].filter(Boolean).join(" · "))]));
}

function section(title, lines) {
  const box = el("div", "admin-review-part");
  box.append(el("h4", "dock-kicker", title));
  lines.forEach(t => box.append(el("p", "fb-body", t)));
  return box;
}

async function openReview(id) {
  reviewing = null;
  const d = await api(`/api/admin/packages/${id}/review`);
  reviewing = { id, hash: d.ask_hash };
  $("reviewTitle").textContent = d.title;
  $("reviewAuthor").textContent = `Tác giả: ${d.author}. ${ASK_LABEL[d.ask_status]}.`;
  $("reviewZdr").hidden = d.zdr;
  $("reviewError").hidden = true;
  const body = $("reviewBody");
  body.textContent = "";
  d.lessons.forEach(l => {
    const box = el("article", "fb-card");
    box.append(el("h3", "stream-title", l.title));
    box.append(section("Tóm tắt", l.summary));
    box.append(section("Thẻ", l.cards.map(c => `${c.q} → ${c.a}`)));
    if (l.quiz.length) box.append(section("Quiz", l.quiz.map(q => `${q.q} → ${q.options[q.answer]}`)));
    box.append(section("Nội dung AI đọc", [l.content || "Bài này không có content.md."]));
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

async function removePackage(id, title) {
  const reason = prompt(`Gỡ "${title}"? Toàn bộ bài, tiến độ và góp ý của package này sẽ bị xóa. Ghi lý do:`);
  if (!reason || !reason.trim()) return;
  await api(`/api/admin/packages/${id}`, send("DELETE", { reason }));
  await load();
}

function guarded(run) {
  return e => {
    if (e && e.preventDefault) e.preventDefault();
    Promise.resolve().then(run).catch(showError);
  };
}

async function reviewDecision(decision) {
  try {
    await decide(reviewing.id, decision, reviewing.hash);
    $("reviewDialog").close();
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
    $("aiResult").textContent = "";
    const body = { provider: $("aiProvider").value, model: $("aiModel").value.trim() };
    if ($("aiKey").value.trim()) body.key = $("aiKey").value.trim();
    try {
      await api("/api/admin/ai", send("PUT", body));
      await load();
      $("aiResult").textContent = "Đã lưu.";
    } catch (e) {
      $("aiResult").textContent = SAVE_ERROR[e.code] || e.message;
    }
  }));
  $("aiTest").addEventListener("click", guarded(async () => {
    $("aiResult").textContent = "Đang thử…";
    const d = await api("/api/admin/ai/test", send("POST", {}));
    $("aiResult").textContent = TEST_RESULT[d.code] || "Không rõ kết quả.";
  }));
  load().catch(showError);
});
