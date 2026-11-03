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
    tests.forEach(t => {
      const row = el("article", "stream-row");
      const info = el("div", "lib-info");
      info.append(el("h3", "stream-title", t.title));
      const pills = el("div", "meta-pills");
      [
        `${t.items} câu`,
        t.minutes ? `${t.minutes} phút` : "Không giới hạn giờ",
        `Điểm đạt: ${t.pass_percent}%`,
        t.best_percent !== null && t.best_percent !== undefined ? `Điểm cao nhất: ${t.best_percent}%` : null,
        t.pool ? `Chờ ôn: ${t.pool} câu` : null,
      ].filter(Boolean).forEach(txt => pills.append(el("span", "meta-pill", txt)));
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
      [
        `${t.items} câu`,
        t.minutes ? `${t.minutes} phút` : "Không giới hạn giờ",
        `Điểm đạt: ${t.pass_percent}%`,
        t.best_percent !== null && t.best_percent !== undefined ? `Điểm cao nhất: ${t.best_percent}%` : null,
        t.pool ? `Chờ ôn: ${t.pool} câu` : null,
      ].filter(Boolean).forEach(txt => pills.append(el("span", "meta-pill", txt)));
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

function showTestRun(attemptId) {
  go("test-run", true, "#attempt=" + encodeURIComponent(attemptId));
  const s = $("screen-test-run");
  if (s) {
    s.textContent = "";
    s.append(el("p", "dock-note", `Đang tải lượt làm bài (${attemptId})...`));
  }
}

function showTestResult(attemptId) {
  go("test-result", true, "#result=" + encodeURIComponent(attemptId));
  const s = $("screen-test-result");
  if (s) {
    s.textContent = "";
    s.append(el("p", "dock-note", `Đang tải kết quả (${attemptId})...`));
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
  }
});

window.testRoute = testRoute;
window.renderTestText = renderTestText;
window.testPrompt = testPrompt;
window.copyTestPrompt = copyTestPrompt;
window.parseTestJson = parseTestJson;
window.mergeTestFiles = mergeTestFiles;
