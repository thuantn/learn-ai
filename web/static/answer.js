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

  scroller() {
    return document.getElementById("askScroll") || (this.el() ? this.el().closest(".ask-dock-scroll") : null) || (this.el() ? this.el().parentElement : null);
  },

  // Puts target at the top of the scroller. Right after a question is sent, only "Đang trả lời..." sits below it,
  // so the thread gets bottom room until the answer is long enough; otherwise the question stays near the bottom.
  scrollTo(target) {
    const s = this.scroller();
    if (!target || !s) return;
    const t = this.el();
    if (t) t.style.paddingBottom = "";
    const top = target.getBoundingClientRect().top;
    const offset = top - s.getBoundingClientRect().top + s.scrollTop;
    // Measured from the thread, not scrollHeight: scrollHeight never drops below clientHeight, so a short thread looked long enough.
    const lack = t ? s.clientHeight - (t.getBoundingClientRect().bottom - top) : 0;
    if (lack > 0) t.style.paddingBottom = lack + "px";
    s.scrollTop = offset;
  },
  // Moves only the panel: scrolls so the last question is at the top of the middle scroller.
  showEnd() {
    if (!this.el()) return;
    const questions = this.el().querySelectorAll(".is-question");
    const target = questions.length ? questions[questions.length - 1] : this.el().lastElementChild;
    this.scrollTo(target);
    const clearBtn = document.getElementById("askClear");
    if (clearBtn) clearBtn.hidden = !this.el().lastElementChild;
  },

  // Called again when the page returns to view, since the other page may have added to the thread.
  async sync(lesson, api) {
    if (lesson !== this.lesson) {
      this.lesson = lesson;
      this.saved = -1;
      if (this.el()) this.el().textContent = "";
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
    if (this.el()) {
      this.el().replaceChildren(...bubbles);
      this.showEnd();
      if (window.MathJax && MathJax.startup) {
        await MathJax.startup.promise;
        await MathJax.typesetPromise(bubbles).catch(() => {});
        this.showEnd();
      }
    }
  },

  async clear(api) {
    if (!confirm("Xóa toàn bộ câu hỏi của bạn trong bài này?")) return;
    await api(`/api/lessons/${this.lesson}/ask`, { method: "DELETE" });
    this.saved = 0;
    if (this.el()) this.el().textContent = "";
    this.showEnd();
  },
};
