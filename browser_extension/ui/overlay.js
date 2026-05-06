(function initOverlay(global) {
  if (global.AutoHeLlegadoOverlay) {
    return;
  }

  const OVERLAY_ID = "auto-he-llegado-overlay";
  const FRAME_OVERLAY_ID = "auto-he-llegado-frame-overlay";
  const STORAGE_KEY = "autoHeLlegado.overlayCollapsed";

  function getOverlayHost() {
    return document.body || document.documentElement;
  }

  function ensureOverlay() {
    let root = document.getElementById(OVERLAY_ID);
    if (root) {
      return root;
    }
    root = document.createElement("div");
    root.id = OVERLAY_ID;
    root.setAttribute("data-mounted-by", "auto-he-llegado-extension");
    root.innerHTML = [
      '<div class="auto-he-llegado-overlay-header">',
      '<div class="auto-he-llegado-overlay-title">Auto He Llegado</div>',
      '<div class="auto-he-llegado-overlay-toggle">toggle</div>',
      "</div>",
      '<div class="auto-he-llegado-overlay-body"></div>'
    ].join("");
    root.querySelector(".auto-he-llegado-overlay-header").addEventListener("click", () => {
      const collapsed = root.dataset.collapsed === "true";
      root.dataset.collapsed = collapsed ? "false" : "true";
      global.localStorage.setItem(STORAGE_KEY, root.dataset.collapsed);
    });
    root.dataset.collapsed = global.localStorage.getItem(STORAGE_KEY) || "false";
    getOverlayHost()?.appendChild(root);
    console.info("[auto-he-llegado] overlay mounted", { frame: global.top === global ? "top" : "iframe" });
    return root;
  }

  function ensureFrameOverlay() {
    let root = document.getElementById(FRAME_OVERLAY_ID);
    if (root) {
      return root;
    }
    root = document.createElement("div");
    root.id = FRAME_OVERLAY_ID;
    root.setAttribute("data-mounted-by", "auto-he-llegado-extension");
    getOverlayHost()?.appendChild(root);
    console.info("[auto-he-llegado] iframe overlay mounted", { url: global.location.href });
    return root;
  }

  function renderRows(root, rows) {
    root.innerHTML = rows
      .map(
        ([label, value]) =>
          `<div class="auto-he-llegado-row"><div class="auto-he-llegado-label">${label}</div><div class="auto-he-llegado-value">${value}</div></div>`
      )
      .join("");
  }

  function renderOverlay(state) {
    const root = ensureOverlay();
    const body = root.querySelector(".auto-he-llegado-overlay-body");
    const rows = [
      ["Site", state.site],
      ["Lang", state.lang],
      ["Phase", state.phase],
      ["Last valid", state.lastValidPhase || "--"],
      ["Frame", state.frameRole],
      ["Iframe active", state.iframeActive ? "yes" : "no"],
      ["Worker", state.serviceWorkerAlive ? "yes" : "no"],
      ["user_avatar", state.signals.userAvatarVisible ? "yes" : "no"],
      ["Continue", String(state.signals.continueCount)],
      ["Block signals", state.signals.blockStrong ? "yes" : "no"]
    ];
    renderRows(body, rows);
  }

  function renderIframeOverlay(state) {
    const root = ensureFrameOverlay();
    root.textContent = `Auto He Llegado iframe | Site: ${state.site} | Lang: ${state.lang} | Phase: ${state.phase} | Last: ${state.lastValidPhase || "--"}`;
  }

  global.AutoHeLlegadoOverlay = {
    renderIframeOverlay,
    renderOverlay
  };
})(window);
