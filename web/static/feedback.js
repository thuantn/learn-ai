"use strict";
// Feedback form, shared by the app and the lesson page. Everything the author wrote goes in with textContent.
(function () {
  const KINDS = [["comment", "Góp ý"], ["wrong", "Báo sai"], ["abuse", "Báo vi phạm"]];
  let current = null;
  let kind = "comment";

  function build() {
    const dlg = document.createElement("dialog");
    dlg.className = "lesson-dialog";
    dlg.id = "feedbackDialog";
    dlg.setAttribute("aria-labelledby", "fbTitle");
    dlg.innerHTML = `
      <form class="lesson-dialog-form" id="fbForm">
        <div>
          <h2 class="fc-title" id="fbTitle">Góp ý cho bài học</h2>
          <p class="dock-note" id="fbTarget"></p>
        </div>
        <div class="type-group" role="group" aria-label="Loại góp ý" id="fbKinds"></div>
        <div>
          <label class="auth-label" for="fbText"><span>Nội dung</span></label>
          <textarea id="fbText" class="studio-textarea" maxlength="2000" required></textarea>
        </div>
        <p class="dock-note">Tác giả sẽ thấy email của bạn.</p>
        <p class="studio-alert error" id="fbError" role="alert" hidden></p>
        <div class="lesson-dialog-buttons">
          <button type="button" class="btn-studio-secondary" id="fbCancel">Hủy</button>
          <button type="submit" class="btn-studio-primary" id="fbSend">Gửi góp ý</button>
        </div>
      </form>`;
    document.body.append(dlg);
    const kinds = dlg.querySelector("#fbKinds");
    KINDS.forEach(([value, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "track-pill";
      b.dataset.kind = value;
      b.textContent = label;
      b.addEventListener("click", () => pick(value));
      kinds.append(b);
    });
    dlg.querySelector("#fbCancel").addEventListener("click", () => dlg.close());
    dlg.querySelector("#fbForm").addEventListener("submit", submit);
    return dlg;
  }

  function pick(value) {
    kind = value;
    document.querySelectorAll("#fbKinds [data-kind]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.kind === value)));
  }

  async function submit(e) {
    e.preventDefault();
    const dlg = document.getElementById("feedbackDialog");
    const error = dlg.querySelector("#fbError");
    const button = dlg.querySelector("#fbSend");
    error.hidden = true;
    button.disabled = true;
    try {
      const r = await fetch(`/api/lessons/${encodeURIComponent(current.lesson)}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, target_type: current.targetType, target_id: current.targetId, text: dlg.querySelector("#fbText").value }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || "Chưa gửi được. Thử lại sau.");
      dlg.close();
      if (current.onSent) current.onSent();
    } catch (err) {
      error.textContent = err.message === "Failed to fetch" ? "Không kết nối được. Thử lại." : err.message;
      error.hidden = false;
    }
    button.disabled = false;
  }

  // options: lesson, targetType ("lesson", "card", "quiz"), targetId, label, kind, onSent
  window.openFeedback = function (options) {
    const dlg = document.getElementById("feedbackDialog") || build();
    current = { targetType: "lesson", targetId: "", ...options };
    pick(options.kind || "comment");
    dlg.querySelector("#fbTarget").textContent = options.label || "";
    dlg.querySelector("#fbText").value = "";
    dlg.querySelector("#fbError").hidden = true;
    dlg.showModal();
  };
})();
