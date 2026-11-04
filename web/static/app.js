"use strict";
const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
const SCREENS = ["home", "library", "review", "listen", "flashcard", "finish", "tests", "test-detail", "test-run", "test-result"];
const state = { me: null, lessons: [], lesson: null, track: "long", due: 0, nextDue: null, cards: [], idx: 0, reviewed: 0, tests: [] };
function currentTrack() { return state.lesson && state.lesson.tracks[state.track]; }
const audio = new Audio();
audio.preload = "none";
let lastSaved = 0, pendingSeek = null, askLessonId = null;

// Leaving the page cuts in-flight requests; WebKit then logs a page error for each one even when
// the caller catches it. Aborting them first turns that into a plain AbortError.
let leaving = new AbortController();
window.addEventListener("beforeunload", () => {
  leaving.abort();
  // a download link or a cancelled unload keeps the page: later requests get a fresh signal
  setTimeout(() => { leaving = new AbortController(); }, 0);
});
async function api(url, opts) {
  const r = await fetch(url, { signal: leaving.signal, ...opts });
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 403 && d.code === "must_change") { location.href = "/change-password"; throw new Error("password"); }
  if (!r.ok) { const e = new Error(d.error || "Có lỗi. Thử lại sau."); e.code = d.code; throw e; }
  return d;
}
const send = (method, body, extra) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}), ...extra });

function fmt(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
const lessonNo = l => "Bài " + l.order;

function statusText(l) {
  if (l.status === "done") return l.due ? `Đã xong, còn ${l.due} thẻ đến hạn` : "Đã xong";
  if (l.status === "in_progress") return l.due ? `Đang học, còn ${l.due} thẻ đến hạn` : "Đang học";
  return "Chưa học";
}

// ---------- Screens ----------
function go(id, replace, hash) {
  if (id !== "test-run" && window.leaveAttempt) window.leaveAttempt();
  if (!SCREENS.includes(id)) id = "home";
  if (!state.lesson && ["review", "listen", "flashcard", "finish"].includes(id)) id = "home";
  if (id === "listen" && !hasAudio()) id = "flashcard";
  const isLesson = ["review", "listen", "flashcard", "finish"].includes(id);
  document.body.classList.toggle("in-lesson", isLesson);
  document.body.classList.toggle("on-listen", id === "listen");
  if (!isLesson) {
    openAsk(false);
  } else if ($("askDock").classList.contains("overlay-open")) {
    openAsk(false);
  }
  syncAsk();
  $$(".screen").forEach(s => s.classList.toggle("active", s.id === "screen-" + id));
  const navTarget = id.startsWith("test") ? "tests" : id;
  $$("[data-nav]").forEach(t => t.dataset.nav === navTarget ? t.setAttribute("aria-current", "page") : t.removeAttribute("aria-current"));
  const targetHash = hash || ("#" + id);
  if (location.hash !== targetHash) history[replace ? "replaceState" : "pushState"](null, "", targetHash);
  closeNav();
  window.scrollTo(0, 0);
  if (id === "flashcard") loadCards();
  if (id === "listen") loadTrack();
  if (id === "library") loadLibrary();
}
window.addEventListener("hashchange", () => {
  if (!location.hash.startsWith("#attempt=") && window.leaveAttempt) window.leaveAttempt();
  if (!joinFromLink() && !(window.testRoute && window.testRoute())) go(location.hash.slice(1), true);
});
const hasAudio = () => !!state.lesson && Object.keys(state.lesson.tracks).length > 0;

function closeNav() {
  $("navDrawer").classList.remove("open");
  $("navBackdrop").classList.remove("open");
}
function openAsk(open) {
  if (open) closeNav();
  const dock = $("askDock");
  const isLesson = document.body.classList.contains("in-lesson");
  if (!isLesson) {
    dock.classList.toggle("overlay-open", open);
  } else {
    dock.classList.remove("overlay-open");
  }
  dock.classList.toggle("mobile-open", open);
  // In a lesson on a wide screen the dock is a column of the grid; a backdrop there would cover it.
  const floats = !isLesson || window.matchMedia("(max-width: 1023px)").matches;
  $("askBackdrop").classList.toggle("open", open && floats);
  if (open && !$("askInput").disabled) $("askInput").focus();
  if (open) AskThread.showEnd();
}

// ---------- Rendering ----------
function renderFlow() {
  const names = ["Ôn lại", "Nghe", "Flashcard"];
  const skip = { 1: "listen", 2: "flashcard", 3: "finish" };
  $$("[data-flow]").forEach(box => {
    const at = +box.dataset.flow;
    box.textContent = "";
    const steps = document.createElement("div");
    steps.className = "flow-steps";
    let shown = 0;
    names.forEach((n, i) => {
      if (i === 1 && !hasAudio()) return;
      const s = document.createElement("button");
      s.type = "button";
      s.className = "flow-step-item" + (i + 1 === at ? " active" : "");
      s.dataset.step = i + 1;
      s.dataset.act = "go";
      s.dataset.to = ["review", "listen", "flashcard"][i];
      if (i + 1 === at) s.setAttribute("aria-current", "step");
      s.textContent = `${++shown}. ${n}`;
      steps.append(s);
    });
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn-studio-secondary flow-skip";
    b.textContent = "Bỏ qua";
    if (skip[at] === "finish") b.dataset.act = "finish";
    else { b.dataset.act = "go"; b.dataset.to = skip[at]; }
    box.append(steps, b);
  });
}

function renderLesson() {
  const l = state.lesson;
  const hasTests = state.tests && state.tests.length > 0;
  document.body.classList.toggle("no-lesson", !l);
  document.body.classList.toggle("no-audio", !hasAudio());
  renderFlow();
  document.querySelector('[data-nav="flashcard"] span').textContent = `${hasAudio() ? 3 : 2}. Flashcard`;
  $("homeCta").hidden = !l;
  $("homeEmptyCta").hidden = !!l || hasTests;
  $("homeListHeading").hidden = !l;
  $$("[data-next-listen]").forEach(b => { b.textContent = hasAudio() ? "Tiếp tục: Nghe podcast" : "Tiếp tục: Flashcard"; });
  if (!l) {
    if (hasTests) {
      $("homePill").textContent = "Luyện thi";
      $("home-title").textContent = "Bộ đề luyện thi";
      $("homeNote").textContent = "Chọn bộ đề bên dưới để bắt đầu làm bài.";
    } else {
      $("homePill").textContent = "Tài khoản mới";
      $("home-title").textContent = "Chưa có bài học nào";
      $("homeNote").textContent = "Tải lên bài của bạn, hoặc nhờ đồng nghiệp share bài để bắt đầu học.";
    }
    $("summary").textContent = "";
    $("dockKicker").textContent = "";
    $("dockTitle").textContent = "";
    return;
  }
  $$("[data-lesson-title]").forEach(e => { e.textContent = `${lessonNo(l)}: ${l.title}`; });
  $$("[data-lesson-short]").forEach(e => { e.textContent = lessonNo(l); });
  $$("[data-article]").forEach(a => { a.href = l.page; });
  $("homePill").textContent = statusText(l);
  $("homePill").classList.toggle("is-done", l.status === "done");
  $("home-title").textContent = `${lessonNo(l)}: ${l.title}`;
  const homeStart = $("homeCta")?.querySelector("[data-act=start]");
  if (homeStart) {
    if (l.status === "in_progress") homeStart.textContent = "Tiếp tục học";
    else if (l.status === "done") homeStart.textContent = "Học lại";
    else homeStart.textContent = "Bắt đầu học";
  }
  $("dockKicker").textContent = hasAudio() ? `Podcast, ${lessonNo(l)}` : lessonNo(l);
  $("dockTitle").textContent = l.title;
  const t = l.tracks;
  const at = currentTrack();
  const keys = Object.keys(t);
  let note = "";
  if (keys.length === 0) {
    note = "Bài này không có audio.";
  } else if (keys.length === 1) {
    const tr = t[keys[0]];
    note = `Podcast ${tr.label.toLowerCase()} ${fmt(tr.duration)}` + (at && at.position ? `, đang dừng ở ${fmt(at.position)}.` : ".");
  } else {
    note = `Podcast ${t.short.label.toLowerCase()} ${fmt(t.short.duration)}, ${t.long.label.toLowerCase()} ${fmt(t.long.duration)}` +
      (at && at.position ? `, đang dừng ở ${fmt(at.position)} của ${at.label.toLowerCase()}.` : ".");
  }
  if (keys.length > 0) note += " Cần có mạng để nghe.";
  $("homeNote").textContent = note;
  const box = $("summary");
  box.textContent = "";
  l.summary.forEach((text, i) => {
    const band = document.createElement("div");
    band.className = "summary-band";
    const n = document.createElement("span");
    n.className = "band-num";
    n.textContent = String(i + 1).padStart(2, "0");
    const p = document.createElement("p");
    p.className = "band-text";
    p.textContent = text;
    band.append(n, p);
    box.append(band);
  });
  renderTrackButtons();
  renderTime();
}

// Tests come ordered by package; each package gets its title above its tests so "Đề 1" says whose it is.
function testGroupHeading(t, last) {
  if (t.package_id === last) return null;
  const h = document.createElement("h3");
  h.className = "test-group-title";
  h.textContent = t.package_title || "Bộ đề";
  return h;
}

function renderHomeTests() {
  const heading = $("homeTestsHeading");
  const box = $("homeTestList");
  if (!heading || !box) return;
  const tests = state.tests || [];
  heading.hidden = tests.length === 0;
  box.textContent = "";

  const packages = [];
  const pkgMap = new Map();
  tests.forEach(t => {
    let p = pkgMap.get(t.package_id);
    if (!p) {
      p = { id: t.package_id, title: t.package_title || "Bộ đề", tests: [] };
      pkgMap.set(t.package_id, p);
      packages.push(p);
    }
    p.tests.push(t);
  });

  packages.forEach(pkg => {
    const row = document.createElement("a");
    row.className = "stream-row test-package-row";
    row.href = "#tests=" + encodeURIComponent(pkg.id);

    const info = document.createElement("div");
    info.className = "test-package-info";

    const title = document.createElement("h3");
    title.className = "test-group-title";
    title.textContent = pkg.title;

    const meta = document.createElement("div");
    meta.className = "test-package-meta";

    const parts = [`${pkg.tests.length} đề`];
    const bests = pkg.tests.map(t => t.best_percent).filter(v => v !== null && v !== undefined);
    if (bests.length > 0) {
      parts.push(`Điểm cao nhất ${Math.max(...bests)}%`);
    }
    const poolSum = pkg.tests.reduce((sum, t) => sum + (t.pool || 0), 0);
    if (poolSum > 0) {
      parts.push(`Chờ ôn ${poolSum} câu`);
    }
    meta.textContent = parts.join(" · ");

    info.append(title, meta);

    const chev = document.createElement("span");
    chev.className = "lesson-row-chevron";
    chev.setAttribute("aria-hidden", "true");
    chev.textContent = "›";

    row.append(info, chev);
    box.append(row);
  });
}

function renderList() {
  const box = $("lessonList");
  box.textContent = "";
  const total = state.lessons.length;
  state.lessons.forEach((l, i) => {
    const row = document.createElement("div");
    row.className = "stream-row lesson-row";
    const isCurrent = state.lesson && l.id === state.lesson.id;
    if (isCurrent) row.classList.add("is-current");
    if (total > 8 && i >= 8 && !isCurrent) {
      row.hidden = true;
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lesson-row-main";
    btn.dataset.act = "start";
    btn.dataset.lesson = l.id;

    const idx = document.createElement("span");
    idx.className = "stream-index lesson-row-idx";
    idx.textContent = String(l.order).padStart(2, "0");

    const text = document.createElement("div");
    text.className = "lesson-row-text";

    const title = document.createElement("span");
    title.className = "lesson-row-title";
    title.textContent = `${lessonNo(l)}: ${l.title}`;

    const status = document.createElement("span");
    status.className = "lesson-row-status" + (l.status === "done" ? " is-done" : "");
    status.textContent = l.mine ? statusText(l) : `${statusText(l)}. Tác giả: ${l.author}`;

    text.append(title, status);

    const chev = document.createElement("span");
    chev.className = "lesson-row-chevron";
    chev.setAttribute("aria-hidden", "true");
    chev.textContent = "›";

    btn.append(idx, text, chev);

    const read = document.createElement("a");
    read.className = "lesson-row-read";
    read.href = l.page;
    read.textContent = "Đọc bài";

    row.append(btn, read);
    box.append(row);
  });

  if (total > 8) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "btn-link-quiet lesson-expand-btn";
    moreBtn.textContent = `Xem tất cả ${total} bài`;
    moreBtn.addEventListener("click", () => {
      box.querySelectorAll(".lesson-row[hidden]").forEach(r => r.removeAttribute("hidden"));
      moreBtn.remove();
    });
    box.append(moreBtn);
  }

  renderHomeTests();
  const dueText = state.due ? `Còn ${state.due} thẻ đến hạn` : "Không có thẻ đến hạn";
  $$("[data-due-text]").forEach(e => { e.textContent = dueText; });
  $$("[data-due-short]").forEach(e => { e.textContent = state.due ? `${state.due} thẻ` : ""; });
}

function renderTrackButtons() {
  const t = state.lesson ? state.lesson.tracks : {};
  $$("[data-track]").forEach(b => {
    const k = b.dataset.track, tr = t[k];
    b.hidden = !tr;
    if (!tr) return;
    b.setAttribute("aria-pressed", String(k === state.track));
    b.textContent = "";
    if (b.classList.contains("track-big")) {
      const a = document.createElement("div");
      a.className = "track-name";
      a.textContent = `${tr.label}, ${fmt(tr.duration)}`;
      const s = document.createElement("div");
      s.className = "track-saved";
      s.textContent = tr.position ? `Đang dừng ở ${fmt(tr.position)}` : "Chưa nghe";
      b.append(a, s);
    } else {
      b.textContent = `${tr.label} (${fmt(tr.duration)})`;
    }
  });
}

function renderTime() {
  const t = currentTrack();
  if (!t) {
    $$('[data-time="now"]').forEach(e => { e.textContent = "0:00"; });
    $$('[data-time="total"]').forEach(e => { e.textContent = "0:00"; });
    $("dockNote").textContent = "";
    $("miniLabel").textContent = "";
    renderBars(0);
    return;
  }
  const pos = pendingSeek ?? (audio.src ? audio.currentTime : t.position);
  $$('[data-time="now"]').forEach(e => { e.textContent = fmt(pos); });
  $$('[data-time="total"]').forEach(e => { e.textContent = fmt(t.duration); });
  $$("[data-scrub]").forEach(r => {
    r.max = Math.round(t.duration);
    if (document.activeElement !== r || !r.matches(":active")) r.value = Math.round(pos);
  });
  $("dockNote").textContent = pos ? `Đang dừng ở ${fmt(pos)} của ${t.label.toLowerCase()}` : "Cần có mạng để nghe";
  $("miniLabel").textContent = `${t.label}, ${fmt(pos)}`;
  renderBars(pos / (t.duration || 1));
}

const BARS = [35, 60, 45, 80, 55, 90, 70, 40, 75, 50, 85, 65, 30, 60, 45, 55];
function renderBars(ratio) {
  const box = $("dockBars");
  if (!box.children.length) BARS.forEach(h => {
    const s = document.createElement("span");
    s.className = "s-bar";
    s.style.height = h + "%";
    box.append(s);
  });
  [...box.children].forEach((s, i) => s.classList.toggle("played", i / BARS.length < ratio));
}

function renderPlay() {
  const playing = !audio.paused;
  $$("[data-play-label]").forEach(b => { b.textContent = playing ? "Dừng" : "Phát"; });
}

// ---------- Podcast ----------
function loadTrack() {
  const t = currentTrack();
  if (!t) return;
  const url = new URL(t.url, location.href).href;
  if (audio.src !== url) {
    audio.src = url;
    pendingSeek = t.position || 0;
  }
  renderTime();
}
audio.addEventListener("loadedmetadata", () => {
  if (pendingSeek !== null) { audio.currentTime = pendingSeek; pendingSeek = null; }
  audio.playbackRate = SPEEDS[speedIndex()];
  renderTime();
});
audio.addEventListener("timeupdate", () => {
  const t = currentTrack();
  if (pendingSeek === null && t) t.position = audio.currentTime;
  renderTime();
  if (Date.now() - lastSaved > 10000) savePosition();
});
["play", "pause"].forEach(ev => audio.addEventListener(ev, () => {
  renderPlay();
  if (ev === "pause") savePosition();
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
}));
audio.addEventListener("ended", savePosition);
// The phone's mini player appears once audio has started; before that, Listen has the only play button it needs.
audio.addEventListener("play", () => document.body.classList.add("audio-started"));
["ended", "emptied"].forEach(ev => audio.addEventListener(ev, () => document.body.classList.remove("audio-started")));

// Phones: the tab bar steps aside while reading down, and returns on the way up or at the end of the page.
let lastScrollY = 0;
window.addEventListener("scroll", () => {
  const y = window.scrollY;
  if (Math.abs(y - lastScrollY) < 8) return;
  const atEnd = y + window.innerHeight >= document.documentElement.scrollHeight - 8;
  document.body.classList.toggle("bars-away", y > lastScrollY && y > 80 && !atEnd);
  lastScrollY = y;
}, { passive: true });
audio.addEventListener("error", () => { if (audio.src) { $("audioError").hidden = false; go("listen"); } });
audio.addEventListener("playing", () => { $("audioError").hidden = true; });

function savePosition(keepalive) {
  if (!state.lesson || !audio.src || pendingSeek !== null) return;
  lastSaved = Date.now();
  const body = { episode: `${state.lesson.id}:${state.track}`, seconds: audio.currentTime };
  fetch("/api/listen", send("PUT", body, keepalive === true ? { keepalive: true } : {})).catch(() => {});
}
document.addEventListener("visibilitychange", () => { if (document.hidden) savePosition(true); });
window.addEventListener("pagehide", () => savePosition(true));

function togglePlay() {
  loadTrack();
  if (audio.paused) {
    setupMediaSession();
    audio.play().catch(() => { $("audioError").hidden = false; });
  } else audio.pause();
}
function seekBy(sec) {
  loadTrack();
  const t = currentTrack();
  if (!t) return;
  if (pendingSeek !== null) pendingSeek = Math.max(0, pendingSeek + sec);
  else audio.currentTime = Math.max(0, Math.min(t.duration, audio.currentTime + sec));
  t.position = pendingSeek ?? audio.currentTime;
  renderTime();
  savePosition();
}
function switchTrack(key) {
  if (!state.lesson || key === state.track || !state.lesson.tracks[key]) return;
  const wasPlaying = !audio.paused;
  audio.pause();
  savePosition();
  state.track = key;
  loadTrack();
  renderTrackButtons();
  if (wasPlaying) audio.play().catch(() => {});
}
function speedIndex() {
  let v = 1;
  try { v = +localStorage.getItem("speed") || 1; } catch (e) { /* storage blocked */ }
  const i = SPEEDS.indexOf(v);
  return i < 0 ? 0 : i;
}
function renderSpeed() {
  const v = SPEEDS[speedIndex()];
  audio.playbackRate = v;
  $$("[data-speed-label]").forEach(b => { b.textContent = String(v).replace(".", ",") + "x"; });
}
function cycleSpeed() {
  try { localStorage.setItem("speed", SPEEDS[(speedIndex() + 1) % SPEEDS.length]); } catch (e) { /* storage blocked */ }
  renderSpeed();
}
function setupMediaSession() {
  if (!("mediaSession" in navigator) || !state.lesson) return;
  navigator.mediaSession.metadata = new MediaMetadata({ title: state.lesson.title, artist: "Học AI", album: lessonNo(state.lesson) });
  navigator.mediaSession.setActionHandler("play", () => audio.play());
  navigator.mediaSession.setActionHandler("pause", () => audio.pause());
  navigator.mediaSession.setActionHandler("seekbackward", () => seekBy(-15));
  navigator.mediaSession.setActionHandler("seekforward", () => seekBy(15));
}

// ---------- Flashcards ----------
async function loadCards() {
  $("fcCard").hidden = true;
  $("fcEmpty").hidden = true;
  try {
    state.cards = (await api("/api/cards/due")).cards;
  } catch (e) {
    if (e.message === "login" || e.message === "password") return;
    state.cards = [];
  }
  state.idx = 0;
  renderCard();
}
function renderCard() {
  const c = state.cards[state.idx];
  $("fcEmpty").hidden = !!c;
  $("fcCard").hidden = !c;
  $("fcIndex").textContent = c ? `Thẻ ${state.idx + 1} / ${state.cards.length}` : "";
  if (!c) return;
  $("fcBadge").textContent = c.wrong ? `Câu từng làm sai, Bài ${c.lesson_order}` : `Bài ${c.lesson_order}`;
  $("fcQuestion").textContent = c.q;
  $("fcAnswer").textContent = c.a;
  $("fcAnswerPane").hidden = true;
  $("fcReveal").hidden = false;
}
function revealCard() {
  if (!state.cards[state.idx]) return;
  $("fcAnswerPane").hidden = false;
  $("fcReveal").hidden = true;
}
async function rateCard(r) {
  const c = state.cards[state.idx];
  if (!c || $("fcAnswerPane").hidden) return;
  $$(".btn-rate").forEach(b => { b.disabled = true; });
  try {
    await api(`/api/cards/${encodeURIComponent(c.id)}/review`, send("POST", { rating: r }));
    state.reviewed++;
    state.idx++;
    if (state.idx >= state.cards.length) finish();
    else renderCard();
  } catch (e) {
    $("fcBadge").textContent = "Chưa lưu được. Chấm lại nhé.";
  }
  $$(".btn-rate").forEach(b => { b.disabled = false; });
}
async function finish() {
  if (state.lesson) await api(`/api/lessons/${state.lesson.id}/finish`, send("POST")).catch(() => {});
  await refresh();
  const parts = [];
  if (state.reviewed) parts.push(`Bạn đã ôn ${state.reviewed} thẻ.`);
  if (state.nextDue) parts.push(`Lần ôn tiếp theo: ${new Date(state.nextDue * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}.`);
  $("finishNote").textContent = parts.join(" ") || "Đã hoàn tất buổi học.";
  state.reviewed = 0;
  go("finish");
}

// ---------- Ask box ----------
// Suggestions already asked in this visit, as "lesson\nquestion": go() re-renders the chips on every screen change.
// ponytail: forgotten on reload; filter against the saved thread if learners notice.
const askedChips = new Set();

function renderChipsForLesson(l) {
  const chips = $("askChips");
  if (!chips) return;
  chips.textContent = "";
  const left = l && Array.isArray(l.suggest) ? l.suggest.filter(q => !askedChips.has(l.id + "\n" + q.trim())) : [];
  if (!left.length) {
    chips.hidden = true;
    return;
  }
  left.forEach(q => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "prompt-chip";
    b.dataset.act = "ask-chip";
    b.textContent = q;
    chips.append(b);
  });
  chips.hidden = false;
}

function removeChipIfAsked(question) {
  const chips = $("askChips");
  if (!chips) return;
  const chip = [...chips.querySelectorAll(".prompt-chip")].find(c => c.textContent.trim() === question.trim());
  if (chip) {
    chip.remove();
  }
  if (!chips.querySelector(".prompt-chip")) {
    chips.hidden = true;
  }
}

function askBubble(cls) {
  const b = document.createElement("div");
  b.className = "ask-bubble " + cls;
  $("askThread").append(b);
  $("askClear").hidden = false;
  return b;
}

async function sendAsk(question) {
  question = question.trim();
  if (!question || $("askInput").disabled || AskThread.sending) return;
  removeChipIfAsked(question);
  const isLesson = document.body.classList.contains("in-lesson");
  const targetLessonId = isLesson ? (state.lesson ? state.lesson.id : null) : askLessonId;
  if (!targetLessonId) return;
  askedChips.add(targetLessonId + "\n" + question);

  const qEl = askBubble("is-question");
  qEl.textContent = question;
  $("askInput").value = "";
  const out = askBubble("md-answer is-pending");
  out.textContent = "Đang trả lời...";
  $("askSend").disabled = true;
  AskThread.sending = true;
  $("askLessonPick").disabled = true;
  AskThread.scrollTo(qEl);
  try {
    const d = await api("/api/ask", send("POST", { lesson: targetLessonId, question }));
    AskThread.saved += 2;
    out.classList.remove("is-pending");
    out.innerHTML = renderAnswer(d.text);
    if (window.MathJax && MathJax.typesetPromise) await MathJax.typesetPromise([out]).catch(() => {});
  } catch (e) {
    out.classList.remove("is-pending");
    out.textContent = e.message;
    out.classList.add("is-error");
    // It was not kept, so the learner should not have to type it again.
    if (!$("askInput").value) $("askInput").value = question;
  }
  AskThread.sending = false;
  $("askLessonPick").disabled = false;
  $("askSend").disabled = false;
}

$("askForm").addEventListener("submit", e => { e.preventDefault(); sendAsk($("askInput").value); });
$("askInput").addEventListener("keydown", e => {
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    const isPhone = window.matchMedia("(max-width: 1023px)").matches;
    const isOverlay = !document.body.classList.contains("in-lesson");
    if (isPhone || isOverlay) {
      openAsk(false);
    }
    return;
  }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendAsk(e.target.value); }
});

const askPick = $("askLessonPick");
if (askPick) {
  askPick.addEventListener("change", e => {
    askLessonId = e.target.value;
    const currentL = state.lessons.find(l => l.id === askLessonId);
    const askOn = !!(currentL && currentL.ask);
    $("askInput").disabled = !askOn;
    $("askSend").disabled = !askOn;
    $("askInput").placeholder = askOn ? "Hỏi về bài này" : "Ô Hỏi chưa được bật.";
    renderChipsForLesson(currentL);
    AskThread.sync(askOn ? askLessonId : null, api).catch(() => {});
  });
}

// ---------- Actions ----------
function setLesson(id) {
  const l = state.lessons.find(x => x.id === id);
  if (!l || l === state.lesson) return;
  audio.pause();
  savePosition();
  audio.removeAttribute("src");
  pendingSeek = null;
  state.lesson = l;
  state.track = l.track in l.tracks ? l.track : (Object.keys(l.tracks)[0] || null);
  renderLesson();
  syncAsk();
}
async function startLesson(id) {
  if (id) setLesson(id);
  if (!state.lesson) return;
  await api(`/api/lessons/${state.lesson.id}/start`, send("POST"));
  await refresh();
  go("review");
}
function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) { /* storage blocked */ }
  renderThemeLabel();
}
function renderThemeLabel() {
  const label = document.documentElement.getAttribute("data-theme") === "dark" ? "Nền Sáng" : "Nền Tối";
  $$("[data-theme-label]").forEach(b => { b.textContent = label; });
}
async function logout() {
  audio.pause();
  savePosition();
  await fetch("/logout", send("POST")).catch(() => {});
  try {
    const theme = localStorage.getItem("theme");
    localStorage.clear();  // lesson pages keep notes here, and the next person on this browser must not see them
    if (theme) localStorage.setItem("theme", theme);
  } catch (e) { /* storage blocked */ }
  location.href = "/login";
}

const ACTIONS = {
  go: el => go(el.dataset.to),
  start: el => startLesson(el.dataset.lesson),
  finish: finish,
  play: togglePlay,
  seek: el => seekBy(+el.dataset.by),
  speed: cycleSpeed,
  track: el => switchTrack(el.dataset.track),
  reveal: revealCard,
  rate: el => rateCard(+el.dataset.r),
  theme: toggleTheme,
  logout: logout,
  "fb-card": () => {
    const c = state.cards[state.idx];
    if (c) openFeedback({ lesson: c.lesson, targetType: c.target_type, targetId: c.target_id, kind: "wrong", label: c.q });
  },
  "nav-open": () => { openAsk(false); $("navDrawer").classList.add("open"); $("navBackdrop").classList.add("open"); },
  "nav-close": closeNav,
  "ask-open": () => openAsk(true),
  "ask-close": () => openAsk(false),
  "ask-clear": () => AskThread.clear(api).catch(e => { askBubble("is-error").textContent = e.message; }),
  "ask-chip": el => { openAsk(true); sendAsk(el.textContent); },
  "ask-expand": el => {
    const on = !$("workbenchGrid").classList.contains("ask-expanded");
    $("workbenchGrid").classList.toggle("ask-expanded", on);
    $("askDock").classList.toggle("mobile-expanded", on);
    el.setAttribute("aria-expanded", String(on));
    el.textContent = on ? "Thu gọn" : "Mở rộng";
  }
};
document.addEventListener("click", e => {
  const menu = $("accountMenu");
  if (menu && menu.hasAttribute("open")) {
    if (e.target.closest(".account-menu-panel") || !e.target.closest(".account-menu")) {
      menu.removeAttribute("open");
    }
  }
  const el = e.target.closest("[data-act]");
  if (!el) return;
  if (el.tagName === "A") e.preventDefault();
  Promise.resolve(ACTIONS[el.dataset.act](el)).catch(err => { if (err && err.name !== "AbortError" && err.message !== "login" && err.message !== "password") console.error(err); });
});
document.addEventListener("input", e => {
  if (!e.target.matches("[data-scrub]")) return;
  loadTrack();
  const v = +e.target.value;
  if (pendingSeek !== null) pendingSeek = v;
  else audio.currentTime = v;
  currentTrack().position = v;
  renderTime();
});
document.addEventListener("change", e => { if (e.target.matches("[data-scrub]")) savePosition(); });
document.querySelector("[data-article]") && $$("[data-article]").forEach(a => a.addEventListener("click", () => { audio.pause(); savePosition(true); closeNav(); }));
$("navDrawer") && $("navDrawer").addEventListener("click", e => { if (e.target.closest("a")) closeNav(); });

document.addEventListener("keydown", e => {
  if (e.target.matches("input:not([type=range]),textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "Escape") {
    closeNav();
    openAsk(false);
    const menu = $("accountMenu");
    if (menu) menu.removeAttribute("open");
    return;
  }
  const on = $$(".screen.active")[0];
  if (!on) return;
  if (on.id === "screen-listen") {
    if (e.code === "Space" && e.target.tagName !== "BUTTON") { e.preventDefault(); togglePlay(); }
    if (e.target.type !== "range") {
      if (e.key === "ArrowLeft") seekBy(-15);
      if (e.key === "ArrowRight") seekBy(15);
    }
  }
  if (on.id === "screen-flashcard") {
    if (e.code === "Space" && !$("fcCard").hidden && $("fcAnswerPane").hidden && e.target.tagName !== "BUTTON") { e.preventDefault(); revealCard(); }
    if ("1234".includes(e.key) && e.key.length === 1) rateCard(+e.key);
  }
});

// ---------- Start ----------
async function refresh() {
  const [d, tData] = await Promise.all([
    api("/api/lessons"),
    api("/api/tests").catch(() => ({ tests: [] }))
  ]);
  state.tests = tData.tests || [];
  const current = state.lesson && state.lesson.id;
  const heard = state.lesson ? state.lesson.tracks : null;
  state.lessons = d.lessons;
  state.due = d.due_total;
  state.nextDue = d.next_due;
  const again = d.lessons.find(x => x.id === current);
  if (current && !again) {  // deleted, or access was taken away
    audio.pause();
    audio.removeAttribute("src");
    pendingSeek = null;
  }
  state.lesson = again || d.lessons.find(x => x.status === "in_progress") || d.lessons.find(x => x.status === "new") || d.lessons[0] || null;
  if (state.lesson && !again) state.track = state.lesson.track in state.lesson.tracks ? state.lesson.track : (Object.keys(state.lesson.tracks)[0] || null);
  if (again && heard && audio.src && state.track && again.tracks[state.track]) {
    again.tracks[state.track].position = heard[state.track].position;
  }
  renderLesson();
  renderList();
  syncAsk();
}
function syncAsk() {
  const isLesson = document.body.classList.contains("in-lesson");
  const askLessonPick = $("askLessonPick");
  const askLessonShort = $("askLessonShort");
  const askContextText = $("askContextText");
  const askNoLessons = $("askNoLessons");

  if (isLesson) {
    askLessonId = state.lesson ? state.lesson.id : null;
    const askOn = !!(state.lesson && state.lesson.ask);
    document.body.classList.toggle("no-ask", !askOn);
    $("askInput").disabled = !askOn;
    $("askSend").disabled = !askOn;
    $("askInput").placeholder = askOn ? "Hỏi về bài này" : "Ô Hỏi chưa được bật.";
    if (askContextText) askContextText.hidden = false;
    if (askNoLessons) askNoLessons.hidden = true;
    if (askLessonShort) {
      askLessonShort.hidden = false;
      askLessonShort.textContent = state.lesson ? lessonNo(state.lesson) : "";
    }
    if (askLessonPick) askLessonPick.hidden = true;
    renderChipsForLesson(state.lesson);
    AskThread.sync(askOn ? askLessonId : null, api).catch(() => {});
  } else {
    const askable = (state.lessons || []).filter(l => l.ask);
    const hasAnyAsk = askable.length > 0;
    document.body.classList.toggle("no-ask", !hasAnyAsk);
    if (!hasAnyAsk) {
      askLessonId = null;
      if (askContextText) askContextText.hidden = true;
      if (askNoLessons) askNoLessons.hidden = false;
      $("askInput").disabled = true;
      $("askSend").disabled = true;
      $("askInput").placeholder = "Chưa có bài nào bật Ô Hỏi.";
      if ($("askChips")) $("askChips").textContent = "";
      AskThread.sync(null, api).catch(() => {});
    } else {
      if (askContextText) askContextText.hidden = false;
      if (askNoLessons) askNoLessons.hidden = true;
      if (askLessonShort) askLessonShort.hidden = true;
      if (askLessonPick) {
        askLessonPick.hidden = false;
        if (!askable.some(l => l.id === askLessonId)) {
          askLessonId = (state.lesson && state.lesson.ask ? state.lesson : askable[0]).id;
        }
        askLessonPick.innerHTML = "";
        state.lessons.forEach(l => {
          const opt = document.createElement("option");
          opt.value = l.id;
          opt.textContent = l.ask ? `${lessonNo(l)}: ${l.title}` : `${lessonNo(l)}: ${l.title} (chưa bật Ô Hỏi)`;
          opt.disabled = !l.ask;
          if (l.id === askLessonId) opt.selected = true;
          askLessonPick.append(opt);
        });
        askLessonPick.value = askLessonId;
      }
      const currentL = state.lessons.find(l => l.id === askLessonId);
      const askOn = !!(currentL && currentL.ask);
      $("askInput").disabled = !askOn;
      $("askSend").disabled = !askOn;
      $("askInput").placeholder = askOn ? "Hỏi về bài này" : "Ô Hỏi chưa được bật.";
      renderChipsForLesson(currentL);
      AskThread.sync(askOn ? askLessonId : null, api).catch(() => {});
    }
  }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) syncAsk(); });
window.addEventListener("pageshow", e => { if (e.persisted) syncAsk(); });
// A share link arrives as #join=<token>: the fragment stays out of server logs and survives the login redirects.
function joinFromLink() {
  const m = location.hash.match(/^#join=([\w.-]+)$/);
  if (!m) return false;
  history.replaceState(null, "", "#home");
  api("/api/join", send("POST", { token: m[1], preview: true })).then(async p => {
    if (!p.mine && !confirm(`Tác giả ${p.author} share bài này:\n${p.title.replace(/\s+/g, " ")}\n\nThêm vào thư viện?`)) return;
    const d = await api("/api/join", send("POST", { token: m[1] }));
    if (d.first_lesson) location.replace("/lesson/" + d.first_lesson);
    else location.hash = "#tests=" + d.package_id;
  }).catch(e => {
    if (e.message === "login" || e.message === "password") return;
    $("homeAlert").textContent = e.message;
    $("homeAlert").hidden = false;
    go("home", true);
  });
  return true;
}
// After DOMContentLoaded, so library.js has run and its screen can open straight away.
document.addEventListener("DOMContentLoaded", () => (async function init() {
  state.me = await api("/api/me");
  const isAdmin = !!(state.me && state.me.admin);
  document.querySelectorAll("[data-admin-link]").forEach(a => a.hidden = !isAdmin);
  renderSpeed();
  renderThemeLabel();
  joinFromLink();
  await refresh();
  if (!(window.testRoute && window.testRoute())) go(location.hash.slice(1) || "home", true);
})().catch(err => { if (err.name !== "AbortError" && err.message !== "login" && err.message !== "password") console.error(err); }));
