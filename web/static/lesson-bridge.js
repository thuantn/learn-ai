"use strict";
// Synchronous bridge loaded first in lesson pages. No cookies, no fetch.
(function () {
  const pending = [];
  const inflight = new Map();
  let port = null;
  let nextId = 1;
  let helloTimer = null;
  let helloStopTimer = null;

  function startCallTimer(item) {
    item.timer = setTimeout(() => {
      const at = pending.indexOf(item);
      if (at >= 0) pending.splice(at, 1);
      inflight.delete(item.id);
      item.reject({ code: "timeout", message: "Không kết nối được với app." });
    }, 10000);
  }

  function flushPending() {
    while (pending.length) {
      const item = pending.shift();
      inflight.set(item.id, item);
      port.postMessage({ id: item.id, op: item.op, args: item.args });
    }
  }

  function onPortMessage(event) {
    const msg = event.data;
    if (!msg || typeof msg.id !== "number") return;
    const item = inflight.get(msg.id);
    if (!item) return;
    inflight.delete(msg.id);
    clearTimeout(item.timer);
    if (msg.ok) item.resolve(msg.data);
    else item.reject({ code: msg.code || "error", message: msg.message || "" });
  }

  function stopHello() {
    if (helloTimer) { clearInterval(helloTimer); helloTimer = null; }
    if (helloStopTimer) { clearTimeout(helloStopTimer); helloStopTimer = null; }
  }

  function startHello() {
    window.parent.postMessage({ type: "learn-hello" }, "*");
    helloTimer = setInterval(() => {
      window.parent.postMessage({ type: "learn-hello" }, "*");
    }, 200);
    helloStopTimer = setTimeout(stopHello, 10000);
  }

  function onHello(event) {
    if (event.source !== window.parent) return;
    const msg = event.data;
    if (!msg || msg.type !== "learn-port" || !event.ports[0]) return;
    // A later port answers a hello sent while the first was on its way. The first one stays in use.
    if (port) return;
    stopHello();
    port = event.ports[0];
    port.onmessage = onPortMessage;
    port.start();
    flushPending();
  }

  window.addEventListener("message", onHello);

  window.LearnBridge = {
    call: function (op, args) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        const item = { id, op, args: args || {}, resolve, reject };
        startCallTimer(item);
        if (port) {
          inflight.set(id, item);
          port.postMessage({ id, op, args: item.args });
        } else {
          pending.push(item);
          if (!helloTimer) startHello();
        }
      });
    },
    askApp: function (text) {
      window.LearnBridge.call("ask.open", { text: text || "" }).catch(() => {});
    }
  };

  window.claude = {
    use: async function (name) {
      if (name === "user") {
        const learnerId = await window.LearnBridge.call("learner.id");
        return { id: async () => learnerId };
      }
      if (name === "db") {
        return {
          doc: function () {
            return {
              get: async () => {
                const data = await window.LearnBridge.call("doc.get", {});
                return { exists: data !== null, data: () => data };
              },
              set: body => window.LearnBridge.call("doc.set", { data: body })
            };
          }
        };
      }
      if (name === "sample") return null;
      return null;
    }
  };

  document.addEventListener("click", function (event) {
    if (!(event.target instanceof Element)) return;
    const a = event.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    event.preventDefault();
    if (href.startsWith("#")) {
      // WebKit reloads a sandboxed page on a link within it, and the host closes a page that reloads.
      const target = href === "#" ? document.documentElement : document.getElementById(href.slice(1));
      if (target) target.scrollIntoView();
      return;
    }
    window.LearnBridge.call("link.open", { url: a.href }).catch(() => {});
  }, true);

  // On a phone the app bar and the lesson's menu leave while reading down and return on the way up.
  const NARROW = "(max-width: 1023px)";
  const narrow = window.matchMedia(NARROW);
  const style = document.createElement("style");
  style.textContent = `@media ${NARROW}{nav.top{transition:transform .15s}html[data-learn-reading] nav.top{transform:translateY(-100%)}}`;
  (document.head || document.documentElement).append(style);
  let lastY = 0;
  let reading = false;
  let settleUntil = 0;

  function setReading(on) {
    if (on === reading) return;
    reading = on;
    // The frame changes height with the bar, and at the end of the page the browser then moves the scroll by itself.
    settleUntil = performance.now() + 300;
    document.documentElement.toggleAttribute("data-learn-reading", on);
    window.LearnBridge.call("bar.set", { hidden: on }).catch(() => {});
  }

  window.addEventListener("scroll", function () {
    const y = Math.max(0, Math.min(window.scrollY, document.documentElement.scrollHeight - window.innerHeight));
    if (!narrow.matches || y < 64) setReading(false);
    else if (performance.now() >= settleUntil) {
      if (Math.abs(y - lastY) < 12) return;
      setReading(y > lastY);
    }
    lastY = y;
  }, { passive: true });

  document.addEventListener("error", function (event) {
    if (!(event.target instanceof Element)) return;
    const audio = event.target.closest("audio");
    if (!audio) return;
    window.LearnBridge.call("media.error", { src: audio.currentSrc || "" }).catch(() => {});
  }, true);

  // When the page has its own floating Ask button, pad bottom and notify host.
  function checkOwnAsk() {
    if (document.getElementById("fab")) {
      document.body.style.paddingBottom = "72px";
      window.LearnBridge.call("page.ownAsk", {}).catch(() => {});
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkOwnAsk);
  } else {
    checkOwnAsk();
  }
})();
