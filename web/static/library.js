"use strict";
// Library, upload, share and the author's feedback list. Text from packages only ever goes in with textContent.
const MAX_ZIP = 90 * 1024 * 1024;
let upload = { xhr: null, id: null, removed: [] };
let sharing = null;

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}
function actionButton(label, act, id, className) {
  const b = el("button", className || "btn-studio-secondary", label);
  b.type = "button";
  b.dataset.act = act;
  if (id) b.dataset.id = id;
  return b;
}
function size(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1).replace(".", ",") + " GB";
  return (bytes ? Math.max(1, Math.round(bytes / 1024 / 1024)) : 0) + " MB";
}

// ---------- Library ----------
async function loadLibrary() {
  const box = $("libMine");
  try {
    const d = await api("/api/packages");
    state.library = d;
    renderLibrary(d);
  } catch (e) {
    if (e.message === "login" || e.message === "password") return;
    box.textContent = e.message;
  }
}

const ASK_LABEL = { pending: "Ô Hỏi: chờ admin duyệt", approved: "Ô Hỏi: đang bật", rejected: "Ô Hỏi: đã tắt hoặc bị từ chối" };

function renderLibrary(d) {
  $("libAdmin").hidden = !(state.me && state.me.admin);
  $("libUsed").textContent = `${size(d.used)} / ${size(d.quota)}`;
  $("libMeter").style.width = Math.min(100, d.used / d.quota * 100) + "%";
  const mine = $("libMine");
  mine.textContent = "";
  d.mine.forEach(p => {
    const row = el("article", "stream-row");
    const info = el("div", "lib-info");
    info.append(el("h3", "stream-title", p.title));
    const pills = el("div", "meta-pills");
    const pillList = [
      p.topic && `Chủ đề: ${p.topic}`,
      p.lessons && p.lessons.length ? `${p.lessons.length} bài` : null,
      p.tests && p.tests.length ? `${p.tests.length} đề` : null,
      size(p.size_bytes),
      `${p.people} người được share`,
      p.link_on && "Link đang bật"
    ].filter(Boolean);
    pillList.forEach(t => pills.append(el("span", "meta-pill", t)));
    if (ASK_LABEL[p.ask_status]) pills.append(el("span", "meta-pill", ASK_LABEL[p.ask_status]));
    info.append(pills);
    const act = el("div", "stream-actions");
    if (p.first_lesson) {
      const learn = actionButton("Học", "start", null, "btn-studio-primary");
      learn.dataset.lesson = p.first_lesson;
      act.append(learn);
    }
    if (p.tests && p.tests.length > 0) {
      const doTests = actionButton("Làm đề", "lib-tests", p.id, p.first_lesson ? "btn-studio-secondary" : "btn-studio-primary");
      act.append(doTests);
      act.append(actionButton("Thống kê đề", "lib-test-stats", p.id));
    }
    act.append(actionButton("Share", "lib-share", p.id), actionButton(`Góp ý (${p.feedback})`, "lib-feedback", p.id),
      actionButton("Tải bản mới", "lib-upload"), actionButton("Xóa", "lib-delete", p.id, "btn-studio-secondary btn-danger-soft"));
    if (p.has_content && (p.ask_status === "none" || p.ask_status === "rejected")) act.append(actionButton("Xin bật ô Hỏi", "lib-ask", p.id));
    row.append(info, act);
    mine.append(row);
  });
  $("libMineEmpty").hidden = d.mine.length > 0;
  const shared = $("libShared");
  shared.textContent = "";
  d.shared.forEach(p => {
    const row = el("article", "stream-row");
    const info = el("div", "lib-info");
    const descParts = [`Tác giả: ${p.author}`];
    if (p.lessons && p.lessons.length) descParts.push(`${p.lessons.length} bài`);
    if (p.tests && p.tests.length) descParts.push(`${p.tests.length} đề`);
    info.append(el("h3", "stream-title", p.title), el("p", "stream-status", descParts.join(", ")));
    const act = el("div", "stream-actions");
    if (p.first_lesson) {
      const learn = actionButton("Học", "start", null, "btn-studio-primary");
      learn.dataset.lesson = p.first_lesson;
      act.append(learn);
    }
    if (p.tests && p.tests.length > 0) {
      const doTests = actionButton("Làm đề", "lib-tests", p.id, p.first_lesson ? "btn-studio-secondary" : "btn-studio-primary");
      act.append(doTests);
    }
    act.append(actionButton("Bỏ khỏi thư viện", "lib-leave", p.id));
    row.append(info, act);
    shared.append(row);
  });
  $("libSharedEmpty").hidden = d.shared.length > 0;
}

async function deletePackage(id) {
  const p = state.library.mine.find(x => x.id === id);
  if (!p || !confirm(`Xóa "${p.title}"? Người học mất quyền ngay và tiến độ của mọi người với bài này bị xóa.`)) return;
  await api(`/api/packages/${id}`, { method: "DELETE" });
  await refresh();
  await loadLibrary();
}

// ---------- Upload ----------
const MAX_TESTS_TOTAL = 16 * 1024 * 1024;

function uploadStep(step) {
  ["upPick", "upBusy", "upError", "upConfirm"].forEach(id => { $(id).hidden = id !== step; });
}
function openUpload() {
  $("upFile").value = "";
  if ($("upJsonText")) $("upJsonText").value = "";
  $("upPickError").hidden = true;
  const copied = $("upPromptCopied");
  if (copied) copied.hidden = true;
  uploadStep("upPick");
  $("uploadDialog").showModal();
}
function showUploadProblems(problems) {
  const list = $("upProblems");
  list.textContent = "";
  problems.forEach(p => {
    const li = el("li");
    if (p.path) li.append(el("strong", "", p.path), document.createTextNode(": "));
    li.append(document.createTextNode(p.message));
    list.append(li);
  });
  uploadStep("upError");
}
function sendFile(file, contentType, name) {
  if (!file) return;
  const isJson = contentType === "application/json" || file.type === "application/json" || (file.name && file.name.toLowerCase().endsWith(".json"));
  const type = isJson ? "application/json" : "application/zip";
  const limit = isJson ? MAX_TESTS_TOTAL : MAX_ZIP;
  if (file.size > limit) {
    $("upPickError").textContent = isJson ? "File JSON quá lớn, tối đa 16 MB." : "File zip quá lớn, tối đa 90 MB.";
    $("upPickError").hidden = false;
    return;
  }
  uploadStep("upBusy");
  $("upBusyName").textContent = name || file.name || (isJson ? "tests.json" : "package.zip");
  $("upBusyText").textContent = "Đang tải lên";
  $("upPercent").textContent = "0%";
  $("upMeter").style.width = "0%";
  const xhr = new XMLHttpRequest();
  upload.xhr = xhr;
  xhr.open("POST", "/api/uploads");
  xhr.setRequestHeader("Content-Type", type);
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const percent = Math.round(e.loaded / e.total * 100);
    $("upPercent").textContent = percent + "%";
    $("upMeter").style.width = percent + "%";
    if (percent === 100) $("upBusyText").textContent = "Đang kiểm tra";
  };
  xhr.onload = () => {
    upload.xhr = null;
    let d = {};
    try { d = JSON.parse(xhr.responseText); } catch (e) { /* no JSON from the proxy */ }
    if (xhr.status === 200) return showConfirm(d);
    if (d.problems) return showUploadProblems(d.problems);
    showUploadProblems([{ path: "", message: d.error || "Tải lên chưa được. Thử lại sau." }]);
  };
  xhr.onerror = () => {
    upload.xhr = null;
    showUploadProblems([{ path: "", message: "Mất kết nối giữa chừng. Bài đang chạy không bị ảnh hưởng, hãy thử lại." }]);
  };
  xhr.send(file);
}
function showConfirm(d) {
  upload.id = d.upload_id;
  upload.removed = d.removed || [];
  $("upTitle").textContent = d.title || "";
  const nLessons = (d.lessons && d.lessons.length) || 0;
  const nTests = (d.tests && d.tests.length) || 0;
  $("upMeta").textContent = `${d.is_update ? "Bản mới của bài đã có" : "Bài mới"}, ${nLessons} bài, ${nTests} đề, ${size(d.size)}`;
  const fill = (id, items) => {
    const box = $(id);
    box.textContent = "";
    (items || []).forEach(t => box.append(el("li", "", t)));
  };
  const allItems = [];
  (d.lessons || []).forEach(l => allItems.push(d.tests && d.tests.length ? `Bài: ${l}` : l));
  (d.tests || []).forEach(t => allItems.push(d.lessons && d.lessons.length ? `Đề: ${t}` : t));
  fill("upLessons", allItems);
  fill("upRemoved", d.removed || []);
  $("upRemovedBox").hidden = !d.removed || d.removed.length === 0;
  fill("upWarnings", (d.warnings || []).map(w => w.message || w));
  $("upWarningsBox").hidden = !d.warnings || d.warnings.length === 0;
  $("upAttest").checked = false;
  $("upCommit").disabled = true;
  $("upConfirmError").hidden = true;
  uploadStep("upConfirm");
}

async function handleFileSelect(files) {
  if (!files || !files.length) return;
  $("upPickError").hidden = true;
  if (files.length === 1 && files[0].name.toLowerCase().endsWith(".zip")) {
    return sendFile(files[0]);
  }
  try {
    const parsedList = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (!f.name.toLowerCase().endsWith(".json") && f.type !== "application/json") {
        throw new Error("Chỉ chọn các file .json hoặc một file .zip.");
      }
      const text = await f.text();
      parsedList.push(parseTestJson(text));
    }
    const merged = mergeTestFiles(parsedList);
    const blob = new Blob([JSON.stringify(merged)], { type: "application/json" });
    sendFile(blob, "application/json", files.length === 1 ? files[0].name : "tests-merged.json");
  } catch (err) {
    $("upPickError").textContent = err.message || "Không đọc được file JSON.";
    $("upPickError").hidden = false;
  }
}

async function handlePasteSend() {
  const text = $("upJsonText").value;
  if (!text || !text.trim()) {
    $("upPickError").textContent = "Hãy dán nội dung JSON trước.";
    $("upPickError").hidden = false;
    return;
  }
  $("upPickError").hidden = true;
  try {
    const parsed = parseTestJson(text);
    const blob = new Blob([JSON.stringify(parsed)], { type: "application/json" });
    sendFile(blob, "application/json", "pasted.json");
  } catch (err) {
    $("upPickError").textContent = err.message || "Không đọc được JSON.";
    $("upPickError").hidden = false;
  }
}
async function commitUpload() {
  $("upCommit").disabled = true;
  try {
    await api(`/api/uploads/${upload.id}/commit`, send("POST", { attest: $("upAttest").checked, confirm_removed: upload.removed }));
    upload.id = null;
    $("uploadDialog").close();
    await refresh();
    await loadLibrary();
  } catch (e) {
    $("upConfirmError").textContent = e.message;
    $("upConfirmError").hidden = false;
    $("upCommit").disabled = !$("upAttest").checked;
  }
}
function closeUpload() {
  if (upload.xhr) upload.xhr.abort();
  upload.xhr = null;
  if (upload.id) fetch(`/api/uploads/${upload.id}`, { method: "DELETE" }).catch(() => {});
  upload.id = null;
  $("uploadDialog").close();
}

// ---------- Share ----------
async function openShare(id) {
  sharing = id;
  const p = state.library.mine.find(x => x.id === id);
  $("shareTitle").textContent = p.title;
  $("shareEmail").value = "";
  $("shareError").hidden = true;
  $("shareCopied").textContent = "";
  $("shareDialog").showModal();
  await Promise.all([renderPeople(), renderLink()]);
}
async function renderPeople() {
  const d = await api(`/api/packages/${sharing}/people`);
  const box = $("sharePeople");
  box.textContent = "";
  d.people.forEach(person => {
    const row = el("div", "stream-row share-person");
    row.append(el("span", "share-email", person.email));
    const b = actionButton("Bỏ", "share-remove");
    b.dataset.email = person.email;
    row.append(b);
    box.append(row);
  });
  $("sharePeopleLabel").textContent = `Người đang được share (${d.people.length})`;
}
async function renderLink() {
  const d = await api(`/api/packages/${sharing}/link`);
  showLink(d.url);
}
function showLink(url) {
  $("shareLink").value = url ? location.origin + url : "";
  $("shareLinkOn").hidden = !url;
  $("shareLinkOff").hidden = !!url;
}
async function addPerson(e) {
  e.preventDefault();
  $("shareError").hidden = true;
  try {
    await api(`/api/packages/${sharing}/share`, send("POST", { email: $("shareEmail").value }));
    $("shareEmail").value = "";
    await renderPeople();
  } catch (err) {
    $("shareError").textContent = err.message;
    $("shareError").hidden = false;
  }
}
async function removePerson(button) {
  await api(`/api/packages/${sharing}/unshare`, send("POST", { email: button.dataset.email }));
  await renderPeople();
}
async function newLink() {
  if ($("shareLink").value && !confirm("Link cũ sẽ hết tác dụng. Tạo link mới?")) return;
  showLink((await api(`/api/packages/${sharing}/link`, send("POST"))).url);
  $("shareCopied").textContent = "";
}
async function linkOff() {
  await api(`/api/packages/${sharing}/link`, { method: "DELETE" });
  showLink(null);
  $("shareCopied").textContent = "";
}
async function copyLink() {
  try {
    await navigator.clipboard.writeText($("shareLink").value);
    $("shareCopied").textContent = "Đã copy link.";
  } catch (e) {
    $("shareLink").select();
    $("shareCopied").textContent = "Không copy tự động được. Hãy tự chép link đang chọn.";
  }
}
async function closeShare() {
  $("shareDialog").close();
  await loadLibrary();
}

// ---------- Feedback the author received ----------
const KIND_LABEL = { comment: "Góp ý", wrong: "Báo sai", abuse: "Báo vi phạm" };
async function openFeedbackList(id) {
  const p = state.library.mine.find(x => x.id === id);
  $("fbListTitle").textContent = p.title;
  const box = $("fbList");
  box.textContent = "Đang tải...";
  $("feedbackListDialog").showModal();
  const d = await api(`/api/packages/${id}/feedback`);
  box.textContent = d.feedback.length ? "" : "Chưa có góp ý nào.";
  d.feedback.forEach(f => {
    const card = el("article", "fb-card");
    const pills = el("div", "meta-pills");
    pills.append(el("span", "meta-pill" + (f.kind === "comment" ? "" : " is-warn"), KIND_LABEL[f.kind] || f.kind));
    if (f.lesson_title) pills.append(el("span", "meta-pill", f.lesson_title));
    if (f.target_text) pills.append(el("span", "meta-pill", f.target_text));
    else if (f.target_id) pills.append(el("span", "meta-pill", `${f.target_id} (đã xóa khỏi bài)`));
    const when = new Date(f.created_at * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" });
    card.append(pills, el("p", "fb-body", f.body), el("p", "dock-note", `${f.author || "Tài khoản đã xóa"}, ${when}`));
    box.append(card);
  });
}

// ---------- Practice test stats the author sees ----------
async function openTestStats(id) {
  const p = state.library.mine.find(x => x.id === id);
  const dia = $("testStatsDialog");
  const title = $("testStatsTitle");
  const box = $("testStatsList");
  if (!dia || !box) return;
  title.textContent = p ? p.title : "Thống kê";
  box.textContent = "Đang tải...";
  dia.showModal();

  try {
    const d = await api(`/api/packages/${encodeURIComponent(id)}/test-stats`);
    box.textContent = (d.tests && d.tests.length) ? "" : "Chưa có dữ liệu thống kê.";
    (d.tests || []).forEach(t => {
      const sec = el("article", "test-stat-group fb-card");
      sec.append(el("h3", "stream-title", t.title));
      if (t.items && t.items.length > 0) {
        t.items.forEach(it => {
          const itemCard = el("div", "test-stat-item");
          const pills = el("div", "meta-pills");
          pills.append(el("span", "meta-pill", `${it.people} người làm`));
          pills.append(el("span", "meta-pill is-warn", `Tỉ lệ sai: ${it.wrong_percent}%`));
          if (it.top_wrong) {
            pills.append(el("span", "meta-pill", `Sai nhiều nhất: ${it.top_wrong.text}`));
          }
          itemCard.append(pills);
          const qBox = el("div", "test-desc-box");
          qBox.innerHTML = renderTestText(it.question);
          itemCard.append(qBox);
          sec.append(itemCard);
        });
      }
      if (t.hidden > 0) {
        sec.append(el("p", "dock-note", `Còn ${t.hidden} câu chưa đủ 3 người.`));
      } else if (!t.items || t.items.length === 0) {
        sec.append(el("p", "dock-note", "Chưa có câu nào có đủ 3 người làm."));
      }
      box.append(sec);
    });
  } catch (err) {
    box.textContent = err.message || "Không tải được thống kê.";
  }
}

Object.assign(ACTIONS, {
  "lib-upload": openUpload,
  "lib-share": b => openShare(b.dataset.id),
  "lib-feedback": b => openFeedbackList(b.dataset.id),
  "lib-test-stats": b => openTestStats(b.dataset.id),
  "test-stats-close": () => $("testStatsDialog").close(),
  "lib-delete": b => deletePackage(b.dataset.id),
  "lib-ask": async b => {
    if (!confirm("Xin bật ô Hỏi? Admin sẽ đọc nội dung bài. Khi được duyệt, nội dung bài và câu hỏi của người học được gửi tới nhà cung cấp AI.")) return;
    await api(`/api/packages/${b.dataset.id}/ask-request`, send("POST", {}));
    await refresh();
    go("library", true);
  },
  "lib-leave": async b => {
    if (!confirm("Bỏ bài này khỏi thư viện? Muốn học lại, bạn cần nhờ tác giả share lại.")) return;
    await api(`/api/packages/${b.dataset.id}/leave`, send("POST", {}));
    await refresh();
    go("library", true);
  },
  "lib-tests": b => { location.hash = "#tests=" + encodeURIComponent(b.dataset.id); },
  "up-close": closeUpload,
  "up-commit": commitUpload,
  "up-again": openUpload,
  "up-prompt": () => copyTestPrompt(),  // practice.js loads after this file
  "up-paste-send": handlePasteSend,
  "share-close": closeShare,
  "share-remove": removePerson,
  "share-copy": copyLink,
  "share-new": newLink,
  "share-off": linkOff,
  "fb-list-close": () => $("feedbackListDialog").close(),
});
$("upFile").addEventListener("change", e => handleFileSelect(e.target.files));
$("upAttest").addEventListener("change", e => { $("upCommit").disabled = !e.target.checked; });
$("shareForm").addEventListener("submit", addPerson);
$("uploadDialog").addEventListener("cancel", e => { e.preventDefault(); closeUpload(); });
