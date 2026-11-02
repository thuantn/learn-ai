"use strict";
// Shared answer renderer used by app.js and lesson-host.js.
function renderAnswer(text) {
  const keep = [];
  const src = text.replace(/\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)/g, m => { keep.push(m); return `@@M${keep.length - 1}@@`; });
  const escape = t => t.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  return DOMPurify.sanitize(marked.parse(src), { FORBID_TAGS: ["img", "form", "input", "button", "textarea", "select"], FORBID_ATTR: ["style"] }).replace(/@@M(\d+)@@/g, (_, i) => escape(keep[+i] || ""));
}
