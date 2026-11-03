"use strict";

let _promptCache = null;

async function testPrompt() {
  if (_promptCache === null) {
    const r = await fetch("/static/test-prompt.txt");
    _promptCache = r.ok ? await r.text() : "";
  }
  return _promptCache;
}

async function copyTestPrompt() {
  try {
    const text = await testPrompt();
    await navigator.clipboard.writeText(text);
    const st = $("upPromptCopied");
    if (st) {
      st.textContent = "Đã copy hướng dẫn vào clipboard.";
      st.hidden = false;
      setTimeout(() => { if (st) st.hidden = true; }, 3000);
    }
  } catch (e) {
    const err = $("upPickError");
    if (err) {
      err.textContent = "Không copy tự động được. Hãy mở /static/test-prompt.txt";
      err.hidden = false;
    }
  }
}

function renderTestText(text) {
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text), {
    ALLOWED_TAGS: ["p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a"],
    ALLOWED_ATTR: ["href"],
    ALLOWED_URI_REGEXP: /^https:/i,
  });
}

function parseTestJson(text) {
  if (typeof text !== "string") throw new Error("Nội dung không phải là chuỗi JSON.");
  let s = text.trim();
  if (s.charCodeAt(0) === 0xFEFF) {
    s = s.slice(1).trim();
  }
  try {
    return JSON.parse(s);
  } catch (_) {}

  const fenceMatch = s.match(/^```(?:[a-zA-Z0-9_-]+)?\s*\n?([\s\S]*?)\n?```$/);
  if (fenceMatch) {
    try {
      return JSON.parse(fenceMatch[1].trim());
    } catch (_) {}
  }

  const firstBrace = s.indexOf("{");
  const lastBrace = s.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    try {
      return JSON.parse(s.slice(firstBrace, lastBrace + 1).trim());
    } catch (_) {}
  }

  throw new Error("Không đọc được JSON. Hãy kiểm tra định dạng hoặc dán lại.");
}

function mergeTestFiles(list) {
  if (!Array.isArray(list) || list.length === 0) {
    throw new Error("Danh sách file trống.");
  }
  const slug = list[0].slug;
  if (!slug) {
    throw new Error("Dữ liệu đề thiếu trường slug.");
  }
  for (let i = 1; i < list.length; i++) {
    if (list[i].slug !== slug) {
      throw new Error(`Các file có slug khác nhau ("${slug}" và "${list[i].slug}"). Hãy chọn các file cùng slug.`);
    }
  }
  const merged = {
    slug: slug,
    title: list[0].title || "Bộ đề",
    topic: list[0].topic || "",
    description: list[0].description || "",
    tests: []
  };
  for (const item of list) {
    if (Array.isArray(item.tests)) {
      merged.tests.push(...item.tests);
    }
  }
  return merged;
}

function testRoute() {
  const h = location.hash;
  let m;
  if (h === "#tests" || (m = h.match(/^#tests=(.+)$/))) {
    showTestsScreen(m ? decodeURIComponent(m[1]) : null);
    return true;
  }
  if ((m = h.match(/^#test=(.+)$/))) {
    showTestDetail(decodeURIComponent(m[1]));
    return true;
  }
  if ((m = h.match(/^#attempt=(.+)$/))) {
    showTestRun(decodeURIComponent(m[1]));
    return true;
  }
  if ((m = h.match(/^#result=(.+)$/))) {
    showTestResult(decodeURIComponent(m[1]));
    return true;
  }
  return false;
}

function shouldShowItemsPill(title, items) {
  if (!items) return false;
  const re = new RegExp(`(?:^|\\D)${items}\\s*(?:câu|questions)(?:\\b|\\W|$)`, "i");
  return !re.test(title || "");
}

async function showTestsScreen(pkgFilter) {
  const hash = pkgFilter ? "#tests=" + encodeURIComponent(pkgFilter) : "#tests";
  go("tests", true, hash);
  const sub = $("testsSubtitle");
  const list = $("testsList");
  const empty = $("testsEmpty");
  if (!list) return;

  list.textContent = "Đang tải danh sách đề...";
  if (empty) empty.hidden = true;

  try {
    const d = await api("/api/tests");
    state.tests = d.tests || [];
    let tests = state.tests;
    if (pkgFilter) {
      tests = tests.filter(t => t.package_id === pkgFilter);
      if (tests.length > 0) {
        sub.textContent = tests[0].package_title ? `Package: ${tests[0].package_title}` : "";
      } else {
        sub.textContent = "";
      }
    } else {
      sub.textContent = "";
    }
    list.textContent = "";
    if (tests.length === 0) {
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    let last = null;
    tests.forEach(t => {
      const group = pkgFilter ? null : testGroupHeading(t, last);
      if (group) list.append(group);
      last = t.package_id;
      const row = el("article", "stream-row");
      const info = el("div", "lib-info");
      info.append(el("h3", "stream-title", t.title));
      const pills = el("div", "meta-pills");
      const pillTexts = [];
      if (shouldShowItemsPill(t.title, t.items)) {
        pillTexts.push(`${t.items} câu`);
      }
      if (t.minutes) pillTexts.push(`${t.minutes} phút`);
      else pillTexts.push("Không giới hạn giờ");
      pillTexts.push(`Điểm đạt: ${t.pass_percent}%`);
      if (t.best_percent !== null && t.best_percent !== undefined) {
        pillTexts.push(`Điểm cao nhất: ${t.best_percent}%`);
      }
      if (t.pool) pillTexts.push(`Chờ ôn: ${t.pool} câu`);
      pillTexts.forEach(txt => pills.append(el("span", "meta-pill", txt)));
      info.append(pills);
      const act = el("div", "stream-actions");
      const btn = actionButton("Làm đề", "test-open", t.key, "btn-studio-primary");
      act.append(btn);
      row.append(info, act);
      list.append(row);
    });
  } catch (err) {
    if (err.message !== "login" && err.message !== "password") {
      list.textContent = err.message || "Không tải được danh sách đề.";
    }
  }
}

async function showTestDetail(key) {
  go("test-detail", true, "#test=" + encodeURIComponent(key));
  const title = $("testDetailTitle");
  const pill = $("testDetailPill");
  const pills = $("testDetailPills");
  const desc = $("testDetailDesc");
  const actions = $("testDetailActions");
  const alert = $("testDetailAlert");
  const historyList = $("testHistoryList");
  const historyEmpty = $("testHistoryEmpty");

  if (title) title.textContent = "Đang tải...";
  if (pills) pills.textContent = "";
  if (desc) desc.textContent = "";
  if (actions) actions.textContent = "";
  if (alert) alert.hidden = true;
  if (historyList) historyList.textContent = "Đang tải lịch sử...";
  if (historyEmpty) historyEmpty.hidden = true;

  try {
    const t = await api("/api/tests/" + encodeURIComponent(key));
    if (title) title.textContent = t.title;
    if (pill) pill.textContent = t.package_title || "Bộ đề";
    if (pills) {
      pills.textContent = "";
      const detailPills = [];
      if (shouldShowItemsPill(t.title, t.items)) {
        detailPills.push(`${t.items} câu`);
      }
      if (t.minutes) detailPills.push(`${t.minutes} phút`);
      else detailPills.push("Không giới hạn giờ");
      detailPills.push(`Điểm đạt: ${t.pass_percent}%`);
      if (t.best_percent !== null && t.best_percent !== undefined) {
        detailPills.push(`Điểm cao nhất: ${t.best_percent}%`);
      }
      if (t.pool) detailPills.push(`Chờ ôn: ${t.pool} câu`);
      detailPills.forEach(txt => pills.append(el("span", "meta-pill", txt)));
    }
    if (desc) {
      desc.innerHTML = renderTestText(t.description || "");
    }

    if (actions) {
      actions.textContent = "";

      // 1. Thi thử
      const examOpen = t.open && t.open.exam;
      if (examOpen) {
        const cont = el("button", "btn-studio-primary", "Tiếp tục Thi thử");
        cont.type = "button";
        cont.dataset.act = "attempt-open";
        cont.dataset.id = examOpen;
        const restart = el("button", "btn-studio-secondary", "Làm lại Thi thử");
        restart.type = "button";
        restart.dataset.act = "attempt-start";
        restart.dataset.key = t.key;
        restart.dataset.mode = "exam";
        restart.dataset.restart = "true";
        actions.append(cont, restart);
      } else {
        const start = el("button", "btn-studio-primary", "Thi thử");
        start.type = "button";
        start.dataset.act = "attempt-start";
        start.dataset.key = t.key;
        start.dataset.mode = "exam";
        actions.append(start);
      }

      // 2. Luyện tập
      const practiceOpen = t.open && t.open.practice;
      if (practiceOpen) {
        const cont = el("button", "btn-studio-primary", "Tiếp tục Luyện tập");
        cont.type = "button";
        cont.dataset.act = "attempt-open";
        cont.dataset.id = practiceOpen;
        const restart = el("button", "btn-studio-secondary", "Làm lại Luyện tập");
        restart.type = "button";
        restart.dataset.act = "attempt-start";
        restart.dataset.key = t.key;
        restart.dataset.mode = "practice";
        restart.dataset.restart = "true";
        actions.append(cont, restart);
      } else {
        const start = el("button", "btn-studio-secondary", "Luyện tập");
        start.type = "button";
        start.dataset.act = "attempt-start";
        start.dataset.key = t.key;
        start.dataset.mode = "practice";
        actions.append(start);
      }

      // 3. Ôn câu sai (ẩn khi pool == 0)
      if (t.pool && t.pool > 0) {
        const reviewOpen = t.open && t.open.review;
        if (reviewOpen) {
          const cont = el("button", "btn-studio-primary", `Tiếp tục Ôn (${t.pool} câu)`);
          cont.type = "button";
          cont.dataset.act = "attempt-open";
          cont.dataset.id = reviewOpen;
          const restart = el("button", "btn-studio-secondary", "Ôn lại từ đầu");
          restart.type = "button";
          restart.dataset.act = "attempt-start";
          restart.dataset.key = t.key;
          restart.dataset.mode = "review";
          restart.dataset.restart = "true";
          actions.append(cont, restart);
        } else {
          const start = el("button", "btn-studio-secondary", `Ôn câu sai (${t.pool} câu)`);
          start.type = "button";
          start.dataset.act = "attempt-start";
          start.dataset.key = t.key;
          start.dataset.mode = "review";
          actions.append(start);
        }
      }
    }

    if (historyList) {
      historyList.textContent = "";
      const hist = t.history || [];
      if (hist.length === 0) {
        if (historyEmpty) historyEmpty.hidden = false;
      } else {
        if (historyEmpty) historyEmpty.hidden = true;
        hist.forEach(h => {
          const row = el("article", "stream-row");
          const info = el("div", "lib-info");
          const modeName = h.mode === "exam" ? "Thi thử" : (h.mode === "practice" ? "Luyện tập" : "Ôn câu sai");
          const when = new Date(h.at * 1000).toLocaleString("vi-VN", {
            hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric"
          });
          info.append(el("h3", "stream-title", `${modeName} - ${h.percent}%`));
          const pills = el("div", "meta-pills");
          pills.append(el("span", "meta-pill" + (h.passed ? "" : " is-warn"), h.passed ? "Đậu" : "Chưa đậu"));
          pills.append(el("span", "meta-pill", when));
          info.append(pills);
          const act = el("div", "stream-actions");
          const btn = actionButton("Xem kết quả", "attempt-result", h.id, "btn-studio-secondary");
          act.append(btn);
          row.append(info, act);
          historyList.append(row);
        });
      }
    }
  } catch (err) {
    if (err.message !== "login" && err.message !== "password") {
      if (alert) {
        alert.textContent = err.message || "Không tải được thông tin bộ đề.";
        alert.hidden = false;
      }
    }
  }
}

let _currentAttempt = null;
let _currentAttemptId = null;
let _currentIndex = 0;
let _clockInterval = null;
let _saveQueue = {};
let _resultAttempt = null;
let _resultFilter = "all";

function leaveAttempt() {
  document.body.classList.remove("in-test");
  if (_clockInterval) {
    clearInterval(_clockInterval);
    _clockInterval = null;
  }
  for (const itemId in _saveQueue) {
    const q = _saveQueue[itemId];
    if (q && q.timer) {
      clearTimeout(q.timer);
      q.timer = null;
    }
  }
  _saveQueue = {};
  stopSpeech();
  _currentAttempt = null;
  _currentAttemptId = null;
}
window.leaveAttempt = leaveAttempt;

function applySavedFont() {
  let fontLevel = "2";
  try {
    fontLevel = localStorage.getItem("learn.test-font") || "2";
  } catch (_) {}
  const runScreen = $("screen-test-run");
  if (runScreen) runScreen.dataset.testFont = fontLevel;
}

function changeFont(delta) {
  const runScreen = $("screen-test-run");
  let cur = parseInt(runScreen?.dataset.testFont || "2", 10);
  cur = Math.max(1, Math.min(4, cur + delta));
  if (runScreen) runScreen.dataset.testFont = String(cur);
  try {
    localStorage.setItem("learn.test-font", String(cur));
  } catch (_) {}
}

// Speech follows the language of the question itself: tests in any language sit in a Vietnamese app.
const VI_MARKS = /[ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]/i;
const textLang = text => (VI_MARKS.test(text) ? "vi" : "en");
const LANG_NAME = { vi: "tiếng Việt", en: "tiếng Anh" };

function voiceFor(lang) {
  const voices = window.speechSynthesis.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith(lang));
  return voices.find(v => v.default) || voices.find(v => v.localService) || voices[0] || null;
}

function setupTts() {
  const btn = $("btnTestSpeech");
  const note = $("testSpeechNote");
  if (!btn || !note) return;
  if (!("speechSynthesis" in window)) {
    btn.hidden = true;
    note.textContent = "Trình duyệt không hỗ trợ giọng đọc.";
    note.hidden = false;
    return;
  }
  function showButton() {
    const any = window.speechSynthesis.getVoices().length > 0;
    btn.hidden = !any;
    note.textContent = any ? "" : "Thiết bị chưa có giọng đọc.";
    note.hidden = any;
  }
  showButton();
  if (window.speechSynthesis.onvoiceschanged !== undefined) window.speechSynthesis.onvoiceschanged = showButton;
}

function stopSpeech() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  const btn = $("btnTestSpeech");
  if (btn) btn.textContent = "Đọc";
}

function toggleSpeech() {
  if (!("speechSynthesis" in window)) return;
  if (window.speechSynthesis.speaking) {
    stopSpeech();
    return;
  }
  if (!_currentAttempt || !_currentAttempt.items || !_currentAttempt.items[_currentIndex]) return;
  const item = _currentAttempt.items[_currentIndex];

  const div = document.createElement("div");
  div.innerHTML = renderTestText(item.question);
  const qText = div.textContent || "";
  const lang = textLang(qText + " " + item.options.map(o => o.text).join(" "));
  const voice = voiceFor(lang);
  const note = $("testSpeechNote");
  if (!voice) {
    if (note) { note.textContent = "Thiết bị chưa có giọng đọc " + LANG_NAME[lang] + "."; note.hidden = false; }
    return;
  }
  if (note) note.hidden = true;

  const label = lang === "vi" ? "Lựa chọn" : "Option";
  let speechText = qText + ".\n";
  item.options.forEach((opt, idx) => {
    speechText += `${label} ${String.fromCharCode(65 + idx)}: ${opt.text}.\n`;
  });

  const u = new SpeechSynthesisUtterance(speechText);
  u.voice = voice;
  u.lang = voice.lang;
  u.onend = () => { stopSpeech(); };
  u.onerror = () => { stopSpeech(); };

  const btn = $("btnTestSpeech");
  if (btn) btn.textContent = "Dừng";
  window.speechSynthesis.speak(u);
}

function startClock() {
  if (_clockInterval) {
    clearInterval(_clockInterval);
    _clockInterval = null;
  }
  if (!_currentAttempt) return;

  const timerEl = $("testTimer");
  if (!timerEl) return;

  if (_currentAttempt.status === "paused") {
    if (_currentAttempt.remaining !== null && _currentAttempt.remaining !== undefined) {
      timerEl.textContent = fmt(_currentAttempt.remaining);
    } else {
      timerEl.textContent = fmt(_currentAttempt.elapsed || 0);
    }
    return;
  }

  const hasRemaining = _currentAttempt.remaining !== null && _currentAttempt.remaining !== undefined;
  const startPerf = performance.now();
  const initSec = hasRemaining ? _currentAttempt.remaining : (_currentAttempt.elapsed || 0);

  function tick() {
    const passed = Math.floor((performance.now() - startPerf) / 1000);
    if (hasRemaining) {
      const cur = Math.max(0, initSec - passed);
      timerEl.textContent = fmt(cur);
      if (cur <= 0) {
        clearInterval(_clockInterval);
        _clockInterval = null;
        confirmSubmit(true);
      }
    } else {
      const cur = initSec + passed;
      timerEl.textContent = fmt(cur);
    }
  }

  tick();
  _clockInterval = setInterval(tick, 500);
}

function updateSaveIndicator() {
  const el = $("testSave");
  if (!el) return;
  let hasSending = false;
  let hasFailed = false;
  for (const k in _saveQueue) {
    const q = _saveQueue[k];
    if (q) {
      if (q.status === "sending" || q.pending !== null) hasSending = true;
      if (q.status === "failed") hasFailed = true;
    }
  }
  if (hasSending) {
    el.textContent = "Đang lưu";
  } else if (hasFailed) {
    el.textContent = "Chưa lưu";
  } else {
    el.textContent = "Đã lưu";
  }
}

function queueSave(itemId, changes) {
  if (!_currentAttempt || !_currentAttemptId) return;
  const item = _currentAttempt.items.find(x => x.id === itemId);
  if (!item) return;

  if (changes.chosen !== undefined) item.chosen = changes.chosen;
  if (changes.flagged !== undefined) item.flagged = changes.flagged;

  renderGrid();

  if (!_saveQueue[itemId]) {
    _saveQueue[itemId] = { status: "idle", pending: null, timer: null };
  }
  const q = _saveQueue[itemId];
  if (q.status === "sending") {
    q.pending = Object.assign(q.pending || {}, changes);
    updateSaveIndicator();
    return;
  }
  if (q.timer) {
    // a failed save is waiting to retry: send it now with the newer changes on top, never the old one later
    clearTimeout(q.timer);
    q.timer = null;
    changes = Object.assign({}, q.failed, changes);
    q.failed = null;
  }
  q.status = "sending";
  updateSaveIndicator();
  sendSave(itemId, changes);
}

async function sendSave(itemId, payload) {
  const attId = _currentAttemptId;
  const q = _saveQueue[itemId];
  if (!attId || !q) return;

  try {
    const r = await fetch(`/api/attempts/${encodeURIComponent(attId)}/items/${encodeURIComponent(itemId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (r.status === 401) { location.href = "/login"; return; }
    if (r.ok) {
      q.status = "idle";
      if (q.pending) {
        const next = q.pending;
        q.pending = null;
        q.status = "sending";
        sendSave(itemId, next);
      } else {
        updateSaveIndicator();
      }
    } else if (r.status >= 400 && r.status < 500) {
      q.status = "idle";
      q.pending = null;
      updateSaveIndicator();
      reloadAttempt();
    } else {
      retrySave(itemId, attId, payload);
    }
  } catch (err) {
    retrySave(itemId, attId, payload);
  }
}

function retrySave(itemId, attId, payload) {
  const q = _saveQueue[itemId];
  q.status = "failed";
  q.failed = Object.assign({}, payload, q.pending);
  q.pending = null;
  updateSaveIndicator();
  if (q.timer) clearTimeout(q.timer);
  q.timer = setTimeout(() => {
    q.timer = null;
    if (_currentAttemptId !== attId) return;
    const next = q.failed;
    q.failed = null;
    q.status = "sending";
    sendSave(itemId, next);
  }, 3000);
}

async function reloadAttempt() {
  if (!_currentAttemptId) return;
  try {
    const att = await api(`/api/attempts/${encodeURIComponent(_currentAttemptId)}`);
    if (att.status === "submitted") {
      leaveAttempt();
      location.hash = "#result=" + encodeURIComponent(att.id);
      return;
    }
    _currentAttempt = att;
    renderRunScreen();
  } catch (_) {}
}

document.addEventListener("visibilitychange", async () => {
  if (document.hidden) return;
  if (!_currentAttemptId || location.hash.indexOf("#attempt=") === -1) return;

  try {
    const att = await api(`/api/attempts/${encodeURIComponent(_currentAttemptId)}`);
    if (att.status === "submitted") {
      leaveAttempt();
      location.hash = "#result=" + encodeURIComponent(_currentAttemptId);
      return;
    }

    if (att.status === "paused") {
      _currentAttempt = att;
      renderRunScreen();
      return;
    }

    if (_currentAttempt && Array.isArray(_currentAttempt.items)) {
      const serverItemsById = {};
      for (const it of att.items || []) {
        serverItemsById[it.id] = it;
      }
      for (let i = 0; i < _currentAttempt.items.length; i++) {
        const localItem = _currentAttempt.items[i];
        const q = _saveQueue[localItem.id];
        const hasUnsaved = q && (q.status === "sending" || q.status === "failed" || q.pending !== null);
        if (!hasUnsaved && serverItemsById[localItem.id]) {
          _currentAttempt.items[i] = serverItemsById[localItem.id];
        }
      }
      _currentAttempt.remaining = att.remaining;
      _currentAttempt.elapsed = att.elapsed;
      _currentAttempt.status = att.status;
      _currentAttempt.pause_count = att.pause_count;
    } else {
      _currentAttempt = att;
    }

    renderRunScreen();
  } catch (_) {}
});

function renderRunScreen() {
  if (!_currentAttempt) return;

  const isPaused = _currentAttempt.status === "paused";
  const pausedPane = $("testPausedPane");
  const qBox = $("testQuestionBox");
  const navActions = $("testNavActions");
  const modePill = $("testRunModePill");
  const btnPause = $("btnTestPause");

  if (modePill) {
    modePill.textContent = _currentAttempt.mode === "exam" ? "Thi thử" :
      (_currentAttempt.mode === "practice" ? "Luyện tập" : "Ôn câu sai");
  }

  if (btnPause) {
    btnPause.textContent = isPaused ? "Tiếp tục" : "Tạm dừng";
  }

  if (pausedPane) pausedPane.hidden = !isPaused;
  if (qBox) qBox.hidden = isPaused;
  if (navActions) navActions.hidden = isPaused;

  if (isPaused) {
    if (qBox) qBox.textContent = "";
    return;
  }

  renderCurrentQuestion();
  renderGrid();
  updateSaveIndicator();
}

function renderCurrentQuestion() {
  const box = $("testQuestionBox");
  if (!box || !_currentAttempt || !_currentAttempt.items || _currentAttempt.items.length === 0) return;

  const item = _currentAttempt.items[_currentIndex];
  if (!item) return;

  box.textContent = "";

  const meta = el("div", "test-q-meta");
  meta.append(el("span", "meta-pill", item.domain || "Khác"));
  const typeText = item.type === "multi" ? `Chọn ${item.required} đáp án` : "Chọn 1 đáp án";
  meta.append(el("span", "meta-pill" + (item.type === "multi" ? " is-warn" : ""), typeText));
  if (item.flagged) {
    meta.append(el("span", "meta-pill is-warn", "Đã gắn cờ"));
  }
  box.append(meta);

  const qDiv = el("div", "test-q-text test-desc-box");
  qDiv.innerHTML = renderTestText(item.question);
  attachSafeLinks(qDiv);
  box.append(qDiv);

  const optsList = el("div", "test-options-list");
  optsList.setAttribute("role", "group");
  optsList.setAttribute("aria-label", "Các lựa chọn");

  item.options.forEach((opt, idx) => {
    const letter = String.fromCharCode(65 + idx);
    const isChosen = item.chosen && item.chosen.includes(opt.id);
    const isCorrect = item.correct && item.correct.includes(opt.id);

    let cls = "test-option-btn";
    if (isChosen) cls += " is-selected";
    if (item.checked) {
      if (isCorrect) cls += " is-correct";
      else if (isChosen) cls += " is-wrong";
    }

    const btn = el("button", cls);
    btn.type = "button";
    btn.dataset.act = "test-choose";
    btn.dataset.option = opt.id;
    if (item.checked) btn.disabled = true;

    btn.append(el("span", "test-opt-badge", letter));
    btn.append(el("span", "test-opt-text", opt.text));
    optsList.append(btn);

    if (item.checked && opt.why) {
      optsList.append(el("div", "test-opt-why", opt.why));
    }
  });
  box.append(optsList);

  if (item.checked) {
    const banner = el("div", "test-checked-banner " + (item.is_correct ? "is-pass" : "is-fail"),
      item.is_correct ? "✓ Đúng" : "✕ Chưa chính xác"
    );
    box.append(banner);

    if (item.explanation) {
      const expBox = el("div", "test-explanation-box");
      expBox.append(el("div", "auth-label", "Lời giải"));
      const expText = el("div", "test-desc-box");
      expText.innerHTML = renderTestText(item.explanation);
      attachSafeLinks(expText);
      expBox.append(expText);
      box.append(expBox);
    }

    if (item.best_practice) {
      const bpBox = el("div", "test-best-practice-box");
      bpBox.append(el("div", "auth-label", "Best Practice"));
      const bpText = el("div", "test-desc-box");
      bpText.innerHTML = renderTestText(item.best_practice);
      attachSafeLinks(bpText);
      bpBox.append(bpText);
      box.append(bpBox);
    }

    if (item.docs && item.docs.length > 0) {
      const docsBox = el("div", "test-docs-box");
      docsBox.append(el("div", "auth-label", "Tài liệu tham khảo"));
      const ul = el("ul", "up-list");
      item.docs.forEach(href => {
        const li = el("li", null);
        const a = el("a", null, href);
        a.href = href;
        li.append(a);
        ul.append(li);
      });
      attachSafeLinks(ul);
      docsBox.append(ul);
      box.append(docsBox);
    }
  }

  const itemActions = el("div", "test-item-actions");
  if (_currentAttempt.ask && (item.checked || _currentAttempt.status === "submitted")) {
    const askBtn = el("button", "btn-studio-secondary", "Hỏi về câu này");
    askBtn.type = "button";
    askBtn.dataset.act = "test-item-ask";
    askBtn.dataset.itemId = item.id;
    itemActions.append(askBtn);
  }
  const fbBtn = el("button", "btn-link-quiet", "Báo sai câu này");
  fbBtn.type = "button";
  fbBtn.dataset.act = "test-item-feedback";
  fbBtn.dataset.itemId = item.id;
  itemActions.append(fbBtn);
  box.append(itemActions);

  const counter = $("testRunCounter");
  if (counter) counter.textContent = `Câu ${_currentIndex + 1} / ${_currentAttempt.items.length}`;

  const btnPrev = $("btnTestPrev");
  if (btnPrev) btnPrev.disabled = _currentIndex === 0;

  const btnNext = $("btnTestNext");
  if (btnNext) btnNext.disabled = _currentIndex === _currentAttempt.items.length - 1;

  const btnFlag = $("btnTestFlag");
  if (btnFlag) {
    btnFlag.textContent = item.flagged ? "Bỏ cờ" : "Gắn cờ";
    btnFlag.classList.toggle("is-flagged", !!item.flagged);
  }

  const btnCheck = $("btnTestCheck");
  if (btnCheck) {
    const isPracticeOrReview = _currentAttempt.mode === "practice" || _currentAttempt.mode === "review";
    btnCheck.hidden = !isPracticeOrReview || !!item.checked;
  }
}

function renderGrid() {
  const grid = $("testGrid");
  if (!grid || !_currentAttempt || !_currentAttempt.items) return;
  grid.textContent = "";

  _currentAttempt.items.forEach((it, idx) => {
    let cls = "test-grid-btn";
    if (idx === _currentIndex) cls += " is-current";
    if (it.chosen && it.chosen.length > 0) cls += " is-answered";
    if (it.flagged) cls += " is-flagged";
    if (it.checked) {
      if (it.is_correct) cls += " is-correct";
      else cls += " is-wrong";
    }

    const b = el("button", cls, String(idx + 1));
    b.type = "button";
    b.dataset.act = "test-jump";
    b.dataset.idx = String(idx);
    grid.append(b);
  });
}

function goToQuestion(idx) {
  if (!_currentAttempt || !_currentAttempt.items) return;
  if (idx < 0 || idx >= _currentAttempt.items.length) return;
  stopSpeech();
  _currentIndex = idx;
  renderCurrentQuestion();
  renderGrid();
  const pane = $("testGridPane");
  if (pane) pane.classList.remove("is-open");
}

function chooseOption(optId) {
  if (!_currentAttempt || !_currentAttempt.items) return;
  const item = _currentAttempt.items[_currentIndex];
  if (!item || item.checked) return;

  let chosen = Array.isArray(item.chosen) ? [...item.chosen] : [];
  if (item.type === "single") {
    chosen = [optId];
  } else {
    const idx = chosen.indexOf(optId);
    if (idx !== -1) {
      chosen.splice(idx, 1);
    } else {
      if (chosen.length < item.required) {
        chosen.push(optId);
      } else {
        chosen.shift();
        chosen.push(optId);
      }
    }
  }
  queueSave(item.id, { chosen });
  renderCurrentQuestion();
}

async function checkCurrentItem() {
  if (!_currentAttempt || !_currentAttemptId) return;
  const item = _currentAttempt.items[_currentIndex];
  if (!item) return;

  if (item.type === "multi" && item.chosen.length !== item.required) {
    alert(`Cần chọn đủ ${item.required} đáp án.`);
    return;
  }

  const btn = $("btnTestCheck");
  if (btn) btn.disabled = true;

  try {
    const checkedItem = await api(
      `/api/attempts/${encodeURIComponent(_currentAttemptId)}/items/${encodeURIComponent(item.id)}/check`,
      send("POST", { chosen: item.chosen })
    );
    if (_saveQueue[item.id]) {
      _saveQueue[item.id].pending = null;
      _saveQueue[item.id].status = "idle";
      updateSaveIndicator();
    }
    _currentAttempt.items[_currentIndex] = checkedItem;
    stopSpeech();
    renderCurrentQuestion();
    renderGrid();
  } catch (err) {
    if (err.code === "checked") {
      reloadAttempt();
    } else {
      alert(err.message || "Không thể kiểm tra câu trả lời.");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function togglePause() {
  if (!_currentAttempt || !_currentAttemptId) return;
  try {
    if (_currentAttempt.status === "paused") {
      const res = await api(`/api/attempts/${encodeURIComponent(_currentAttemptId)}/resume`, send("POST"));
      _currentAttempt = res;
      renderRunScreen();
      startClock();
    } else {
      const res = await api(`/api/attempts/${encodeURIComponent(_currentAttemptId)}/pause`, send("POST"));
      _currentAttempt = res;
      if (_clockInterval) {
        clearInterval(_clockInterval);
        _clockInterval = null;
      }
      stopSpeech();
      renderRunScreen();
    }
  } catch (err) {
    if (err.code === "submitted") {
      leaveAttempt();
      location.hash = "#result=" + encodeURIComponent(_currentAttemptId);
    } else {
      alert(err.message || "Thao tác không thành công.");
    }
  }
}

function openSubmitDialog() {
  if (!_currentAttempt || !_currentAttemptId) return;

  let hasSending = false;
  let hasFailed = false;
  for (const k in _saveQueue) {
    const q = _saveQueue[k];
    if (q) {
      if (q.status === "sending" || q.pending !== null) hasSending = true;
      if (q.status === "failed") hasFailed = true;
    }
  }
  if (hasFailed) {
    alert("Chưa lưu xong các câu trả lời. Vui lòng kiểm tra kết nối mạng.");
    return;
  }
  if (hasSending) {
    alert("Đang lưu câu trả lời, vui lòng chờ trong giây lát.");
    return;
  }

  const dia = $("testSubmitDialog");
  const sum = $("testSubmitSummary");
  const alertEl = $("testSubmitAlert");
  if (!dia || !sum) return;
  if (alertEl) alertEl.hidden = true;

  const items = _currentAttempt.items || [];
  const unanswered = [];
  const flagged = [];

  items.forEach((it, idx) => {
    if (!it.chosen || it.chosen.length === 0) unanswered.push(idx + 1);
    if (it.flagged) flagged.push(idx + 1);
  });

  sum.textContent = "";

  if (unanswered.length === 0 && flagged.length === 0) {
    sum.append(el("p", null, "Bạn đã trả lời hết tất cả các câu hỏi."));
  } else {
    if (unanswered.length > 0) {
      const box = el("div", null);
      box.append(el("p", null, `Còn ${unanswered.length} câu chưa làm:`));
      const row = el("div", "submit-num-row");
      unanswered.forEach(num => {
        const btn = el("button", "submit-num-link", String(num));
        btn.type = "button";
        btn.dataset.act = "test-jump-dialog";
        btn.dataset.idx = String(num - 1);
        row.append(btn);
      });
      box.append(row);
      sum.append(box);
    }
    if (flagged.length > 0) {
      const box = el("div", null);
      box.append(el("p", null, `Có ${flagged.length} câu đã gắn cờ xem lại:`));
      const row = el("div", "submit-num-row");
      flagged.forEach(num => {
        const btn = el("button", "submit-num-link", String(num));
        btn.type = "button";
        btn.dataset.act = "test-jump-dialog";
        btn.dataset.idx = String(num - 1);
        row.append(btn);
      });
      box.append(row);
      sum.append(box);
    }
  }

  dia.showModal();
}

async function confirmSubmit(isAuto = false) {
  if (!_currentAttemptId) return;
  const dia = $("testSubmitDialog");
  const btn = $("btnConfirmSubmit");
  const alertEl = $("testSubmitAlert");
  if (btn) btn.disabled = true;

  try {
    await api(`/api/attempts/${encodeURIComponent(_currentAttemptId)}/submit`, send("POST"));
    if (dia && dia.open) dia.close();
    const attId = _currentAttemptId;
    leaveAttempt();
    location.hash = "#result=" + encodeURIComponent(attId);
  } catch (err) {
    if (err.code === "submitted") {
      if (dia && dia.open) dia.close();
      const attId = _currentAttemptId;
      leaveAttempt();
      location.hash = "#result=" + encodeURIComponent(attId);
    } else if (isAuto) {
      reloadAttempt();
    } else {
      if (alertEl) {
        alertEl.textContent = err.message || "Không thể nộp bài. Vui lòng thử lại.";
        alertEl.hidden = false;
      } else {
        alert(err.message || "Không thể nộp bài.");
      }
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function showTestRun(attemptId) {
  go("test-run", true, "#attempt=" + encodeURIComponent(attemptId));
  document.body.classList.add("in-test");

  if (_currentAttemptId === attemptId && _currentAttempt) {
    renderRunScreen();
    return;
  }

  leaveAttempt();
  document.body.classList.add("in-test");
  _currentAttemptId = attemptId;
  _currentIndex = 0;

  applySavedFont();

  const box = $("testQuestionBox");
  if (box) {
    box.textContent = "Đang tải bài thi...";
  }

  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attemptId)}`);
    if (att.status === "submitted") {
      leaveAttempt();
      location.hash = "#result=" + encodeURIComponent(attemptId);
      return;
    }
    _currentAttempt = att;
    renderRunScreen();
    startClock();
    setupTts();
  } catch (err) {
    if (err.message !== "login" && err.message !== "password") {
      if (box) box.textContent = err.message || "Không tải được lượt làm bài.";
    }
  }
}

async function showTestResult(attemptId) {
  leaveAttempt();
  go("test-result", true, "#result=" + encodeURIComponent(attemptId));
  _resultFilter = "all";

  const title = $("testResultTitle");
  const pill = $("testResultPill");
  const pills = $("testResultPills");
  const scoreNum = $("testResultScore");
  const passStatus = $("testResultStatus");
  const actions = $("testResultActions");
  const domainsSection = $("testResultDomainsSection");
  const domainsBody = $("testResultDomainBody");
  const itemsList = $("testResultItemsList");

  if (title) title.textContent = "Đang tải kết quả...";
  if (pills) pills.textContent = "";
  if (scoreNum) scoreNum.textContent = "";
  if (passStatus) passStatus.textContent = "";
  if (actions) actions.textContent = "";
  if (domainsBody) domainsBody.textContent = "";
  if (itemsList) itemsList.textContent = "Đang tải câu hỏi...";

  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attemptId)}`);
    if (att.status !== "submitted") {
      location.hash = "#attempt=" + encodeURIComponent(attemptId);
      return;
    }
    _resultAttempt = att;

    if (title) title.textContent = att.title;
    if (pill) {
      pill.textContent = att.mode === "exam" ? "Thi thử" :
        (att.mode === "practice" ? "Luyện tập" : "Ôn câu sai");
    }

    const res = att.result;
    if (pills) {
      pills.textContent = "";
      const pillList = [];
      if (res) {
        pillList.push(`Thời gian: ${fmt(res.duration_seconds)}`);
        if (att.pause_count > 0) {
          pillList.push(`Tạm dừng: ${att.pause_count} lần (${fmt(att.paused_seconds)})`);
        }
      }
      pillList.forEach(txt => pills.append(el("span", "meta-pill", txt)));
    }

    if (res) {
      if (scoreNum) scoreNum.textContent = `${res.score} / ${res.total} (${res.percent}%)`;
      if (passStatus) {
        passStatus.textContent = res.passed ?
          `ĐẬU (Ngưỡng đạt ${res.pass_percent}%)` :
          `CHƯA ĐẬU (Ngưỡng đạt ${res.pass_percent}%)`;
        passStatus.className = "result-pass-status " + (res.passed ? "is-pass" : "is-fail");
      }
      if (domainsSection) domainsSection.hidden = false;
      if (domainsBody) {
        domainsBody.textContent = "";
        (res.by_domain || []).forEach(d => {
          const tr = document.createElement("tr");
          const tdName = document.createElement("td");
          tdName.textContent = d.domain;
          const tdCount = document.createElement("td");
          tdCount.textContent = `${d.correct} / ${d.total}`;
          const tdPct = document.createElement("td");
          tdPct.textContent = `${d.percent}%`;
          tr.append(tdName, tdCount, tdPct);
          domainsBody.append(tr);
        });
      }
    } else {
      if (scoreNum) scoreNum.textContent = "Đã hoàn thành lượt ôn";
      if (passStatus) passStatus.textContent = "";
      if (domainsSection) domainsSection.hidden = true;
    }

    if (actions) {
      actions.textContent = "";
      const restartBtn = el("button", "btn-studio-primary", "Làm lại");
      restartBtn.type = "button";
      restartBtn.dataset.act = "attempt-start";
      restartBtn.dataset.key = att.test_key;
      restartBtn.dataset.mode = att.mode;
      restartBtn.dataset.restart = "true";
      actions.append(restartBtn);

      const wrongCount = (att.items || []).filter(it => !it.is_correct).length;
      if (wrongCount > 0 || att.mode === "review") {
        const reviewBtn = el("button", "btn-studio-secondary", "Ôn câu sai");
        reviewBtn.type = "button";
        reviewBtn.dataset.act = "attempt-start";
        reviewBtn.dataset.key = att.test_key;
        reviewBtn.dataset.mode = "review";
        actions.append(reviewBtn);
      }
    }

    const btnDetail = $("btnResultDetail");
    if (btnDetail) {
      btnDetail.dataset.act = "test-detail";
      btnDetail.dataset.id = att.test_key;
    }

    renderResultItems();
  } catch (err) {
    if (err.message !== "login" && err.message !== "password") {
      if (title) title.textContent = err.message || "Không tải được kết quả.";
    }
  }
}

function renderResultItems() {
  const list = $("testResultItemsList");
  if (!list || !_resultAttempt || !_resultAttempt.items) return;

  list.textContent = "";

  const filtered = _resultAttempt.items.map((it, idx) => ({ it, originalIdx: idx })).filter(({ it }) => {
    if (_resultFilter === "wrong") return !it.is_correct;
    if (_resultFilter === "flagged") return !!it.flagged;
    return true;
  });

  if (filtered.length === 0) {
    list.append(el("p", "dock-note", "Không có câu hỏi nào theo bộ lọc này."));
    return;
  }

  filtered.forEach(({ it, originalIdx }) => {
    const card = el("article", "test-result-card " + (it.is_correct ? "is-correct" : "is-wrong"));

    const head = el("div", "result-card-head");
    const titleNum = el("h3", "stream-title", `Câu ${originalIdx + 1}`);
    const badges = el("div", "result-card-badges");
    badges.append(el("span", "meta-pill " + (it.is_correct ? "is-pass" : "is-warn"), it.is_correct ? "Đúng" : "Sai"));
    if (it.domain) badges.append(el("span", "meta-pill", it.domain));
    if (it.flagged) badges.append(el("span", "meta-pill is-warn", "Gắn cờ"));
    head.append(titleNum, badges);
    card.append(head);

    const qText = el("div", "test-desc-box");
    qText.innerHTML = renderTestText(it.question);
    attachSafeLinks(qText);
    card.append(qText);

    const optList = el("div", "test-options-list");
    (it.options || []).forEach((opt, oIdx) => {
      const letter = String.fromCharCode(65 + oIdx);
      const isChosen = it.chosen && it.chosen.includes(opt.id);
      const isCorrect = it.correct && it.correct.includes(opt.id);

      let cls = "test-option-btn";
      if (isCorrect) cls += " is-correct";
      else if (isChosen) cls += " is-wrong";

      const optBtn = el("div", cls);
      optBtn.append(el("span", "test-opt-badge", letter));

      const bodySpan = el("span", "test-opt-text", opt.text);
      if (isChosen) {
        bodySpan.append(el("span", "meta-pill", " Bạn chọn"));
      }
      if (isCorrect) {
        bodySpan.append(el("span", "meta-pill", " Đáp án đúng"));
      }
      optBtn.append(bodySpan);
      optList.append(optBtn);

      if (opt.why) {
        optList.append(el("div", "test-opt-why", opt.why));
      }
    });
    card.append(optList);

    if (it.explanation) {
      const expBox = el("div", "test-explanation-box");
      expBox.append(el("div", "auth-label", "Lời giải"));
      const expText = el("div", "test-desc-box");
      expText.innerHTML = renderTestText(it.explanation);
      attachSafeLinks(expText);
      expBox.append(expText);
      card.append(expBox);
    }

    if (it.best_practice) {
      const bpBox = el("div", "test-best-practice-box");
      bpBox.append(el("div", "auth-label", "Best Practice"));
      const bpText = el("div", "test-desc-box");
      bpText.innerHTML = renderTestText(it.best_practice);
      attachSafeLinks(bpText);
      bpBox.append(bpText);
      card.append(bpBox);
    }

    if (it.docs && it.docs.length > 0) {
      const docsBox = el("div", "test-docs-box");
      docsBox.append(el("div", "auth-label", "Tài liệu tham khảo"));
      const ul = el("ul", "up-list");
      it.docs.forEach(href => {
        const li = el("li", null);
        const a = el("a", null, href);
        a.href = href;
        li.append(a);
        ul.append(li);
      });
      attachSafeLinks(ul);
      docsBox.append(ul);
      card.append(docsBox);
    }

    const cardActions = el("div", "test-item-actions");
    if (_resultAttempt && _resultAttempt.ask) {
      const askBtn = el("button", "btn-studio-secondary", "Hỏi về câu này");
      askBtn.type = "button";
      askBtn.dataset.act = "test-item-ask";
      askBtn.dataset.itemId = it.id;
      cardActions.append(askBtn);
    }
    const fbBtn = el("button", "btn-link-quiet", "Báo sai câu này");
    fbBtn.type = "button";
    fbBtn.dataset.act = "test-item-feedback";
    fbBtn.dataset.itemId = it.id;
    cardActions.append(fbBtn);
    card.append(cardActions);

    list.append(card);
  });
}

function reportItem(itemId) {
  const att = _currentAttempt || _resultAttempt;
  if (!att) return;
  const idx = (att.items || []).findIndex(x => x.id === itemId);
  const numStr = idx >= 0 ? `Câu ${idx + 1}` : itemId;
  if (window.openFeedback) {
    window.openFeedback({
      url: `/api/attempts/${encodeURIComponent(att.id)}/items/${encodeURIComponent(itemId)}/feedback`,
      kind: "wrong",
      label: `${att.title || "Bộ đề"} · ${numStr}`,
      title: "Báo sai câu hỏi",
    });
  }
}

let _askAttemptId = null;
let _askItemId = null;
let _askSending = false;

async function openItemAsk(itemId) {
  const att = _currentAttempt || _resultAttempt;
  if (!att) return;
  _askAttemptId = att.id;
  _askItemId = itemId;
  const idx = (att.items || []).findIndex(x => x.id === itemId);
  const numStr = idx >= 0 ? `Câu ${idx + 1}` : itemId;

  const dia = $("testAskDialog");
  const ctx = $("testAskContext");
  const thread = $("testAskThread");
  const err = $("testAskError");
  const clearBtn = $("testAskClear");
  const input = $("testAskInput");
  if (!dia || !thread) return;

  if (ctx) ctx.textContent = `Đang hỏi về: ${att.title || "Bộ đề"} · ${numStr}. Câu hỏi được lưu để bạn xem lại và hỏi tiếp; tác giả đề không xem được.`;
  if (err) err.hidden = true;
  if (clearBtn) clearBtn.hidden = true;
  if (input) input.value = "";
  thread.textContent = "Đang tải...";
  dia.showModal();

  try {
    const d = await api(`/api/attempts/${encodeURIComponent(_askAttemptId)}/items/${encodeURIComponent(_askItemId)}/ask`);
    thread.textContent = "";
    const msgs = d.messages || [];
    if (msgs.length > 0 && clearBtn) clearBtn.hidden = false;
    const bubbles = msgs.map(m => {
      const b = el("div", "ask-bubble " + (m.role === "user" ? "is-question" : "md-answer"));
      if (m.role === "user") {
        b.textContent = m.text;
      } else {
        b.innerHTML = renderAnswer(m.text);
      }
      return b;
    });
    thread.append(...bubbles);
    thread.scrollTop = thread.scrollHeight;
    if (window.MathJax && MathJax.startup) {
      await MathJax.startup.promise;
      await MathJax.typesetPromise(bubbles).catch(() => {});
      thread.scrollTop = thread.scrollHeight;
    }
  } catch (e) {
    thread.textContent = e.message || "Không tải được lịch sử hỏi.";
  }
}

async function sendItemAsk() {
  if (_askSending || !_askAttemptId || !_askItemId) return;
  const input = $("testAskInput");
  const thread = $("testAskThread");
  const sendBtn = $("testAskSend");
  const clearBtn = $("testAskClear");
  const err = $("testAskError");
  if (!input || !thread) return;

  const q = input.value.trim();
  if (!q) return;

  if (err) err.hidden = true;
  const userBubble = el("div", "ask-bubble is-question", q);
  thread.append(userBubble);
  input.value = "";

  const botBubble = el("div", "ask-bubble md-answer", "Đang trả lời...");
  thread.append(botBubble);
  thread.scrollTop = thread.scrollHeight;

  _askSending = true;
  if (sendBtn) sendBtn.disabled = true;

  try {
    const d = await api(
      `/api/attempts/${encodeURIComponent(_askAttemptId)}/items/${encodeURIComponent(_askItemId)}/ask`,
      send("POST", { question: q })
    );
    botBubble.innerHTML = renderAnswer(d.text);
    if (window.MathJax && MathJax.typesetPromise) {
      await MathJax.typesetPromise([botBubble]).catch(() => {});
    }
    if (clearBtn) clearBtn.hidden = false;
  } catch (e) {
    botBubble.textContent = e.message || "Có lỗi khi gửi câu hỏi.";
    botBubble.classList.add("is-error");
    if (!input.value) input.value = q;
  } finally {
    _askSending = false;
    if (sendBtn) sendBtn.disabled = false;
    thread.scrollTop = thread.scrollHeight;
  }
}

async function clearItemAsk() {
  if (!_askAttemptId || !_askItemId) return;
  if (!confirm("Xóa toàn bộ câu hỏi của bạn về câu này?")) return;
  const thread = $("testAskThread");
  const clearBtn = $("testAskClear");
  try {
    await api(`/api/attempts/${encodeURIComponent(_askAttemptId)}/items/${encodeURIComponent(_askItemId)}/ask`, { method: "DELETE" });
    if (thread) thread.textContent = "";
    if (clearBtn) clearBtn.hidden = true;
  } catch (e) {
    alert(e.message || "Không thể xóa hội thoại.");
  }
}

function attachSafeLinks(container) {
  if (!container) return;
  container.addEventListener("click", e => {
    const a = e.target.closest("a");
    if (!a || !a.href) return;
    e.preventDefault();
    e.stopPropagation();
    if (confirm(`Mở liên kết ngoài?\n${a.href}`)) {
      window.open(a.href, "_blank", "noopener,noreferrer");
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  attachSafeLinks($("testDetailDesc"));
  attachSafeLinks($("screen-test-run"));
  attachSafeLinks($("screen-test-result"));

  const askForm = $("testAskForm");
  if (askForm) askForm.addEventListener("submit", e => { e.preventDefault(); sendItemAsk(); });
  const askInput = $("testAskInput");
  if (askInput) askInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendItemAsk(); }
  });
});

Object.assign(ACTIONS, {
  "test-open": el => { location.hash = "#test=" + encodeURIComponent(el.dataset.id); },
  "test-detail": el => { location.hash = "#test=" + encodeURIComponent(el.dataset.id); },
  "test-back": () => { location.hash = "#tests"; },
  "attempt-open": el => { location.hash = "#attempt=" + encodeURIComponent(el.dataset.id); },
  "attempt-result": el => { location.hash = "#result=" + encodeURIComponent(el.dataset.id); },
  "attempt-start": async el => {
    const key = el.dataset.key;
    const mode = el.dataset.mode;
    const restart = el.dataset.restart === "true";
    if (restart) {
      const modeName = mode === "exam" ? "Thi thử" : (mode === "practice" ? "Luyện tập" : "Ôn câu sai");
      if (!confirm(`Bắt đầu lại lượt ${modeName}? Tiến độ của lượt dở sẽ bị xóa.`)) return;
    }
    try {
      const att = await api(`/api/tests/${encodeURIComponent(key)}/attempts`, send("POST", { mode, restart }));
      location.hash = "#attempt=" + encodeURIComponent(att.id);
    } catch (err) {
      const alert = $("testDetailAlert");
      if (alert) {
        alert.textContent = err.message || "Không bắt đầu được lượt làm bài.";
        alert.hidden = false;
      }
    }
  },
  "test-choose": el => { chooseOption(el.dataset.option); },
  "test-prev": () => { goToQuestion(_currentIndex - 1); },
  "test-next": () => { goToQuestion(_currentIndex + 1); },
  "test-flag": () => {
    if (_currentAttempt && _currentAttempt.items && _currentAttempt.items[_currentIndex]) {
      const it = _currentAttempt.items[_currentIndex];
      queueSave(it.id, { flagged: !it.flagged });
      renderCurrentQuestion();
    }
  },
  "test-check": () => { checkCurrentItem(); },
  "test-pause": () => { togglePause(); },
  "test-submit": () => { openSubmitDialog(); },
  "test-cancel-submit": () => {
    const dia = $("testSubmitDialog");
    if (dia) dia.close();
  },
  "test-confirm-submit": () => { confirmSubmit(); },
  "test-jump": el => { goToQuestion(parseInt(el.dataset.idx, 10)); },
  "test-jump-dialog": el => {
    const dia = $("testSubmitDialog");
    if (dia) dia.close();
    goToQuestion(parseInt(el.dataset.idx, 10));
  },
  "test-toggle-grid": () => {
    const pane = $("testGridPane");
    if (pane) pane.classList.toggle("is-open");
  },
  "test-close-grid": () => {
    const pane = $("testGridPane");
    if (pane) pane.classList.remove("is-open");
  },
  "test-font-dec": () => { changeFont(-1); },
  "test-font-inc": () => { changeFont(1); },
  "test-speech": () => { toggleSpeech(); },
  "test-item-ask": el => { openItemAsk(el.dataset.itemId); },
  "test-item-feedback": el => { reportItem(el.dataset.itemId); },
  "test-ask-clear": () => { clearItemAsk(); },
  "test-ask-close": () => {
    const dia = $("testAskDialog");
    if (dia) dia.close();
  },
  "result-filter": el => {
    _resultFilter = el.dataset.filter || "all";
    $$(".filter-tab").forEach(tab => {
      tab.classList.toggle("active", tab.dataset.filter === _resultFilter);
    });
    renderResultItems();
  }
});

window.testRoute = testRoute;
window.renderTestText = renderTestText;
window.testPrompt = testPrompt;
window.copyTestPrompt = copyTestPrompt;
window.parseTestJson = parseTestJson;
window.mergeTestFiles = mergeTestFiles;
window.leaveAttempt = leaveAttempt;
