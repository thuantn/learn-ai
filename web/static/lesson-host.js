"use strict";
(function () {
  const $ = id => document.getElementById(id);
  const $$ = sel => [...document.querySelectorAll(sel)];

  const lessonId = (location.pathname.match(/^\/lesson\/(p[0-9a-f]{12}\.[a-z0-9-]+)$/) || [])[1];
  let frameInfo = null;
  let iframe = null;
  // Every port handed to the current frame. A busy page can send a second hello before it gets the first port,
  // and closing the first one then dropped the calls already sent on it.
  let ports = [];
  let loadCount = 0;
  let docPending = null;
  let docTimer = null;
  let docWritePromise = null;
  let askOpen = false;
  let dialogOpen = false;
  let linkTimes = [];
  let askTimes = [];
  let aiEnabled = false;
  let lastQuizId = null;
  let barHeldUntil = 0;
  const narrow = window.matchMedia("(max-width: 1023px)");

  const send = (method, body, extra) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}), ...extra });

  async function api(url, opts) {
    const r = await fetch(url, opts);
    if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(d.error || "Có lỗi. Thử lại sau."); e.code = d.code; e.status = r.status; throw e; }
    return d;
  }

  // A page can ask for this too, for ever. So only on a phone, never over something to read, and the handle outside
  // the frame brings the bar back and holds it long enough to reach "Về app".
  function setBarHidden(hide) {
    const blocked = !narrow.matches || askOpen || dialogOpen || Date.now() < barHeldUntil
      || $("lessonNotice").textContent || $("lessonAskNotice").textContent || !$("lessonCover").hidden;
    document.body.classList.toggle("bar-hidden", hide && !blocked);
  }
  narrow.addEventListener("change", () => setBarHidden(false));

  function setNotice(text) {
    $("lessonNotice").textContent = text;
    if (text) setBarHidden(false);
  }

  let askNoticeTimer;
  function showAskNotice() {
    $("lessonAskNotice").textContent = "Bài này chưa bật ô Hỏi.";
    setBarHidden(false);
    clearTimeout(askNoticeTimer);
    askNoticeTimer = setTimeout(() => { $("lessonAskNotice").textContent = ""; }, 5000);
  }

  function setCover(text, actionBtn) {
    $("lessonCoverText").textContent = text;
    $("lessonReloadBtn").hidden = actionBtn !== "reload";
    $("lessonExpiredReloadBtn").hidden = actionBtn !== "expired";
    $("lessonCover").hidden = false;
    setBarHidden(false);
    if (iframe) {
      iframe.remove();
      iframe = null;
    }
    closePorts();
  }

  function lostAccess() {
    docPending = null;
    if (docTimer) { clearTimeout(docTimer); docTimer = null; }
    setNotice("");
    setCover("Bạn không còn quyền xem bài này. Có thể tác giả đã bỏ quyền hoặc đã xóa bài.", null);
  }

  function showLoading(text) {
    $("lessonLoading").textContent = text;
    $("lessonLoading").hidden = false;
    $("lessonFrameWrap").hidden = true;
    $("lessonCover").hidden = true;
  }

  function showFrame() {
    $("lessonLoading").hidden = true;
    $("lessonFrameWrap").hidden = false;
    $("lessonCover").hidden = true;
  }

  function checkExpired() {
    if (frameInfo && Date.now() / 1000 > frameInfo.expires) {
      setCover("Phiên xem bài đã hết hạn. Tải lại để học tiếp, tiến độ đã lưu không mất.", "expired");
      return true;
    }
    return false;
  }

  async function loadFrame() {
    showLoading("Đang mở bài…");
    loadCount = 0;
    if (iframe) {
      iframe.remove();
      iframe = null;
    }
    closePorts();
    try {
      const r = await fetch(`/api/lessons/${lessonId}/frame`, send("POST", { theme: document.documentElement.getAttribute("data-theme") }));
      if (r.status === 404) {
        setCover("Bài này chưa sẵn sàng ở chế độ mới.", null);
        return;
      }
      if (r.status === 401) { location.href = "/login"; return; }
      if (!r.ok) {
        setCover("Không mở được bài. Thử lại sau.", "reload");
        return;
      }
      frameInfo = await r.json();
      $("lessonTitle").textContent = frameInfo.title;
      const authorEl = $("lessonAuthor");
      if (authorEl) {
        const author = frameInfo.author || "";
        if (author && !frameInfo.mine) {
          authorEl.textContent = author.includes("@") ? author.split("@")[0] : author;
          authorEl.hidden = false;
        } else {
          authorEl.textContent = "";
          authorEl.hidden = true;
        }
      }
      $("askLessonShort").textContent = frameInfo.title;
      $("lessonAskBtn").hidden = !frameInfo.ask;
      document.body.classList.toggle("no-ask", !frameInfo.ask);
      aiEnabled = !!frameInfo.ask;
      $("askInput").disabled = !aiEnabled;
      $("askSend").disabled = !aiEnabled;
      $("askInput").placeholder = aiEnabled ? "Hỏi về bài này" : "Ô Hỏi chưa được bật.";
      createIframe(frameInfo.url, frameInfo.title);
      showFrame();
      syncThread();
    } catch (e) {
      if (e.message === "login") return;
      setCover("Không kết nối được. Thử lại sau.", "reload");
    }
  }

  function createIframe(url, title) {
    iframe = document.createElement("iframe");
    iframe.sandbox="allow-scripts";
    iframe.allow="";
    iframe.title = title;
    iframe.src = url;
    iframe.className = "lesson-iframe";
    $("lessonFrameWrap").textContent = "";
    $("lessonFrameWrap").append(iframe);
    iframe.addEventListener("load", onIframeLoad);
  }

  function onIframeLoad() {
    loadCount++;
    if (loadCount > 1) {
      setCover("Trang bài vừa cố chuyển sang địa chỉ khác nên đã bị đóng.", "reload");
      closePorts();
    }
  }

  window.addEventListener("message", function (event) {
    if (!iframe || event.source !== iframe.contentWindow) return;
    const msg = event.data;
    if (!msg || msg.type !== "learn-hello") return;
    const channel = new MessageChannel();
    ports.push(channel.port1);
    channel.port1.onmessage = onPortMessage;
    channel.port1.start();
    iframe.contentWindow.postMessage({ type: "learn-port" }, "*", [channel.port2]);
  });

  function closePorts() {
    ports.forEach(p => { try { p.close(); } catch (e) {} });
    ports = [];
  }

  // Answers on the port the call came in on, and only while that port still belongs to the current frame.
  function replyOn(from) {
    return (id, ok, rest) => {
      if (ports.includes(from)) from.postMessage({ id, ok, ...rest });
    };
  }

  function isPlainObject(v) {
    return v !== null && typeof v === "object" && Object.getPrototypeOf(v) === Object.prototype;
  }

  async function onPortMessage(event) {
    const reply = replyOn(event.target);
    const msg = event.data;
    if (msg === null || typeof msg !== "object") return;
    let raw;
    try { raw = JSON.stringify(msg); } catch (e) { return; }
    if (raw.length > 2 * 1024 * 1024) {
      if (typeof msg.id === "number") reply(msg.id, false, { code: "too_large", message: "Thông điệp quá lớn." });
      return;
    }
    if (typeof msg.id !== "number") return;
    const { id, op, args } = msg;
    const a = args || {};
    try {
      switch (op) {
        case "learner.id":
          reply(id, true, { data: frameInfo.learner });
          return;
        case "doc.get": {
          const d = await api(`/api/doc/${encodeURIComponent(frameInfo.doc)}`, { method: "GET" });
          reply(id, true, { data: d.data });
          return;
        }
        case "doc.set": {
          if (!isPlainObject(a.data)) {
            reply(id, false, { code: "input", message: "Dữ liệu không hợp lệ." });
            return;
          }
          docPending = a.data;
          reply(id, true, { data: null });
          scheduleDocWrite();
          return;
        }
        case "quiz.answer": {
          const d = await api(`/api/lessons/${lessonId}/quiz-answer`, send("POST", { id: a.id, option: a.option }));
          reply(id, true, { data: d });
          lastQuizId = String(a.id);
          $("lessonQuizWrongBtn").hidden = false;
          return;
        }
        case "ask.open": {
          // The learner must be able to see what they are about to send, so no long tails or runs of blank lines.
          const text = (typeof a.text === "string" ? a.text : "").replace(/\s*\n\s*\n\s*/g, "\n\n").slice(0, 800);
          if (!frameInfo.ask) {
            showAskNotice();
            reply(id, false, { code: "disabled", message: "Ô Hỏi chưa được bật cho bài này." });
            return;
          }
          // A hostile page could reopen the panel for ever, or swap the question just before the learner sends it.
          const now = Date.now();
          askTimes = askTimes.filter(t => now - t < 10000);
          if (askTimes.length < 3) {
            askTimes.push(now);
            openAsk(true);
            if (!$("askInput").value) $("askInput").value = text;
          }
          reply(id, true, { data: null });
          return;
        }
        case "link.open": {
          openLink(a.url);
          reply(id, true, { data: null });
          return;
        }
        case "bar.set": {
          setBarHidden(a.hidden === true);
          reply(id, true, { data: null });
          return;
        }
        case "media.error": {
          checkExpired();
          reply(id, true, { data: null });
          return;
        }
        case "page.ownAsk":
          $("lessonAskBtn").hidden = true;
          reply(id, true, { data: null });
          return;
        default:
          reply(id, false, { code: "unknown_op", message: "Không hỗ trợ thao tác này." });
      }
    } catch (e) {
      if (e.status === 404 && (op === "quiz.answer" || op === "doc.get")) lostAccess();
      reply(id, false, { code: e.code || "error", message: e.message || "Lỗi." });
    }
  }

  function scheduleDocWrite() {
    if (docTimer) return;
    docTimer = setTimeout(flushDoc, 2000);
  }

  async function flushDoc(keepalive) {
    if (docTimer) { clearTimeout(docTimer); docTimer = null; }
    if (docPending === null) return;
    if (docWritePromise) {
      await docWritePromise;
      if (docPending !== null) scheduleDocWrite();
      return;
    }
    const body = docPending;
    docPending = null;
    const opts = send("PUT", body);
    if (keepalive === true) opts.keepalive = true;
    const writePromise = fetch(`/api/doc/${encodeURIComponent(frameInfo.doc)}`, opts)
      .then(async r => {
        if (r.status === 404) { lostAccess(); return; }
        if (!r.ok) throw new Error("save failed");
        setNotice("");
      })
      .catch(() => {
        if (docPending === null) docPending = body;
        setNotice("Chưa lưu được, đang thử lại");
        scheduleDocWrite();
      })
      .finally(() => { docWritePromise = null; });
    docWritePromise = writePromise;
    await writePromise;
  }

  function bodySizeForKeepalive() {
    return docPending === null ? 0 : JSON.stringify(docPending).length;
  }

  async function flushDocBeforeLeave(keepalive) {
    if (docPending === null) return;
    if (keepalive && bodySizeForKeepalive() > 60 * 1024) return;
    await flushDoc(keepalive);
  }

  window.addEventListener("pagehide", () => flushDocBeforeLeave(true));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flushDocBeforeLeave(true);
    else {
      checkExpired();
      syncThread();
    }
  });

  function openLink(raw) {
    // A hostile page could reopen the modal for ever and lock the learner out of "Về app".
    const now = Date.now();
    linkTimes = linkTimes.filter(t => now - t < 10000);
    if (dialogOpen || linkTimes.length >= 3) return;
    linkTimes.push(now);
    let url;
    try { url = new URL(raw); } catch (e) { return; }
    const dialog = $("lessonDialog");
    const textEl = $("lessonDialogText");
    const okBtn = $("lessonDialogOk");
    if (url.protocol === "https:") {
      textEl.textContent = url.href;
      okBtn.hidden = false;
      dialogOpen = true;
      setBarHidden(false);
      dialog.showModal();
      dialog.addEventListener("close", function handler() {
        dialog.removeEventListener("close", handler);
        dialogOpen = false;
        if (dialog.returnValue === "ok") window.open(url.href, "_blank", "noopener,noreferrer");
      }, { once: true });
    } else {
      textEl.textContent = url.href + "\n\nĐịa chỉ này không an toàn nên app không mở. Bạn có thể tự chép nếu muốn.";
      okBtn.hidden = true;
      dialogOpen = true;
      dialog.showModal();
      dialog.addEventListener("close", function handler() {
        dialog.removeEventListener("close", handler);
        dialogOpen = false;
      }, { once: true });
    }
  }

  // ---------- Ask panel ----------
  function askBubble(cls) {
    const b = document.createElement("div");
    b.className = "ask-bubble " + cls;
    $("askThread").append(b);
    $("askClear").hidden = false;
    return b;
  }

  function syncThread() {
    AskThread.sync(aiEnabled ? lessonId : null, api).catch(() => {});
  }

  function openAsk(open) {
    askOpen = open;
    if (open) {
      setBarHidden(false);
      $("askDock").classList.toggle("mobile-open", true);
      $("askBackdrop").classList.toggle("open", true);
      if (!$("askInput").disabled) $("askInput").focus();
      AskThread.showEnd();
    } else {
      $("askDock").classList.remove("mobile-open");
      $("askBackdrop").classList.remove("open");
    }
  }

  async function sendAsk(question) {
    question = question.trim();
    if (!question || $("askInput").disabled || AskThread.sending) return;
    const qEl = askBubble("is-question");
    qEl.textContent = question;
    $("askInput").value = "";
    const out = askBubble("md-answer is-pending");
    out.textContent = "Đang trả lời…";
    $("askSend").disabled = true;
    AskThread.sending = true;
    AskThread.scrollTo(qEl);
    try {
      const d = await api("/api/ask", send("POST", { lesson: lessonId, question }));
      AskThread.saved += 2;
      out.classList.remove("is-pending");
      out.innerHTML = renderAnswer(d.text);
      if (window.MathJax && MathJax.typesetPromise) await MathJax.typesetPromise([out]).catch(() => {});
    } catch (e) {
      AskThread.sending = false;
      out.classList.remove("is-pending");
      if (e.status === 404) { lostAccess(); return; }
      out.textContent = e.message;
      out.classList.add("is-error");
      // It was not kept, so the learner should not have to type it again.
      if (!$("askInput").value) $("askInput").value = question;
    }
    AskThread.sending = false;
    $("askSend").disabled = false;
  }

  $("askForm").addEventListener("submit", e => { e.preventDefault(); sendAsk($("askInput").value); });
  $("askInput").addEventListener("keydown", e => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (narrow.matches) {
        openAsk(false);
      }
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendAsk(e.target.value); }
  });

  document.addEventListener("click", e => {
    const el = e.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    if (act === "ask-open") { openAsk(true); }
    else if (act === "bar-show") { barHeldUntil = Date.now() + 10000; setBarHidden(false); }
    else if (act === "ask-close") { openAsk(false); }
    else if (act === "ask-clear") {
      AskThread.clear(api).catch(e => {
        if (e.status === 404) lostAccess();
        else askBubble("is-error").textContent = e.message;
      });
    }
    else if (act === "ask-expand") {
      const on = !document.body.classList.contains("ask-expanded");
      document.body.classList.toggle("ask-expanded", on);
      $("askDock").classList.toggle("mobile-expanded", on);
      el.setAttribute("aria-expanded", String(on));
      el.textContent = on ? "Thu gọn" : "Mở rộng";
    }
    else if (act === "reload-frame") { loadFrame(); }
    else if (act === "feedback") { openFeedback({ lesson: lessonId, label: frameInfo ? frameInfo.title : "" }); }
    else if (act === "quiz-wrong") { openFeedback({ lesson: lessonId, targetType: "quiz", targetId: lastQuizId, kind: "wrong", label: `Câu ${lastQuizId}` }); }
    else if (act === "expired-reload") { flushDocBeforeLeave(false).finally(() => location.reload()); }
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") openAsk(false);
  });

  (async function init() {
    if (!lessonId) {
      setCover("Đường dẫn không hợp lệ.", null);
      return;
    }
    await loadFrame();
  })();
})();
