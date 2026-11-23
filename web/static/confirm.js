"use strict";
// One confirm dialog for the app and the admin page, in place of the browser's confirm() and prompt().
// askConfirm({ title, text, ok, danger, icon, field: { label, value, type, inputmode, check } }) resolves to
// false when cancelled, true when confirmed, or the trimmed field value. check(value) returns an error or "".
function askConfirm(o) {
  let d = document.getElementById("confirmDialog");
  if (!d) {
    d = document.createElement("dialog");
    d.className = "lesson-dialog";
    d.id = "confirmDialog";
    d.setAttribute("aria-labelledby", "confirmTitle");
    d.innerHTML = `<form class="lesson-dialog-form" novalidate>
      <h2 class="fc-title" id="confirmTitle"></h2>
      <p class="lesson-dialog-text" id="confirmText"></p>
      <div class="confirm-field" id="confirmField" hidden>
        <label class="auth-label" for="confirmInput"><span id="confirmLabel"></span></label>
        <div class="auth-input-box"><input class="auth-input" id="confirmInput" autocomplete="off" spellcheck="false"></div>
      </div>
      <p class="studio-alert error" id="confirmError" role="alert" hidden></p>
      <div class="lesson-dialog-buttons">
        <button type="button" class="btn-studio-secondary" data-confirm="cancel">Hủy</button>
        <button type="submit" class="btn-studio-primary" data-confirm="ok"></button>
      </div>
    </form>`;
    document.body.append(d);
  }
  // A second call while one is open (a fast double click) is treated as cancelled, so the first keeps its handlers.
  if (d.open) return Promise.resolve(false);
  const $c = id => document.getElementById(id);
  const okBtn = d.querySelector('[data-confirm="ok"]');
  const input = $c("confirmInput");
  $c("confirmTitle").textContent = o.title;
  $c("confirmText").textContent = o.text || "";
  $c("confirmText").hidden = !o.text;
  okBtn.textContent = o.ok || "Đồng ý";
  okBtn.className = "btn-studio-primary" + (o.danger ? " btn-danger-soft" : "");
  if (o.icon) okBtn.dataset.icon = o.icon; else delete okBtn.dataset.icon;
  $c("confirmField").hidden = !o.field;
  $c("confirmError").hidden = true;
  if (o.field) {
    $c("confirmLabel").textContent = o.field.label;
    input.type = o.field.type || "text";
    input.inputMode = o.field.inputmode || "";
    input.value = o.field.value || "";
  }
  return new Promise(resolve => {
    const form = d.querySelector("form");
    const done = value => {
      form.onsubmit = null;
      d.querySelector('[data-confirm="cancel"]').onclick = null;
      d.onclose = null;
      if (d.open) d.close();
      resolve(value);
    };
    form.onsubmit = e => {
      e.preventDefault();
      if (!o.field) return done(true);
      const value = input.value.trim();
      const problem = o.field.check ? o.field.check(value) : (value ? "" : "Cần nhập nội dung.");
      if (problem) {
        $c("confirmError").textContent = problem;
        $c("confirmError").hidden = false;
        input.focus();
        return;
      }
      done(value);
    };
    d.querySelector('[data-confirm="cancel"]').onclick = () => done(false);
    d.onclose = () => done(false);
    d.showModal();
    if (o.field) input.focus();
  });
}
