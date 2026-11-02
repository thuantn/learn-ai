"use strict";
(function () {
  const OUTSIDE = "http://127.0.0.1:8793";
  window.results = {};
  const res = window.results;

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function timeout(name, ms) {
    return wait(ms).then(function () { return "timeout"; });
  }

  function run(name, fn) {
    return Promise.resolve().then(function () {
      return Promise.race([fn(), timeout(name, 2000)]);
    }).then(function (v) {
      res[name] = v === undefined ? "ok" : v;
    }).catch(function (e) {
      res[name] = "err:" + (e && (e.message || e.name || e));
    });
  }

  function cookie() { return document.cookie || ""; }
  function ls() {
    try { return window.localStorage.length; }
    catch (e) { return "blocked:" + (e.name || e.message); }
  }
  function fetchUrl(url) {
    return fetch(url).then(function (r) { return "status:" + r.status; }, function () { return "blocked"; });
  }
  function xhr(url) {
    return new Promise(function (resolve) {
      var x = new XMLHttpRequest();
      x.open("GET", url);
      x.onload = function () { resolve("reached"); };
      x.onerror = function () { resolve("blocked"); };
      x.ontimeout = function () { resolve("blocked"); };
      try { x.send(); } catch (e) { resolve("blocked:" + (e.name || e.message)); }
    });
  }
  function beacon(url) {
    try { var ok = navigator.sendBeacon(url, "x"); return "sent:" + ok; }
    catch (e) { return "blocked:" + (e.name || e.message); }
  }
  function img(url) {
    return new Promise(function (resolve) {
      var i = new Image();
      i.onload = function () { resolve("reached"); };
      i.onerror = function () { resolve("blocked"); };
      i.src = url;
    });
  }
  function script(url) {
    return new Promise(function (resolve) {
      var s = document.createElement("script");
      s.onload = function () { resolve("reached"); };
      s.onerror = function () { resolve("blocked"); };
      s.src = url;
      document.head.appendChild(s);
    });
  }
  function css(url) {
    return new Promise(function (resolve) {
      var l = document.createElement("link");
      l.rel = "stylesheet";
      l.onload = function () { resolve("reached"); };
      l.onerror = function () { resolve("blocked"); };
      l.href = url;
      document.head.appendChild(l);
    });
  }
  function form(url) {
    return new Promise(function (resolve) {
      var f = document.createElement("form");
      f.method = "POST";
      f.action = url;
      var i = document.createElement("input");
      i.name = "x";
      i.value = "y";
      f.appendChild(i);
      document.body.appendChild(f);
      try { f.submit(); } catch (e) {}
      setTimeout(function () { resolve("submitted"); }, 300);
    });
  }
  function openWin(url) {
    try { var w = window.open(url, "_blank"); return w ? "opened" : "blocked"; }
    catch (e) { return "blocked:" + (e.name || e.message); }
  }
  function topLoc(url) {
    try { top.location = url; return "reached"; }
    catch (e) { return "blocked:" + (e.name || e.message); }
  }
  function parentLoc(url) {
    try { parent.location = url; return "reached"; }
    catch (e) { return "blocked:" + (e.name || e.message); }
  }
  function rtc() {
    return new Promise(function (resolve) {
      try {
        var pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:127.0.0.1:8794" }] });
        pc.createDataChannel("x");
        var n = 0;
        pc.onicecandidate = function (e) { if (e.candidate) n++; };
        setTimeout(function () {
          var state = pc.iceConnectionState;
          try { pc.close(); } catch (e) {}
          resolve({ state: state, candidates: n });
        }, 1200);
      } catch (e) { resolve("err:" + (e.name || e.message)); }
    });
  }
  function bridgeNope() {
    return LearnBridge.call("nope", {}).then(function () { return "ok"; }, function (e) { return e.code || "blocked"; });
  }
  function badMessage() {
    try { window.parent.postMessage({ id: "x", op: "foo", args: {} }, "*"); return "sent"; }
    catch (e) { return "err:" + (e.name || e.message); }
  }
  function circular() {
    var a = {}; a.self = a;
    return LearnBridge.call("doc.set", { data: a }).then(function () { return "ok"; }, function (e) { return e.code || ("err:" + (e.name || e.message)); });
  }
  function docGetOther() {
    return LearnBridge.call("doc.get", { doc: "other" }).then(function (d) { return d; }, function (e) { return e.code || "err"; });
  }
  function docSetFlood() {
    var ps = [];
    for (var i = 0; i < 200; i++) {
      ps.push(LearnBridge.call("doc.set", { data: { n: i } }));
    }
    return Promise.all(ps).then(function () { return "done"; }, function (e) { return e.code || "err"; });
  }
  function askOpen() {
    return LearnBridge.call("ask.open", { text: "dien san" }).then(function () { return "opened"; }, function (e) { return e.code || "err"; });
  }

  function main() {
    return Promise.resolve()
      .then(function () { return run("cookie", cookie); })
      .then(function () { return run("localStorage", ls); })
      .then(function () { return run("fetch_api_me", function () { return fetchUrl("/api/me"); }); })
      .then(function () { return run("fetch_outside", function () { return fetchUrl(OUTSIDE + "/fetch"); }); })
      .then(function () { return run("xhr_outside", function () { return xhr(OUTSIDE + "/xhr"); }); })
      .then(function () { return run("beacon_outside", function () { return beacon(OUTSIDE + "/beacon"); }); })
      .then(function () { return run("img_outside", function () { return img(OUTSIDE + "/img"); }); })
      .then(function () { return run("script_outside", function () { return script(OUTSIDE + "/script.js"); }); })
      .then(function () { return run("css_outside", function () { return css(OUTSIDE + "/css"); }); })
      .then(function () { return run("form_outside", function () { return form(OUTSIDE + "/form"); }); })
      .then(function () { return run("window_open", function () { return openWin(OUTSIDE + "/open"); }); })
      .then(function () { return run("top_location", function () { return topLoc(OUTSIDE + "/top"); }); })
      .then(function () { return run("parent_location", function () { return parentLoc(OUTSIDE + "/parent"); }); })
      .then(function () { return run("rtc", rtc); })
      .then(function () { return run("bridge_nope", bridgeNope); })
      .then(function () { return run("bad_message", badMessage); })
      .then(function () { return run("circular", circular); })
      .then(function () { return run("doc_get_other", docGetOther); })
      .then(function () { return run("doc_set_flood", docSetFlood); })
      .then(function () { return run("ask_open", askOpen); })
      .then(function () {
        return LearnBridge.call("doc.set", { data: { results: res } }).catch(function () {});
      });
  }

  main();
})();
