"use strict";
// Shared answer renderer used by app.js and lesson-host.js.
function renderAnswer(text) {
  const keep = [];
  const src = text.replace(/\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)/g, m => { keep.push(m); return `@@M${keep.length - 1}@@`; });
  const escape = t => t.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  return DOMPurify.sanitize(marked.parse(src), { FORBID_TAGS: ["style", "img", "form", "input", "button", "textarea", "select"], FORBID_ATTR: ["style"] }).replace(/@@M(\d+)@@/g, (_, i) => escape(keep[+i] || ""));
}

// The learner's thread for one lesson, the same one on the app page and the lesson page.
const AskThread = {
  lesson: null,
  saved: -1,
  sending: false,

  el() { return document.getElementById("askThread"); },

  // Moves only the panel: scrollIntoView would also scroll the app page behind it.
  showEnd() {
    const last = this.el().lastElementChild;
    const dock = document.getElementById("askDock");
    if (last) dock.scrollTop += last.getBoundingClientRect().top - dock.getBoundingClientRect().top - 16;
    document.getElementById("askClear").hidden = !last;
  },

  // Called again when the page returns to view, since the other page may have added to the thread.
  async sync(lesson, api) {
    if (lesson !== this.lesson) {
      this.lesson = lesson;
      this.saved = -1;
      this.el().textContent = "";
      this.showEnd();
    }
    if (!lesson || this.sending) return;
    const { messages } = await api(`/api/lessons/${lesson}/ask`, { method: "GET" });
    if (lesson !== this.lesson || this.sending || messages.length === this.saved) return;
    this.saved = messages.length;
    const bubbles = messages.map(m => {
      const b = document.createElement("div");
      if (m.role === "user") {
        b.className = "ask-bubble is-question";
        b.textContent = m.text;
      } else {
        b.className = "ask-bubble md-answer";
        b.innerHTML = renderAnswer(m.text);
      }
      return b;
    });
    this.el().replaceChildren(...bubbles);
    this.showEnd();
    if (window.MathJax && MathJax.startup) {
      await MathJax.startup.promise;
      await MathJax.typesetPromise(bubbles).catch(() => {});
      this.showEnd();
    }
  },

  async clear(api) {
    if (!confirm("Xóa toàn bộ câu hỏi của bạn trong bài này?")) return;
    await api(`/api/lessons/${this.lesson}/ask`, { method: "DELETE" });
    this.saved = 0;
    this.el().textContent = "";
    this.showEnd();
  },
};
