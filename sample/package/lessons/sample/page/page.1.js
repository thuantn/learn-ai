"use strict";
(function () {
  function sendAnswer() {
    window.LearnBridge.call("quiz.answer", { id: "sample-q0", option: 1 });
  }
  function setup() {
    document.getElementById("send").addEventListener("click", sendAnswer);
  }
  if (document.readyState !== "loading") setup();
  else document.addEventListener("DOMContentLoaded", setup);
})();
