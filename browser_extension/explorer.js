(function initAutoHeLlegadoExplorer(global) {
  if (global.AutoHeLlegadoExplorer) {
    return;
  }

  const common = global.AutoHeLlegadoObserverCommon;
  const CONFIG = {
    schemaVersion: "1.0.0",
    snapshotsKey: "autoHeLlegadoExplorerSnapshots",
    enabledKey: "autoHeLlegadoExplorerEnabled",
    pausedKey: "autoHeLlegadoExplorerPaused",
    defaultEnabled: true,
    maxSnapshots: 200,
    maxElementsPerCategory: 100,
    maxOptionsPerSelect: 20,
    maxBodyText: 3000,
    maxElementText: 120,
    minCaptureIntervalMs: 1000
  };

  const state = {
    enabled: CONFIG.defaultEnabled,
    paused: false,
    initialized: false,
    lastCaptureAt: 0,
    lastSignature: "",
    lastState: null,
    persistQueue: Promise.resolve(),
    panelRefreshTimer: null
  };

  const PANEL_ID = "auto-he-llegado-explorer-panel";

  function isTopFrame() {
    return global.top === global;
  }

  function storageGet(keys) {
    return new Promise((resolve) => {
      try {
        global.chrome.storage.local.get(keys, (result) => {
          resolve(result || {});
        });
      } catch (_error) {
        resolve({});
      }
    });
  }

  function storageSet(payload) {
    return new Promise((resolve) => {
      try {
        global.chrome.storage.local.set(payload, () => resolve());
      } catch (_error) {
        resolve();
      }
    });
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function shouldCapture() {
    return state.enabled && !state.paused;
  }

  function limitText(value, maxLength = CONFIG.maxElementText) {
    const normalized = (value || "").replace(/\s+/g, " ").trim();
    if (!normalized) {
      return "";
    }
    const redacted = redactSensitiveText(normalized);
    if (redacted.length <= maxLength) {
      return redacted;
    }
    return `${redacted.slice(0, maxLength - 3)}...`;
  }

  function redactSensitiveText(value) {
    return (value || "")
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
      .replace(/\+?\d[\d\s().-]{7,}\d/g, "[redacted-phone]")
      .replace(/\b[A-Za-z0-9_-]{24,}\b/g, "[redacted-token]");
  }

  function sanitizeUrl(value) {
    if (!value) {
      return "";
    }
    try {
      const url = new URL(value, global.location.href);
      return limitText(`${url.origin}${url.pathname}${url.hash || ""}`, 160);
    } catch (_error) {
      return limitText(value, 160);
    }
  }

  function pickDataAttributes(node) {
    const dataset = node?.dataset || {};
    const entries = Object.entries(dataset).slice(0, 10);
    const result = {};
    for (const [key, value] of entries) {
      result[key] = limitText(String(value || ""), 80);
    }
    return result;
  }

  function buildSelector(node) {
    if (!node || !node.tagName) {
      return "";
    }
    const tag = node.tagName.toLowerCase();
    if (node.id) {
      return `${tag}#${node.id}`;
    }
    const classes = Array.from(node.classList || []).slice(0, 2);
    const classSuffix = classes.length ? `.${classes.join(".")}` : "";
    const name = node.getAttribute?.("name");
    if (name) {
      return `${tag}${classSuffix}[name="${name}"]`;
    }
    const siblings = node.parentElement ? Array.from(node.parentElement.children).filter((child) => child.tagName === node.tagName) : [];
    const index = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(node) + 1})` : "";
    return `${tag}${classSuffix}${index}`;
  }

  function elementBase(node) {
    const rect = typeof node.getBoundingClientRect === "function" ? node.getBoundingClientRect() : null;
    const style = global.getComputedStyle ? global.getComputedStyle(node) : null;
    return {
      tag: node.tagName?.toLowerCase() || "",
      text: limitText(common.safeText(node), CONFIG.maxElementText),
      id: node.id || "",
      className: limitText(node.className || "", 120),
      name: node.getAttribute?.("name") || "",
      type: node.getAttribute?.("type") || "",
      role: node.getAttribute?.("role") || "",
      ariaLabel: limitText(node.getAttribute?.("aria-label") || "", 120),
      ariaLabelledby: limitText(node.getAttribute?.("aria-labelledby") || "", 120),
      ariaDescribedby: limitText(node.getAttribute?.("aria-describedby") || "", 120),
      dataAttributes: pickDataAttributes(node),
      placeholder: limitText(node.getAttribute?.("placeholder") || "", 120),
      disabled: Boolean(node.disabled),
      checked: typeof node.checked === "boolean" ? node.checked : false,
      selected: typeof node.selected === "boolean" ? node.selected : false,
      visible: common.isNodeVisible(node),
      box: rect
        ? {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height)
          }
        : null,
      style: style
        ? {
            display: style.display,
            visibility: style.visibility,
            opacity: style.opacity
          }
        : null,
      selector: buildSelector(node)
    };
  }

  function collectVisibleElements(selector, mapper, limit = CONFIG.maxElementsPerCategory) {
    const nodes = Array.from(document.querySelectorAll(selector));
    const result = [];
    for (const node of nodes) {
      if (!common.isNodeVisible(node)) {
        continue;
      }
      try {
        result.push(mapper(node));
      } catch (_error) {
        // ignore broken node
      }
      if (result.length >= limit) {
        break;
      }
    }
    return result;
  }

  function collectButtons() {
    return collectVisibleElements(
      "button, [role='button'], input[type='button'], input[type='submit']",
      (node) => ({
        ...elementBase(node),
        buttonType: node.getAttribute("type") || node.type || ""
      })
    );
  }

  function collectInputs() {
    return collectVisibleElements(
      "input",
      (node) => ({
        ...elementBase(node),
        inputType: node.type || "",
        hasValue: Boolean(node.value),
        valueLength: typeof node.value === "string" ? node.value.length : 0,
        passwordField: node.type === "password"
      })
    );
  }

  function collectTextareas() {
    return collectVisibleElements(
      "textarea",
      (node) => ({
        ...elementBase(node),
        hasValue: Boolean(node.value),
        valueLength: typeof node.value === "string" ? node.value.length : 0
      })
    );
  }

  function collectSelects() {
    return collectVisibleElements(
      "select",
      (node) => ({
        ...elementBase(node),
        optionCount: node.options?.length || 0,
        selectedIndex: typeof node.selectedIndex === "number" ? node.selectedIndex : -1,
        options: Array.from(node.options || [])
          .slice(0, CONFIG.maxOptionsPerSelect)
          .map((option) => limitText(option.textContent || "", 80))
      })
    );
  }

  function collectLinks() {
    return collectVisibleElements(
      "a[href]",
      (node) => ({
        ...elementBase(node),
        href: sanitizeUrl(node.href || node.getAttribute("href") || "")
      })
    );
  }

  function collectLabels() {
    return collectVisibleElements("label", (node) => elementBase(node));
  }

  function collectForms() {
    return collectVisibleElements(
      "form",
      (node) => ({
        ...elementBase(node),
        action: sanitizeUrl(node.action || ""),
        method: (node.method || "get").toLowerCase()
      })
    );
  }

  function collectIframes() {
    return collectVisibleElements(
      "iframe",
      (node) => ({
        ...elementBase(node),
        src: sanitizeUrl(node.getAttribute("src") || ""),
        title: limitText(node.getAttribute("title") || "", 120)
      })
    );
  }

  function collectRoleElements() {
    return collectVisibleElements("[role]", (node) => elementBase(node));
  }

  function collectAriaElements() {
    return collectVisibleElements("[aria-label], [aria-labelledby], [aria-describedby]", (node) => elementBase(node));
  }

  function collectDataAttributeElements() {
    return collectVisibleElements(
      "*",
      (node) => elementBase(node),
      CONFIG.maxElementsPerCategory
    ).filter((entry) => Object.keys(entry.dataAttributes || {}).length > 0);
  }

  function collectHeadings() {
    return collectVisibleElements("h1, h2, h3, h4, h5, h6", (node) => elementBase(node));
  }

  function collectDialogs() {
    return collectVisibleElements(
      "dialog, [role='dialog'], [aria-modal='true']",
      (node) => elementBase(node)
    );
  }

  function collectTextElements() {
    return collectVisibleElements(
      "h1, h2, h3, h4, h5, h6, p, span, div, li",
      (node) => elementBase(node)
    ).filter((entry) => Boolean(entry.text));
  }

  function collectCandidateElements() {
    const textIndex = collectVisibleElements(
      "button, [role='button'], a, label, h1, h2, h3, h4, h5, h6, p, span, div",
      (node) => elementBase(node),
      200
    );
    const findByTokens = (tokens) =>
      textIndex.filter((entry) => tokens.some((token) => common.normalizeText(entry.text).includes(common.normalizeText(token)))).slice(0, 10);

    return {
      selfie: findByTokens(["selfie", "foto tipo selfie", "take a selfie", "tire uma foto tipo selfie"]),
      continue: findByTokens(["continuar", "continue", "prosseguir"]),
      loading: findByTokens(["cargando", "loading", "procesando", "validando", "processando", "verifying"]),
      block: findByTokens(["pago", "precio", "price", "payment", "estacion", "station", "duracion", "duration"]),
      result: findByTokens(["exitoso", "successful", "sucesso", "he llegado", "i'm here", "eu cheguei"])
    };
  }

  function buildSnapshot(extensionState) {
    const visibleText = common.collectVisibleText(document.body);
    const bodyTextSample = limitText(visibleText, CONFIG.maxBodyText);
    const safeState = extensionState || {};
    const safeSignals = safeState.signals || {};
    const snapshot = {
      schemaVersion: CONFIG.schemaVersion,
      timestamp: nowIso(),
      href: global.location.href,
      origin: global.location.origin,
      hostname: global.location.hostname,
      pathname: global.location.pathname,
      isTopFrame: global.top === global,
      frameDepth: (() => {
        let depth = 0;
        let current = global;
        try {
          while (current !== current.top) {
            depth += 1;
            current = current.parent;
          }
        } catch (_error) {
          return depth;
        }
        return depth;
      })(),
      title: limitText(document.title || "", 200),
      readyState: document.readyState,
      viewport: {
        width: global.innerWidth,
        height: global.innerHeight
      },
      scroll: {
        x: Math.round(global.scrollX || 0),
        y: Math.round(global.scrollY || 0)
      },
      bodyTextSample,
      bodyTextLength: visibleText.length,
      documentElementClass: limitText(document.documentElement?.className || "", 200),
      bodyClass: limitText(document.body?.className || "", 200),
      counts: {
        iframeCount: document.querySelectorAll("iframe").length,
        formCount: document.forms?.length || 0,
        inputCount: document.querySelectorAll("input").length,
        buttonCount: document.querySelectorAll("button, [role='button'], input[type='button'], input[type='submit']").length
      },
      detectorOutput: {
        site: safeState.site || "unknown",
        lang: safeState.lang || "unknown",
        phase: safeState.phase || "unknown",
        signals: {
          userAvatarVisible: Boolean(safeSignals.userAvatarVisible),
          continueCount: Number(safeSignals.continueCount || 0),
          loadingStrong: Boolean(safeSignals.loadingStrong),
          blockReady: Boolean(safeSignals.blockReady),
          relevantIframeCount: Number(safeSignals.relevantIframeCount || 0)
        }
      },
      elements: {
        buttons: collectButtons(),
        inputs: collectInputs(),
        textareas: collectTextareas(),
        selects: collectSelects(),
        links: collectLinks(),
        labels: collectLabels(),
        forms: collectForms(),
        iframes: collectIframes(),
        roles: collectRoleElements(),
        aria: collectAriaElements(),
        data: collectDataAttributeElements(),
        headings: collectHeadings(),
        dialogs: collectDialogs(),
        text: collectTextElements()
      },
      candidates: collectCandidateElements()
    };
    snapshot.signature = [
      snapshot.href,
      snapshot.bodyTextSample,
      snapshot.detectorOutput.site,
      snapshot.detectorOutput.lang,
      snapshot.detectorOutput.phase,
      snapshot.detectorOutput.signals.userAvatarVisible,
      snapshot.detectorOutput.signals.continueCount,
      snapshot.detectorOutput.signals.loadingStrong,
      snapshot.detectorOutput.signals.blockReady,
      snapshot.detectorOutput.signals.relevantIframeCount
    ].join("|");
    return snapshot;
  }

  async function persistSnapshot(snapshot) {
    state.persistQueue = state.persistQueue.then(async () => {
      const payload = await storageGet([CONFIG.snapshotsKey]);
      const current = payload[CONFIG.snapshotsKey] || {
        schemaVersion: CONFIG.schemaVersion,
        totalCaptures: 0,
        totalDropped: 0,
        snapshots: []
      };
      current.totalCaptures += 1;
      const lastSnapshot = current.snapshots[current.snapshots.length - 1];
      if (lastSnapshot && lastSnapshot.signature === snapshot.signature) {
        current.totalDropped += 1;
        await storageSet({ [CONFIG.snapshotsKey]: current });
        return current;
      }
      const nextSnapshots = current.snapshots.concat(snapshot).slice(-CONFIG.maxSnapshots);
      const nextPayload = {
        schemaVersion: CONFIG.schemaVersion,
        totalCaptures: current.totalCaptures,
        totalDropped: current.totalDropped,
        snapshots: nextSnapshots
      };
      await storageSet({ [CONFIG.snapshotsKey]: nextPayload });
      return nextPayload;
    });
    return state.persistQueue;
  }

  async function readSnapshotState() {
    const payload = await storageGet([CONFIG.snapshotsKey, CONFIG.enabledKey, CONFIG.pausedKey]);
    const snapshotPayload = payload[CONFIG.snapshotsKey] || {
      schemaVersion: CONFIG.schemaVersion,
      totalCaptures: 0,
      totalDropped: 0,
      snapshots: []
    };
    return {
      enabled: payload[CONFIG.enabledKey] ?? CONFIG.defaultEnabled,
      paused: payload[CONFIG.pausedKey] ?? false,
      snapshotCount: snapshotPayload.snapshots?.length || 0,
      totalCaptures: snapshotPayload.totalCaptures || 0,
      totalDropped: snapshotPayload.totalDropped || 0,
      snapshots: snapshotPayload.snapshots || []
    };
  }

  function ensurePanel() {
    if (!isTopFrame()) {
      return null;
    }
    let root = document.getElementById(PANEL_ID);
    if (root) {
      return root;
    }
    root = document.createElement("div");
    root.id = PANEL_ID;
    root.style.position = "fixed";
    root.style.right = "12px";
    root.style.bottom = "12px";
    root.style.zIndex = "2147483647";
    root.style.width = "220px";
    root.style.maxWidth = "calc(100vw - 24px)";
    root.style.background = "rgba(15, 23, 42, 0.95)";
    root.style.color = "#f8fafc";
    root.style.border = "1px solid rgba(255,255,255,0.12)";
    root.style.borderRadius = "8px";
    root.style.boxShadow = "0 10px 24px rgba(0,0,0,0.25)";
    root.style.fontFamily = "Arial, sans-serif";
    root.style.fontSize = "12px";
    root.style.lineHeight = "1.4";
    root.style.padding = "8px 10px";
    root.innerHTML = [
      '<div style="font-weight:700; margin-bottom:6px;">Explorer</div>',
      '<div data-slot="status" style="margin-bottom:6px;">--</div>',
      '<div data-slot="count" style="margin-bottom:8px; color:#cbd5e1;">--</div>',
      '<div style="display:flex; gap:6px; flex-wrap:wrap;">',
      '<button data-action="toggle" style="padding:4px 8px; border-radius:6px; border:0; background:#334155; color:#fff; cursor:pointer;">Pause</button>',
      '<button data-action="export" style="padding:4px 8px; border-radius:6px; border:0; background:#2563eb; color:#fff; cursor:pointer;">Export JSON</button>',
      '<button data-action="clear" style="padding:4px 8px; border-radius:6px; border:0; background:#b91c1c; color:#fff; cursor:pointer;">Clear</button>',
      "</div>"
    ].join("");
    root.addEventListener("click", async (event) => {
      const target = event.target;
      const action = target?.dataset?.action;
      if (!action) {
        return;
      }
      if (action === "toggle") {
        state.paused = !state.paused;
        await storageSet({ [CONFIG.pausedKey]: state.paused });
        await refreshPanel();
        return;
      }
      if (action === "clear") {
        await storageSet({
          [CONFIG.snapshotsKey]: {
            schemaVersion: CONFIG.schemaVersion,
            totalCaptures: 0,
            totalDropped: 0,
            snapshots: []
          }
        });
        await refreshPanel();
        return;
      }
      if (action === "export") {
        await exportSnapshots();
      }
    });
    (document.body || document.documentElement)?.appendChild(root);
    return root;
  }

  async function refreshPanel() {
    const panel = ensurePanel();
    if (!panel) {
      return;
    }
    const snapshotState = await readSnapshotState();
    state.enabled = snapshotState.enabled;
    state.paused = snapshotState.paused;
    const statusNode = panel.querySelector('[data-slot="status"]');
    const countNode = panel.querySelector('[data-slot="count"]');
    const toggleButton = panel.querySelector('[data-action="toggle"]');
    if (statusNode) {
      statusNode.textContent = `Status: ${state.enabled ? (state.paused ? "PAUSED" : "ON") : "OFF"}`;
    }
    if (countNode) {
      countNode.textContent = `Snapshots: ${snapshotState.snapshotCount} | Captures: ${snapshotState.totalCaptures} | Dropped: ${snapshotState.totalDropped}`;
    }
    if (toggleButton) {
      toggleButton.textContent = state.paused ? "Resume" : "Pause";
    }
  }

  async function exportSnapshots() {
    const snapshotState = await readSnapshotState();
    const payload = {
      generatedAt: nowIso(),
      extensionVersion: global.chrome?.runtime?.getManifest?.().version || "unknown",
      snapshotCount: snapshotState.snapshotCount,
      userAgent: global.navigator?.userAgent || "",
      schemaVersion: CONFIG.schemaVersion,
      totalCaptures: snapshotState.totalCaptures,
      totalDropped: snapshotState.totalDropped,
      snapshots: snapshotState.snapshots
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = global.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `auto-he-llegado-explorer-${Date.now()}.json`;
    document.documentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    global.URL.revokeObjectURL(url);
  }

  async function captureSnapshot(extensionState) {
    state.lastState = extensionState || state.lastState;
    if (!shouldCapture()) {
      return;
    }
    const now = Date.now();
    if (now - state.lastCaptureAt < CONFIG.minCaptureIntervalMs) {
      return;
    }
    state.lastCaptureAt = now;
    const snapshot = buildSnapshot(state.lastState);
    await persistSnapshot(snapshot);
    if (isTopFrame()) {
      await refreshPanel();
    }
  }

  async function initialize() {
    if (state.initialized) {
      return;
    }
    state.initialized = true;
    const flags = await storageGet([CONFIG.enabledKey, CONFIG.pausedKey, CONFIG.snapshotsKey]);
    state.enabled = flags[CONFIG.enabledKey] ?? CONFIG.defaultEnabled;
    state.paused = flags[CONFIG.pausedKey] ?? false;
    if (flags[CONFIG.enabledKey] === undefined) {
      await storageSet({ [CONFIG.enabledKey]: state.enabled });
    }
    if (!flags[CONFIG.snapshotsKey]) {
      await storageSet({
        [CONFIG.snapshotsKey]: {
          schemaVersion: CONFIG.schemaVersion,
          totalCaptures: 0,
          totalDropped: 0,
          snapshots: []
        }
      });
    }
    if (isTopFrame()) {
      ensurePanel();
      await refreshPanel();
      state.panelRefreshTimer = global.setInterval(() => {
        refreshPanel();
      }, 1500);
    }
    global.setInterval(() => {
      captureSnapshot(state.lastState);
    }, CONFIG.minCaptureIntervalMs);
  }

  global.AutoHeLlegadoExplorer = {
    initialize,
    captureSnapshot,
    refreshPanel
  };
})(window);
