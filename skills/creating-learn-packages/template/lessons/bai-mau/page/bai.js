"use strict";
// Trang chạy trong sandbox: không có cookie, localStorage hay mạng. Mọi thứ cần lưu đi qua LearnBridge.
// Mở file trên máy thì không có LearnBridge: bài vẫn đọc được, chỉ không chấm và không lưu.
(function () {
  const bridge = window.LearnBridge;
  let saved = { answered: {} };

  function show(box, correct) {
    const result = box.querySelector(".result");
    result.textContent = correct ? "Đúng." : "Chưa đúng.";
    result.className = "result " + (correct ? "is-good" : "is-bad");
    const why = box.querySelector(".why");
    if (why) why.hidden = false;
  }

  async function answer(box, option) {
    const id = box.dataset.quiz;
    if (!bridge) {
      box.querySelector(".result").textContent = "Mở bài trong app để được chấm.";
      return;
    }
    try {
      const reply = await bridge.call("quiz.answer", { id, option });
      show(box, reply.correct);
      saved.answered[id] = reply.correct;
      await bridge.call("doc.set", { data: saved });
    } catch (e) {
      box.querySelector(".result").textContent = "Chưa gửi được, thử lại sau.";
    }
  }

  async function restore() {
    if (!bridge) return;
    const data = await bridge.call("doc.get").catch(() => null);
    if (!data || !data.answered) return;
    saved = data;
    document.querySelectorAll("[data-quiz]").forEach(box => {
      if (box.dataset.quiz in saved.answered) show(box, saved.answered[box.dataset.quiz]);
    });
  }

  document.querySelectorAll("[data-quiz] [data-option]").forEach(b => {
    b.addEventListener("click", () => answer(b.closest("[data-quiz]"), Number(b.dataset.option)));
  });
  document.querySelectorAll("[data-ask]").forEach(b => {
    b.addEventListener("click", () => {
      if (bridge) bridge.askApp(b.dataset.ask);
      else b.textContent = "Mở bài trong app để hỏi";
    });
  });
  restore();
})();
