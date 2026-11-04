"use strict";
// Library, upload, share and the author's feedback list. Text from packages only ever goes in with textContent.
const MAX_ZIP = 300 * 1024 * 1024;
// Up to about 5 minutes of waiting per part: office and home networks drop for longer than a few seconds.
const PART_TRIES = 12;
let upload = { xhr: null, controller: null, session: null, id: null, removed: [] };
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
  const usedPercent = Math.min(100, Math.round(d.used / d.quota * 100));
  $("libMeter").style.width = usedPercent + "%";
  $("libMeter").parentElement.setAttribute("aria-valuenow", String(usedPercent));
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
      `${p.people} người được chia sẻ`,
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
      const doTests = actionButton("Xem đề", "lib-tests", p.id, p.first_lesson ? "btn-studio-secondary" : "btn-studio-primary");
      act.append(doTests);
      act.append(actionButton("Thống kê đề", "lib-test-stats", p.id));
    }
    act.append(actionButton("Chia sẻ", "lib-share", p.id));
    if (p.feedback > 0) act.append(actionButton(`Xem góp ý (${p.feedback})`, "lib-feedback", p.id));
    act.append(actionButton("Tải bản mới", "lib-upload"), actionButton("Xóa", "lib-delete", p.id, "btn-studio-secondary btn-danger-soft"));
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
      const doTests = actionButton("Xem đề", "lib-tests", p.id, p.first_lesson ? "btn-studio-secondary" : "btn-studio-primary");
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
  if (upload.xhr) upload.xhr.abort();
  upload.xhr = null;
  if (upload.controller) upload.controller.abort();
  upload.controller = null;
  upload.session = null;
  upload.id = null;
  $("upFile").value = "";
  if ($("upJsonText")) $("upJsonText").value = "";
  $("upPickError").hidden = true;
  const copied = $("upPromptCopied");
  if (copied) copied.hidden = true;
  if ($("upReuseStatus")) {
    $("upReuseStatus").hidden = true;
    $("upReuseStatus").textContent = "";
  }
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
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const timer = setTimeout(resolve, ms);
    if (signal) {
      signal.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }
  });
}
// fetch has no upload progress, and a 2 MB part over a slow tunnel takes a minute: XHR shows the bytes as they go.
async function putPart(url, chunk, signal, onProgress) {
  // WebKit sent the start of the file for a sliced Blob body (seen with multi-part zips): send the bytes, not the slice.
  const bytes = await chunk.arrayBuffer();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = e => onProgress(e.loaded);
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, json: async () => data || {} });
    };
    xhr.onerror = () => reject(new TypeError("network"));
    xhr.ontimeout = () => reject(new TypeError("timeout"));
    const stop = () => { xhr.abort(); reject(new DOMException("Aborted", "AbortError")); };
    if (signal.aborted) return stop();
    signal.addEventListener("abort", stop, { once: true });
    xhr.send(bytes);
  });
}
async function sendPartsFile(file, name) {
  uploadStep("upBusy");
  $("upBusyName").textContent = name || file.name || "package.zip";
  $("upBusyText").textContent = "Đang tải lên";
  $("upPercent").textContent = "0%";
  $("upMeter").style.width = "0%";
  $("upMeter").parentElement.setAttribute("aria-valuenow", "0");
  if ($("upReuseStatus")) {
    $("upReuseStatus").hidden = true;
    $("upReuseStatus").textContent = "";
  }

  const controller = new AbortController();
  upload.controller = controller;
  upload.session = null;

  let cdOffset = null, cdSize = null;
  try {
    const tailSize = Math.min(file.size, 65536 + 22);
    const tailSlice = file.slice(file.size - tailSize, file.size);
    const tailBuffer = await tailSlice.arrayBuffer();
    const view = new DataView(tailBuffer);
    let eocdOffset = -1;
    for (let i = tailSize - 22; i >= 0; i--) {
      if (view.getUint32(i, true) === 0x06054b50) {
        const commentLen = view.getUint16(i + 20, true);
        if (i + 22 + commentLen === tailSize) {
          eocdOffset = i;
          break;
        }
      }
    }
    if (eocdOffset === -1) {
      for (let i = tailSize - 22; i >= 0; i--) {
        if (view.getUint32(i, true) === 0x06054b50) {
          eocdOffset = i;
          break;
        }
      }
    }
    if (eocdOffset !== -1) {
      const s = view.getUint32(eocdOffset + 12, true);
      const o = view.getUint32(eocdOffset + 16, true);
      if (s !== 0xFFFFFFFF && o !== 0xFFFFFFFF && o >= 0 && s > 0 && o + s <= file.size) {
        cdOffset = o;
        cdSize = s;
      }
    }
  } catch (_) {
    cdOffset = null;
    cdSize = null;
  }

  const postBody = { size: file.size };
  if (cdOffset !== null && cdSize !== null) {
    postBody.cd_offset = cdOffset;
    postBody.cd_size = cdSize;
  }

  let sessionData;
  try {
    const res = await fetch("/api/uploads/parts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(postBody),
      signal: controller.signal,
    });
    let d = {};
    try { d = await res.json(); } catch (_) {}
    if (!res.ok) {
      upload.controller = null;
      if (d.problems) return showUploadProblems(d.problems);
      return showUploadProblems([{ path: "", message: d.error || "Tải lên chưa được. Thử lại sau." }]);
    }
    sessionData = d;
  } catch (err) {
    if (controller.signal.aborted) return;
    upload.controller = null;
    return showUploadProblems([{ path: "", message: "Mất kết nối giữa chừng. Bài đang chạy không bị ảnh hưởng, hãy thử lại." }]);
  }

  const { session, part_size, parts } = sessionData;
  upload.session = session;

  function getPartSize(i) {
    return (i === parts - 1) ? (file.size - i * part_size) : part_size;
  }

  const sentParts = new Set();
  let acknowledgedBytes = 0;
  let totalProgressBytes = file.size;
  let fatalError = null;
  const retryingParts = new Set();

  const inFlight = new Map();
  function updateProgress() {
    let moving = 0;
    inFlight.forEach(n => { moving += n; });
    const percent = totalProgressBytes ? Math.min(100, Math.floor((acknowledgedBytes + moving) / totalProgressBytes * 100)) : 0;
    $("upPercent").textContent = percent + "%";
    $("upMeter").style.width = percent + "%";
    $("upMeter").parentElement.setAttribute("aria-valuenow", String(percent));
  }

  function updateBusyText() {
    if (retryingParts.size > 0) {
      const n = retryingParts.values().next().value;
      $("upBusyText").textContent = `Đang gửi lại phần ${n}`;
    } else {
      $("upBusyText").textContent = acknowledgedBytes >= totalProgressBytes ? "Đang kiểm tra" : "Đang tải lên";
    }
  }

  async function uploadPart(i) {
    if (sentParts.has(i)) return;
    let attempt = 0;
    while (true) {
      if (controller.signal.aborted || fatalError) throw new DOMException("Aborted", "AbortError");
      const startByte = i * part_size;
      const endByte = Math.min(file.size, startByte + part_size);
      const chunk = file.slice(startByte, endByte);
      let res;
      try {
        res = await putPart(`/api/uploads/parts/${session}/${i}`, chunk, controller.signal, sent => {
          inFlight.set(i, sent);
          updateProgress();
        });
      } catch (netErr) {
        inFlight.delete(i);
        updateProgress();
        if (controller.signal.aborted || fatalError) throw netErr;
        attempt++;
        if (attempt > PART_TRIES) {
          throw new Error("Mất kết nối giữa chừng. Bài đang chạy không bị ảnh hưởng, hãy thử lại.");
        }
        retryingParts.add(i + 1);
        updateBusyText();
        await sleep(Math.min(2000 * attempt, 30000), controller.signal);
        retryingParts.delete(i + 1);
        updateBusyText();
        continue;
      }

      inFlight.delete(i);
      if (res.ok) {
        sentParts.add(i);
        acknowledgedBytes += chunk.size;
        updateProgress();
        updateBusyText();
        break;
      }

      let body = null;
      if (res.status === 400) {
        try { body = await res.json(); } catch (_) {}
      }
      // "interrupted" is the server timing out a slow part: the same cut the retries are for.
      if (res.status === 408 || res.status === 429 || res.status >= 500 || (body && body.code === "interrupted")) {
        attempt++;
        if (attempt > PART_TRIES) {
          let d = {};
          try { d = await res.json(); } catch (_) {}
          throw new Error(d.error || `Tải lên phần ${i + 1} không thành công sau nhiều lần thử.`);
        }
        retryingParts.add(i + 1);
        updateBusyText();
        await sleep(Math.min(2000 * attempt, 30000), controller.signal);
        retryingParts.delete(i + 1);
        updateBusyText();
        continue;
      } else {
        let d = {};
        try { d = await res.json(); } catch (_) {}
        const err = new Error(d.error || "Tải lên chưa được. Thử lại sau.");
        if (d.problems) err.problems = d.problems;
        throw err;
      }
    }
  }

  async function uploadPartsList(list) {
    let nextIndex = 0;
    async function worker() {
      while (nextIndex < list.length) {
        if (controller.signal.aborted || fatalError) break;
        const idx = list[nextIndex++];
        try {
          await uploadPart(idx);
        } catch (err) {
          if (!fatalError && err.name !== "AbortError") {
            fatalError = err;
            controller.abort();
          }
          break;
        }
      }
    }
    const workerCount = Math.min(3, list.length);
    const workers = [];
    for (let w = 0; w < workerCount; w++) {
      workers.push(worker());
    }
    await Promise.all(workers);
  }

  if (cdOffset !== null) {
    const cdStartPart = Math.floor(cdOffset / part_size);
    const cdParts = [];
    for (let i = cdStartPart; i < parts; i++) cdParts.push(i);
    totalProgressBytes = file.size;
    await uploadPartsList(cdParts);

    if (fatalError) {
      upload.controller = null;
      upload.session = null;
      if (fatalError.problems) return showUploadProblems(fatalError.problems);
      return showUploadProblems([{ path: "", message: fatalError.message || "Tải lên chưa được. Thử lại sau." }]);
    }
    if (controller.signal.aborted) return;

    $("upBusyText").textContent = "Đang kiểm tra";
    let planData = {};
    try {
      const planRes = await fetch(`/api/uploads/parts/${session}/plan`, {
        method: "POST",
        signal: controller.signal,
      });
      try { planData = await planRes.json(); } catch (_) {}
      if (!planRes.ok) {
        upload.controller = null;
        upload.session = null;
        if (planData.problems) return showUploadProblems(planData.problems);
        return showUploadProblems([{ path: "", message: planData.error || "Tải lên chưa được. Thử lại sau." }]);
      }
    } catch (planErr) {
      if (controller.signal.aborted) return;
      upload.controller = null;
      upload.session = null;
      return showUploadProblems([{ path: "", message: "Mất kết nối giữa chừng. Bài đang chạy không bị ảnh hưởng, hãy thử lại." }]);
    }

    const { needed, reused, reused_bytes } = planData;
    const neededPartsBytes = needed.reduce((sum, i) => sum + getPartSize(i), 0);
    totalProgressBytes = neededPartsBytes;
    acknowledgedBytes = needed.filter(i => sentParts.has(i)).reduce((sum, i) => sum + getPartSize(i), 0);
    updateProgress();

    if (reused > 0) {
      const msg = `Dùng lại ${reused} file đã có (${size(reused_bytes)}), chỉ gửi ${size(neededPartsBytes)}`;
      if ($("upReuseStatus")) {
        $("upReuseStatus").textContent = msg;
        $("upReuseStatus").hidden = false;
      }
    }

    const remainingParts = needed.filter(i => !sentParts.has(i));
    if (remainingParts.length > 0) {
      $("upBusyText").textContent = "Đang tải lên";
      await uploadPartsList(remainingParts);
    }
  } else {
    const allParts = [];
    for (let i = 0; i < parts; i++) allParts.push(i);
    totalProgressBytes = file.size;
    await uploadPartsList(allParts);
  }

  if (fatalError) {
    upload.controller = null;
    upload.session = null;
    if (fatalError.problems) return showUploadProblems(fatalError.problems);
    return showUploadProblems([{ path: "", message: fatalError.message || "Tải lên chưa được. Thử lại sau." }]);
  }

  if (controller.signal.aborted) {
    return;
  }

  $("upBusyText").textContent = "Đang kiểm tra";
  try {
    const finRes = await fetch(`/api/uploads/parts/${session}/finish`, {
      method: "POST",
      signal: controller.signal,
    });
    upload.controller = null;
    upload.session = null;
    let d = {};
    try { d = await finRes.json(); } catch (_) {}
    if (finRes.status === 200) return showConfirm(d);
    if (d.problems) return showUploadProblems(d.problems);
    showUploadProblems([{ path: "", message: d.error || "Tải lên chưa được. Thử lại sau." }]);
  } catch (finErr) {
    if (controller.signal.aborted) return;
    upload.controller = null;
    upload.session = null;
    showUploadProblems([{ path: "", message: "Mất kết nối giữa chừng. Bài đang chạy không bị ảnh hưởng, hãy thử lại." }]);
  }
}
function sendFile(file, contentType, name) {
  if (!file) return;
  const isJson = contentType === "application/json" || file.type === "application/json" || (file.name && file.name.toLowerCase().endsWith(".json"));
  const type = isJson ? "application/json" : "application/zip";
  const limit = isJson ? MAX_TESTS_TOTAL : MAX_ZIP;
  if (file.size > limit) {
    $("upPickError").textContent = isJson ? "File JSON quá lớn, tối đa 16 MB." : "File zip quá lớn, tối đa 300 MB.";
    $("upPickError").hidden = false;
    return;
  }
  if (!isJson) {
    return sendPartsFile(file, name);
  }
  uploadStep("upBusy");
  $("upBusyName").textContent = name || file.name || (isJson ? "tests.json" : "package.zip");
  $("upBusyText").textContent = "Đang tải lên";
  $("upPercent").textContent = "0%";
  $("upMeter").style.width = "0%";
  $("upMeter").parentElement.setAttribute("aria-valuenow", "0");
  const xhr = new XMLHttpRequest();
  upload.xhr = xhr;
  xhr.open("POST", "/api/uploads");
  xhr.setRequestHeader("Content-Type", type);
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const percent = Math.round(e.loaded / e.total * 100);
    $("upPercent").textContent = percent + "%";
    $("upMeter").style.width = percent + "%";
    $("upMeter").parentElement.setAttribute("aria-valuenow", String(percent));
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
  if (upload.controller) upload.controller.abort();
  upload.controller = null;
  if (upload.session) fetch(`/api/uploads/parts/${upload.session}`, { method: "DELETE" }).catch(() => {});
  upload.session = null;
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
  $("sharePeopleLabel").textContent = `Người đang được chia sẻ (${d.people.length})`;
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
    if (!confirm("Bỏ bài này khỏi thư viện? Muốn học lại, bạn cần nhờ tác giả chia sẻ lại.")) return;
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
