"use strict";
// Synchronous bridge loaded first in lesson pages. No cookies, no fetch.
(function () {
  const queued = [];
  let port = null;
  let timedOut = false;
  let nextId = 1;
  let helloTimer = null;

  function flushQueue() {
    while (queued.length) {
      const item = queued.shift();
      port.postMessage({ id: item.id, op: item.op, args: item.args });
    }
  }

  function onPortMessage(event) {
    const msg = event.data;
    if (!msg || typeof msg.id !== "number") return;
    for (let i = 0; i < queued.length; i++) {
      if (queued[i].id === msg.id) {
        const item = queued.splice(i, 1)[0];
        if (msg.ok) item.resolve(msg.data);
        else item.reject({ code: msg.code || "error", message: msg.message || "" });
        return;
      }
    }
  }

  function onHello(event) {
    if (event.source !== window.parent) return;
    const msg = event.data;
    if (!msg || msg.type !== "learn-port" || !event.ports[0]) return;
    if (helloTimer) { clearInterval(helloTimer); helloTimer = null; }
    port = event.ports[0];
    port.onmessage = onPortMessage;
    port.start();
    timedOut = false;
    flushQueue();
  }

  function startTimeout() {
    setTimeout(() => {
      if (port) return;
      timedOut = true;
      if (helloTimer) { clearInterval(helloTimer); helloTimer = null; }
      while (queued.length) {
        const item = queued.shift();
        item.reject({ code: "timeout", message: "Không kết nối được với app." });
      }
    }, 10000);
  }

  window.addEventListener("message", onHello);
  helloTimer = setInterval(() => {
    window.parent.postMessage({ type: "learn-hello" }, "*");
  }, 200);

  window.LearnBridge = {
    call: function (op, args) {
      if (timedOut) return Promise.reject({ code: "timeout", message: "Không kết nối được với app." });
      const id = nextId++;
      return new Promise((resolve, reject) => {
        queued.push({ id, op, args: args || {}, resolve, reject });
        if (queued.length === 1) startTimeout();
        if (port) flushQueue();
      });
    },
    askApp: function (text) {
      return window.LearnBridge.call("ask.open", { text: text || "" });
    }
  };

  window.claude = {
    use: async function (name) {
      if (name === "user") {
        const id = await window.LearnBridge.call("learner.id");
        return { id };
      }
      if (name === "db") {
        return {
          doc: function () {
            return {
              get: () => window.LearnBridge.call("doc.get", {}),
              set: data => window.LearnBridge.call("doc.set", data)
            };
          }
        };
      }
      if (name === "sample") return null;
      return null;
    }
  };

  document.addEventListener("click", function (event) {
    const a = event.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    if (href.startsWith("#")) return;
    event.preventDefault();
    window.LearnBridge.call("link.open", { url: a.href });
  }, true);

  document.addEventListener("error", function (event) {
    if (event.target && event.target.tagName === "AUDIO") {
      window.LearnBridge.call("media.error", { src: event.target.currentSrc || "" });
    }
  }, true);
})();
