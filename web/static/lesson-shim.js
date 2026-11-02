"use strict";
// Lesson pages expect window.claude; this answers the same calls with this app's API.
(function () {
  const lesson = document.currentScript.dataset.lesson;
  const api = async (url, opts) => {
    const r = await fetch(url, opts);
    if (r.status === 401 || r.status === 403) { location.href = "/login"; throw { code: "login" }; }
    const d = await r.json();
    if (!r.ok) throw { code: d.code || "server", message: d.error };
    return d;
  };
  const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  window.claude = {
    use: async function (name) {
      if (name === "user") return { id: async () => (await api("/api/me")).id };
      if (name === "sample") return async input => ({ text: (await api("/api/ask", json("POST", { lesson, input }))).text });
      if (name === "db") return {
        doc: path => {
          const url = "/api/doc/" + encodeURIComponent(path.split("/").pop());
          return {
            get: async () => { const d = (await api(url)).data; return { exists: !!d, data: () => d }; },
            set: body => api(url, json("PUT", body))
          };
        }
      };
      return null;
    }
  };
})();
