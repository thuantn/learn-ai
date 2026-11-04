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
      const hasOpen = t.open && (t.open.exam || t.open.practice || t.open.review);
      if (hasOpen) {
        pillTexts.push("Đang làm dở");
      }
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
      const btn = actionButton("Xem đề", "test-open", t.key, "btn-studio-secondary");
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

      // 3. Ôn câu sai (chạy khi t.pool > 0 hoặc t.open.review tồn tại)
      const reviewOpen = t.open && t.open.review;
      if ((t.pool && t.pool > 0) || reviewOpen) {
        if (reviewOpen) {
          const contLabel = (t.pool && t.pool > 0) ? `Tiếp tục Ôn (${t.pool} câu)` : "Tiếp tục Ôn";
          const cont = el("button", "btn-studio-primary", contLabel);
          cont.type = "button";
          cont.dataset.act = "attempt-open";
          cont.dataset.id = reviewOpen;
          actions.append(cont);
          if (t.pool && t.pool > 0) {
            const restart = el("button", "btn-studio-secondary", "Ôn lại từ đầu");
            restart.type = "button";
            restart.dataset.act = "attempt-start";
            restart.dataset.key = t.key;
            restart.dataset.mode = "review";
            restart.dataset.restart = "true";
            actions.append(restart);
          }
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
let _loadToken = 0;
let _submitting = false;

function showRunNotice(text) {
  const el = $("testRunNotice");
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
}

function clearRunNotice() {
  const el = $("testRunNotice");
  if (!el) return;
  el.textContent = "";
  el.hidden = true;
}

function endAttempt(pauseClock = false) {
  document.body.classList.remove("in-test");
  if (_clockInterval) {
    clearInterval(_clockInterval);
    _clockInterval = null;
  }

  const attId = _currentAttemptId;
  const att = _currentAttempt;

  if (pauseClock && att && att.mode === "exam" && att.time_limit_seconds > 0 && att.status === "open" && attId) {
    fetch(`/api/attempts/${encodeURIComponent(attId)}/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      keepalive: true
    }).catch(() => {});
  }

  for (const itemId in _saveQueue) {
    const q = _saveQueue[itemId];
    if (q) {
      // Its reply sends what is pending; sending that now could arrive first and be overwritten by the older answer.
      if (q.status === "sending") continue;
      const payload = Object.assign({}, q.failed, q.pending);
      if (Object.keys(payload).length > 0 && attId) {
        fetch(`/api/attempts/${encodeURIComponent(attId)}/items/${encodeURIComponent(itemId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          keepalive: true
        }).catch(() => {});
      }
      q.failed = null;
      q.pending = null;
      if (q.timer) {
        clearTimeout(q.timer);
        q.timer = null;
      }
    }
  }
  _saveQueue = {};
  stopSpeech();
  clearRunNotice();
  const autoErr = $("testAutoSubmitError");
  if (autoErr) autoErr.hidden = true;
  _currentAttempt = null;
  _currentAttemptId = null;
}
// What the rest of the app calls on leaving: stops a timed exam's clock.
window.leaveAttempt = () => endAttempt(true);

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

let _readingOn = false;
let _speechRun = 0;
let _speechStartTimer = null;

function currentSpeechRate() {
  try {
    const raw = localStorage.getItem("learn.test-speech-rate");
    if (raw !== null) {
      const v = parseFloat(raw);
      if (SPEEDS.includes(v)) return v;
    }
  } catch (_) {}
  return 1;
}

function renderSpeechRate() {
  const btn = $("btnTestSpeechRate");
  if (!btn) return;
  const v = currentSpeechRate();
  btn.textContent = String(v).replace(".", ",") + "x";
}

function cycleSpeechRate() {
  const next = SPEEDS[(SPEEDS.indexOf(currentSpeechRate()) + 1) % SPEEDS.length];
  try {
    localStorage.setItem("learn.test-speech-rate", String(next));
  } catch (_) {}
  renderSpeechRate();
  if (_readingOn) readCurrentQuestion();
}

function voicesFor(lang) {
  if (!lang || !("speechSynthesis" in window) || !window.speechSynthesis.getVoices) return [];
  return window.speechSynthesis.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith(lang.toLowerCase()));
}

function voiceFor(lang) {
  const voices = voicesFor(lang);
  if (!voices.length) return null;
  let saved = null;
  try {
    saved = localStorage.getItem("learn.test-speech-voice." + lang);
  } catch (_) {}
  if (saved) {
    const match = voices.find(v => v.voiceURI === saved);
    if (match) return match;
  }
  return voices.find(v => v.default) || voices.find(v => v.localService) || voices[0] || null;
}

function currentSpeechLang() {
  if (!_currentAttempt || !_currentAttempt.items || !_currentAttempt.items[_currentIndex]) return null;
  const item = _currentAttempt.items[_currentIndex];
  const div = document.createElement("div");
  div.innerHTML = renderTestText(item.question);
  const qText = div.textContent || "";
  const opts = (item.options || []).map(o => o.text).join(" ");
  return textLang(qText + " " + opts);
}

function renderVoicePicker() {
  const sel = $("testSpeechVoice");
  if (!sel) return;
  const lang = currentSpeechLang();
  const voices = voicesFor(lang);
  sel.innerHTML = "";
  for (const v of voices) {
    const opt = document.createElement("option");
    opt.value = v.voiceURI;
    opt.textContent = v.name;
    sel.appendChild(opt);
  }
  sel.hidden = voices.length < 2;
  const picked = voiceFor(lang);
  if (picked) {
    sel.value = picked.voiceURI;
  }
  sel.onchange = () => {
    const curLang = currentSpeechLang();
    if (curLang) {
      try {
        localStorage.setItem("learn.test-speech-voice." + curLang, sel.value);
      } catch (_) {}
    }
    if (_readingOn) readCurrentQuestion();
  };
}

function setupTts() {
  const btn = $("btnTestSpeech");
  const rateBtn = $("btnTestSpeechRate");
  const picker = $("testSpeechVoice");
  const note = $("testSpeechNote");
  if (!("speechSynthesis" in window)) {
    if (btn) btn.hidden = true;
    if (rateBtn) rateBtn.hidden = true;
    if (picker) picker.hidden = true;
    if (note) {
      note.textContent = "Trình duyệt không hỗ trợ giọng đọc.";
      note.hidden = false;
    }
    return;
  }
  if (btn) btn.hidden = false;
  if (rateBtn) rateBtn.hidden = false;
  if (note) note.hidden = true;
  renderSpeechRate();
  renderVoicePicker();
  if (window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = renderVoicePicker;
  }
}

// No lookbehind: older iOS WebKit cannot parse it.
function speechChunks(text) {
  if (!text) return [];
  const lines = text.replace(/([.!?…])\s+/g, "$1\n").split("\n");
  const chunks = [];
  for (const raw of lines) {
    let cur = raw.trim();
    if (!cur) continue;
    while (cur.length > 220) {
      const cut = cur.lastIndexOf(" ", 220);
      if (cut <= 0) {
        chunks.push(cur.slice(0, 220));
        cur = cur.slice(220).trim();
      } else {
        chunks.push(cur.slice(0, cut));
        cur = cur.slice(cut + 1).trim();
      }
    }
    if (cur.length > 0) chunks.push(cur);
  }
  return chunks;
}

// Increment run to make events from older utterances stale.
function silenceSpeech() {
  _speechRun++;
  if (_speechStartTimer) {
    clearTimeout(_speechStartTimer);
    _speechStartTimer = null;
  }
  if (window.speechSynthesis && window.speechSynthesis.cancel) {
    window.speechSynthesis.cancel();
  }
}

function stopSpeech() {
  _readingOn = false;
  silenceSpeech();
  const btn = $("btnTestSpeech");
  if (btn) {
    btn.textContent = "Đọc";
    btn.setAttribute("aria-label", "Đọc câu hỏi");
  }
}

function readCurrentQuestion() {
  silenceSpeech();
  const run = _speechRun;
  if (!_currentAttempt || !_currentAttempt.items || !_currentAttempt.items[_currentIndex]) return;
  const item = _currentAttempt.items[_currentIndex];

  const lang = currentSpeechLang();
  const voices = (window.speechSynthesis && window.speechSynthesis.getVoices) ? window.speechSynthesis.getVoices() : [];
  const voice = voiceFor(lang);
  if (voices.length > 0 && !voice) {
    stopSpeech();
    const note = $("testSpeechNote");
    if (note) {
      note.textContent = "Thiết bị chưa có giọng đọc " + (LANG_NAME[lang] || lang) + ".";
      note.hidden = false;
    }
    return;
  }

  const div = document.createElement("div");
  div.innerHTML = renderTestText(item.question);
  const qText = div.textContent || "";
  const pieces = speechChunks(qText);
  const label = lang === "vi" ? "Lựa chọn" : "Option";
  (item.options || []).forEach((opt, idx) => {
    const letter = String.fromCharCode(65 + idx);
    pieces.push(`${label} ${letter}: ${opt.text}.`);
  });

  if (!pieces.length || !window.speechSynthesis) return;

  if (typeof window.speechSynthesis.resume === "function") {
    try {
      window.speechSynthesis.resume();
    } catch (_) {}
  }

  const rate = currentSpeechRate();
  const defaultLang = lang === "vi" ? "vi-VN" : "en-US";

  // Speak all pieces synchronously: iOS requires the first speak inside the tap gesture.
  pieces.forEach((piece, idx) => {
    const u = new SpeechSynthesisUtterance(piece);
    u.rate = rate;
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    } else {
      u.lang = defaultLang;
    }
    if (idx === 0) {
      u.onstart = () => {
        if (run !== _speechRun) return;
        if (_speechStartTimer) {
          clearTimeout(_speechStartTimer);
          _speechStartTimer = null;
        }
        const startNote = $("testSpeechNote");
        if (startNote) startNote.hidden = true;
      };
    }
    u.onerror = e => {
      if (run !== _speechRun) return;
      if (e && (e.error === "canceled" || e.error === "interrupted")) return;
      stopSpeech();
      const note = $("testSpeechNote");
      if (note) {
        const err = (e && e.error) ? e.error : "unknown";
        note.textContent = "Không đọc được (" + err + "). Kiểm tra âm lượng và giọng đọc của thiết bị.";
        note.hidden = false;
      }
    };
    window.speechSynthesis.speak(u);
  });

  _speechStartTimer = setTimeout(() => {
    if (run !== _speechRun) return;
    const note = $("testSpeechNote");
    if (note) {
      note.textContent = "Thiết bị chưa phát được giọng đọc. Kiểm tra âm lượng; iPhone cần tắt công tắc im lặng.";
      note.hidden = false;
    }
  }, 5000);
}

function toggleSpeech() {
  if (!("speechSynthesis" in window)) return;
  if (_readingOn) {
    stopSpeech();
    return;
  }
  if (!_currentAttempt || !_currentAttempt.items || !_currentAttempt.items[_currentIndex]) return;
  const note = $("testSpeechNote");
  if (note) note.hidden = true;
  _readingOn = true;
  const btn = $("btnTestSpeech");
  if (btn) {
    btn.textContent = "Tắt đọc";
    btn.setAttribute("aria-label", "Tắt đọc câu hỏi");
  }
  readCurrentQuestion();
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
  sendSave(itemId, changes, _currentAttemptId, q);
}

async function sendSave(itemId, payload, attId = _currentAttemptId, q = _saveQueue[itemId]) {
  if (!attId || !q) return;

  try {
    const r = await fetch(`/api/attempts/${encodeURIComponent(attId)}/items/${encodeURIComponent(itemId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (r.status === 401) { location.href = "/login"; return; }

    const isCurrent = _currentAttemptId === attId;

    if (r.ok) {
      q.status = "idle";
      if (q.pending) {
        const next = q.pending;
        q.pending = null;
        q.status = "sending";
        sendSave(itemId, next, attId, q);
      }
      if (!isCurrent) return;
      updateSaveIndicator();
    } else if (r.status >= 400 && r.status < 500) {
      q.status = "idle";
      q.pending = null;
      if (!isCurrent) return;
      updateSaveIndicator();
      showRunNotice("Máy chủ không nhận câu trả lời vừa rồi. Câu này chưa được lưu.");
      reloadAttempt();
    } else {
      retrySave(itemId, attId, payload, q);
    }
  } catch (err) {
    retrySave(itemId, attId, payload, q);
  }
}

function retrySave(itemId, attId, payload, q) {
  if (_currentAttemptId !== attId || !q) {
    fetch(`/api/attempts/${encodeURIComponent(attId)}/items/${encodeURIComponent(itemId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({}, payload, q && q.pending)),
      keepalive: true
    }).catch(() => {});
    return;
  }
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
    sendSave(itemId, next, attId, q);
  }, 3000);
}

async function reloadAttempt() {
  const attId = _currentAttemptId;
  if (!attId) return false;
  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attId)}`);
    if (_currentAttemptId !== attId) return false;
    if (att.status === "submitted") {
      endAttempt();
      location.hash = "#result=" + encodeURIComponent(attId);
      return true;
    }
    _currentAttempt = att;
    renderRunScreen();
    return false;
  } catch (_) {
    return false;
  }
}

document.addEventListener("visibilitychange", async () => {
  if (document.hidden) return;
  const attId = _currentAttemptId;
  if (!attId || location.hash.indexOf("#attempt=") === -1) return;

  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attId)}`);
    if (_currentAttemptId !== attId) return;
    if (att.status === "submitted") {
      endAttempt();
      location.hash = "#result=" + encodeURIComponent(attId);
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

  const runTitle = $("testRunTitle");
  if (runTitle) runTitle.textContent = _currentAttempt.title || "";

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
    btn.setAttribute("aria-pressed", String(!!isChosen));
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
  clearRunNotice();
  if (!_currentAttempt || !_currentAttempt.items) return;
  if (idx < 0 || idx >= _currentAttempt.items.length) return;
  _currentIndex = idx;
  renderCurrentQuestion();
  renderGrid();
  renderVoicePicker();
  if (_readingOn) readCurrentQuestion();
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
  clearRunNotice();
  if (!_currentAttempt || !_currentAttemptId) return;
  const item = _currentAttempt.items[_currentIndex];
  if (!item) return;

  if (item.type === "multi" && item.chosen.length !== item.required) {
    showRunNotice(`Cần chọn đủ ${item.required} đáp án.`);
    return;
  }

  const btn = $("btnTestCheck");
  if (btn) btn.disabled = true;

  const attemptId = _currentAttemptId;
  const itemId = item.id;

  try {
    const checkedItem = await api(
      `/api/attempts/${encodeURIComponent(attemptId)}/items/${encodeURIComponent(itemId)}/check`,
      send("POST", { chosen: item.chosen })
    );
    if (_currentAttemptId !== attemptId) return;

    if (_saveQueue[itemId]) {
      _saveQueue[itemId].pending = null;
      _saveQueue[itemId].status = "idle";
      updateSaveIndicator();
    }
    const idx = _currentAttempt.items.findIndex(x => x.id === itemId);
    if (idx !== -1) {
      _currentAttempt.items[idx] = checkedItem;
    }
    if (idx === _currentIndex) {
      silenceSpeech();
      renderCurrentQuestion();
    }
    renderGrid();
  } catch (err) {
    if (_currentAttemptId !== attemptId) return;
    if (err.code === "checked") {
      reloadAttempt();
    } else {
      showRunNotice(err.message || "Không thể kiểm tra câu trả lời.");
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
      const attId = _currentAttemptId;
      endAttempt();
      location.hash = "#result=" + encodeURIComponent(attId);
    } else {
      showRunNotice(err.message || "Thao tác không thành công.");
    }
  }
}

function openSubmitDialog() {
  clearRunNotice();
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
    showRunNotice("Chưa lưu xong các câu trả lời. Vui lòng kiểm tra kết nối mạng.");
    return;
  }
  if (hasSending) {
    showRunNotice("Đang lưu câu trả lời, vui lòng chờ trong giây lát.");
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
  if (_submitting) return;
  _submitting = true;
  const attId = _currentAttemptId;
  if (!attId) {
    _submitting = false;
    return;
  }

  const dia = $("testSubmitDialog");
  const btn = $("btnConfirmSubmit");
  const alertEl = $("testSubmitAlert");
  if (btn) btn.disabled = true;

  try {
    await api(`/api/attempts/${encodeURIComponent(attId)}/submit`, send("POST"));
    if (dia && dia.open) dia.close();
    endAttempt();
    location.hash = "#result=" + encodeURIComponent(attId);
  } catch (err) {
    if (err.code === "submitted") {
      if (dia && dia.open) dia.close();
      endAttempt();
      location.hash = "#result=" + encodeURIComponent(attId);
    } else if (isAuto) {
      const moved = await reloadAttempt();
      if (!moved) {
        const autoErr = $("testAutoSubmitError");
        if (autoErr) autoErr.hidden = false;
      }
    } else {
      if (alertEl) {
        alertEl.textContent = err.message || "Không thể nộp bài. Vui lòng thử lại.";
        alertEl.hidden = false;
      }
    }
  } finally {
    if (btn) btn.disabled = false;
    _submitting = false;
  }
}

async function showTestRun(attemptId) {
  go("test-run", true, "#attempt=" + encodeURIComponent(attemptId));
  document.body.classList.add("in-test");

  if (_currentAttemptId === attemptId && _currentAttempt) {
    renderRunScreen();
    return;
  }

  const autoErr = $("testAutoSubmitError");
  if (autoErr) autoErr.hidden = true;

  endAttempt(true);
  document.body.classList.add("in-test");
  _currentAttemptId = attemptId;
  _currentIndex = 0;

  applySavedFont();

  const box = $("testQuestionBox");
  if (box) {
    box.textContent = "Đang tải bài thi...";
  }

  const token = ++_loadToken;
  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attemptId)}`);
    if (token !== _loadToken) return;
    if (att.status === "submitted") {
      endAttempt();
      location.hash = "#result=" + encodeURIComponent(attemptId);
      return;
    }
    _currentAttempt = att;
    renderRunScreen();
    startClock();
    setupTts();
  } catch (err) {
    if (token !== _loadToken) return;
    if (err.message !== "login" && err.message !== "password") {
      if (box) box.textContent = err.message || "Không tải được lượt làm bài.";
    }
  }
}

async function showTestResult(attemptId) {
  endAttempt();
  go("test-result", true, "#result=" + encodeURIComponent(attemptId));
  _resultFilter = "all";

  const title = $("testResultTitle");
  const pill = $("testResultPill");
  const pills = $("testResultPills");
  const scoreNum = $("testResultScore");
  const passStatus = $("testResultStatus");
  const actions = $("testResultActions");
  const resultAlert = $("testResultAlert");
  const domainsSection = $("testResultDomainsSection");
  const domainsBody = $("testResultDomainBody");
  const itemsList = $("testResultItemsList");

  if (title) title.textContent = "Đang tải kết quả...";
  if (pills) pills.textContent = "";
  if (scoreNum) scoreNum.textContent = "";
  if (passStatus) passStatus.textContent = "";
  if (actions) actions.textContent = "";
  if (resultAlert) resultAlert.hidden = true;
  if (domainsBody) domainsBody.textContent = "";
  if (itemsList) itemsList.textContent = "Đang tải câu hỏi...";

  const token = ++_loadToken;
  try {
    const att = await api(`/api/attempts/${encodeURIComponent(attemptId)}`);
    if (token !== _loadToken || location.hash !== "#result=" + encodeURIComponent(attemptId)) return;
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
      const pool = att.pool || 0;
      const isReviewMode = att.mode === "review";

      const showReview = !isReviewMode && pool > 0;
      const showRestart = isReviewMode ? pool > 0 : true;

      if (showReview) {
        const reviewBtn = el("button", "btn-studio-primary", "Ôn câu sai");
        reviewBtn.type = "button";
        reviewBtn.dataset.act = "attempt-start";
        reviewBtn.dataset.key = att.test_key;
        reviewBtn.dataset.mode = "review";
        actions.append(reviewBtn);
      }

      if (showRestart) {
        const restartCls = showReview ? "btn-studio-secondary" : "btn-studio-primary";
        const restartBtn = el("button", restartCls, "Làm lại");
        restartBtn.type = "button";
        restartBtn.dataset.act = "attempt-start";
        restartBtn.dataset.key = att.test_key;
        restartBtn.dataset.mode = att.mode;
        restartBtn.dataset.restart = "true";
        actions.append(restartBtn);
      }

      if (!showReview && !showRestart) {
        const backBtn = el("button", "btn-studio-primary", "Về trang đề");
        backBtn.type = "button";
        backBtn.dataset.act = "test-detail";
        backBtn.dataset.id = att.test_key;
        actions.append(backBtn);
      }
    }

    const btnDetail = $("btnResultDetail");
    if (btnDetail) {
      btnDetail.dataset.act = "test-detail";
      btnDetail.dataset.id = att.test_key;
    }

    const hasBlank = (att.items || []).some(it => !it.chosen || it.chosen.length === 0);
    const blankTab = document.querySelector('[data-act="result-filter"][data-filter="blank"]');
    if (blankTab) blankTab.hidden = !hasBlank;

    renderResultItems();
  } catch (err) {
    if (token !== _loadToken || location.hash !== "#result=" + encodeURIComponent(attemptId)) return;
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
    const isBlank = !it.chosen || it.chosen.length === 0;
    if (_resultFilter === "wrong") return !it.is_correct && !isBlank;
    if (_resultFilter === "blank") return isBlank;
    if (_resultFilter === "flagged") return !!it.flagged;
    return true;
  });

  if (filtered.length === 0) {
    list.append(el("p", "dock-note", "Không có câu hỏi nào theo bộ lọc này."));
    return;
  }

  filtered.forEach(({ it, originalIdx }) => {
    const isBlank = !it.chosen || it.chosen.length === 0;
    let cardCls = "test-result-card";
    if (it.is_correct) cardCls += " is-correct";
    else if (isBlank) cardCls += " is-blank";
    else cardCls += " is-wrong";

    const card = el("article", cardCls);

    const head = el("div", "result-card-head");
    const titleNum = el("h3", "stream-title", `Câu ${originalIdx + 1}`);
    const badges = el("div", "result-card-badges");
    if (it.is_correct) {
      badges.append(el("span", "meta-pill is-pass", "Đúng"));
    } else if (isBlank) {
      badges.append(el("span", "meta-pill", "Bỏ trống"));
    } else {
      badges.append(el("span", "meta-pill is-warn", "Sai"));
    }
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
  const attemptId = _askAttemptId;
  const itId = _askItemId;

  const idx = (att.items || []).findIndex(x => x.id === itemId);
  const numStr = idx >= 0 ? `Câu ${idx + 1}` : itemId;

  const dia = $("testAskDialog");
  const ctx = $("testAskContext");
  const thread = $("testAskThread");
  const err = $("testAskError");
  const clearBtn = $("testAskClear");
  const input = $("testAskInput");
  if (!dia || !thread) return;

  if (ctx) ctx.textContent = `Đang hỏi về: ${att.title || "Bộ đề"} · ${numStr}. Chỉ bạn xem được câu hỏi.`;
  if (err) err.hidden = true;
  if (clearBtn) clearBtn.hidden = true;
  if (input) input.value = "";
  thread.textContent = "Đang tải...";
  dia.showModal();

  try {
    const d = await api(`/api/attempts/${encodeURIComponent(attemptId)}/items/${encodeURIComponent(itId)}/ask`);
    if (_askItemId !== itId || _askAttemptId !== attemptId) return;
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
    const lastQ = bubbles.slice().reverse().find(b => b.classList.contains("is-question")) || bubbles[bubbles.length - 1];
    if (lastQ) {
      thread.scrollTop += lastQ.getBoundingClientRect().top - thread.getBoundingClientRect().top;
    }
    if (window.MathJax && MathJax.startup) {
      await MathJax.startup.promise;
      await MathJax.typesetPromise(bubbles).catch(() => {});
      if (lastQ) {
        thread.scrollTop += lastQ.getBoundingClientRect().top - thread.getBoundingClientRect().top;
      }
    }
  } catch (e) {
    if (_askItemId !== itId || _askAttemptId !== attemptId) return;
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

  const botBubble = el("div", "ask-bubble md-answer is-pending", "Đang trả lời...");
  thread.append(botBubble);
  thread.scrollTop += userBubble.getBoundingClientRect().top - thread.getBoundingClientRect().top;

  _askSending = true;
  if (sendBtn) sendBtn.disabled = true;

  try {
    const d = await api(
      `/api/attempts/${encodeURIComponent(_askAttemptId)}/items/${encodeURIComponent(_askItemId)}/ask`,
      send("POST", { question: q })
    );
    botBubble.classList.remove("is-pending");
    botBubble.innerHTML = renderAnswer(d.text);
    if (window.MathJax && MathJax.typesetPromise) {
      await MathJax.typesetPromise([botBubble]).catch(() => {});
    }
    if (clearBtn) clearBtn.hidden = false;
  } catch (e) {
    botBubble.classList.remove("is-pending");
    botBubble.textContent = e.message || "Có lỗi khi gửi câu hỏi.";
    botBubble.classList.add("is-error");
    if (!input.value) input.value = q;
  } finally {
    _askSending = false;
    if (sendBtn) sendBtn.disabled = false;
  }
}

async function clearItemAsk() {
  if (!_askAttemptId || !_askItemId) return;
  if (!confirm("Xóa toàn bộ câu hỏi của bạn về câu này?")) return;
  const thread = $("testAskThread");
  const clearBtn = $("testAskClear");
  const err = $("testAskError");
  try {
    await api(`/api/attempts/${encodeURIComponent(_askAttemptId)}/items/${encodeURIComponent(_askItemId)}/ask`, { method: "DELETE" });
    if (thread) thread.textContent = "";
    if (clearBtn) clearBtn.hidden = true;
  } catch (e) {
    if (err) {
      err.textContent = e.message || "Không thể xóa hội thoại.";
      err.hidden = false;
    }
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

function exitAttempt() {
  const dia = $("testExitDialog");
  if (dia && dia.open) dia.close();
  if (_currentAttempt && _currentAttempt.test_key) {
    location.hash = "#test=" + encodeURIComponent(_currentAttempt.test_key);
  } else {
    location.hash = "#tests";
  }
}

window.addEventListener("beforeunload", e => {
  let hasUnsaved = false;
  for (const k in _saveQueue) {
    const q = _saveQueue[k];
    if (q && (q.status === "sending" || q.status === "failed" || (q.pending !== null && q.pending !== undefined) || (q.failed !== null && q.failed !== undefined))) {
      hasUnsaved = true;
      break;
    }
  }
  if (hasUnsaved) {
    e.preventDefault();
  }
});

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
  "test-exit": () => {
    let n = 0;
    for (const k in _saveQueue) {
      const q = _saveQueue[k];
      if (q && (q.status === "failed" || (q.failed !== null && q.failed !== undefined))) {
        n++;
      }
    }
    if (n > 0) {
      const txt = $("testExitText");
      if (txt) {
        txt.textContent = `Có ${n} câu chưa lưu được. Thoát thì sẽ gửi thử lần cuối, nhưng có thể mất nếu mạng chưa có lại.`;
      }
      const dia = $("testExitDialog");
      if (dia) dia.showModal();
    } else {
      exitAttempt();
    }
  },
  "test-exit-cancel": () => {
    const dia = $("testExitDialog");
    if (dia && dia.open) dia.close();
  },
  "test-exit-confirm": () => {
    exitAttempt();
  },
  "test-retry-submit": () => {
    const autoErr = $("testAutoSubmitError");
    if (autoErr) autoErr.hidden = true;
    confirmSubmit(true);
  },
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
      const resAlert = $("testResultAlert");
      const resScreen = $("screen-test-result");
      const alert = (resAlert && resScreen && resScreen.classList.contains("active")) ? resAlert : $("testDetailAlert");
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
  "test-speech-rate": () => { cycleSpeechRate(); },
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
