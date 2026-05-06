(function initAutoHeLlegadoContent(global) {
  if (global.__autoHeLlegadoObserverInitialized) {
    return;
  }
  global.__autoHeLlegadoObserverInitialized = true;

  const common = global.AutoHeLlegadoObserverCommon;
  const languageDetector = global.AutoHeLlegadoLanguageDetector;
  const iframeDetector = global.AutoHeLlegadoIframeDetector;
  const phaseDetector = global.AutoHeLlegadoPhaseDetector;
  const overlay = global.AutoHeLlegadoOverlay;
  const explorer = global.AutoHeLlegadoExplorer;
  const childFrameStates = new Map();
  const phaseHistory = [];
  const stateMemory = {
    site: "unknown",
    lang: "unknown",
    frameRole: global.top === global ? "top" : "iframe",
    frameUrl: global.location.href,
    phase: "unknown",
    phaseAt: null
  };
  let updateTimer = null;
  let backupTimer = null;
  let lastPublishedSignature = "";
  let runtimeAlive = false;
  let lastUrl = global.location.href;

  function getFrameDepth() {
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
  }

  function isTopFrame() {
    return global.top === global;
  }

  function updateContentMarkers() {
    if (!document.documentElement) {
      return;
    }
    document.documentElement.dataset.autoHeLlegadoContentLoaded = "true";
    document.documentElement.dataset.autoHeLlegadoContentScript = "loaded";
    document.documentElement.dataset.autoHeLlegadoContentHref = global.location.href;
    document.documentElement.dataset.autoHeLlegadoContentHostname = global.location.hostname;
    document.documentElement.dataset.autoHeLlegadoContentFrame = isTopFrame() ? "top" : "iframe";
    document.documentElement.dataset.autoHeLlegadoContentTimestamp = String(Date.now());
    document.documentElement.dataset.autoHeLlegadoBridgeStatus = "disabled";
    document.documentElement.dataset.autoHeLlegadoBridgeRequested = "false";
    document.documentElement.dataset.autoHeLlegadoBridgeInstalled = "false";
    document.documentElement.dataset.autoHeLlegadoMainWorld = "disabled";
    document.documentElement.dataset.autoHeLlegadoMainWorldHref = "";
    document.documentElement.dataset.autoHeLlegadoMainWorldHostname = "";
  }

  updateContentMarkers();
  console.info("[auto-he-llegado] extension content script loaded", {
    href: global.location.href,
    origin: global.location.origin,
    hostname: global.location.hostname,
    isTopFrame: isTopFrame(),
    frame: isTopFrame() ? "top" : "iframe",
    frameDepth: getFrameDepth()
  });

  function shouldShowOverlay() {
    const flags = new URLSearchParams(global.location.search);
    const queryValue = flags.get("auto-he-llegado-overlay");
    if (queryValue === "off") {
      return false;
    }
    if (queryValue === "on") {
      return true;
    }
    const localStorageValue = global.localStorage.getItem("autoHeLlegado.overlayEnabled");
    if (localStorageValue === "false") {
      return false;
    }
    if (localStorageValue === "true") {
      return true;
    }
    return true;
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function buildPingPayload() {
    return {
      loaded: true,
      href: global.location.href,
      hostname: global.location.hostname,
      timestamp: Date.now(),
      isTopFrame: isTopFrame(),
      frameDepth: getFrameDepth()
    };
  }

  function publishPing() {
    const ping = buildPingPayload();
    updateContentMarkers();
    if (document.documentElement) {
      document.documentElement.dataset.autoHeLlegadoPingLoaded = ping.loaded ? "true" : "false";
      document.documentElement.dataset.autoHeLlegadoPingHref = ping.href || "";
      document.documentElement.dataset.autoHeLlegadoPingHostname = ping.hostname || "";
      document.documentElement.dataset.autoHeLlegadoPingTimestamp = String(ping.timestamp || "");
    }
    return ping;
  }

  function publishStateMarkers(state) {
    if (!document.documentElement || !state) {
      return;
    }
    const signals = state.signals || {};
    document.documentElement.dataset.autoHeLlegadoSite = state.site || "unknown";
    document.documentElement.dataset.autoHeLlegadoLang = state.lang || "unknown";
    document.documentElement.dataset.autoHeLlegadoPhase = state.phase || "unknown";
    document.documentElement.dataset.autoHeLlegadoLastValidPhase = state.lastValidPhase || "unknown";
    document.documentElement.dataset.autoHeLlegadoSignalsUserAvatar = signals.userAvatarVisible ? "true" : "false";
    document.documentElement.dataset.autoHeLlegadoSignalsContinue = String(signals.continueCount || 0);
    document.documentElement.dataset.autoHeLlegadoSignalsLoading = signals.loadingStrong ? "true" : "false";
    document.documentElement.dataset.autoHeLlegadoSignalsBlock = signals.blockReady ? "true" : "false";
    document.documentElement.dataset.autoHeLlegadoSignalsIframe = String(signals.relevantIframeCount || 0);
    document.documentElement.dataset.autoHeLlegadoUpdatedAt = state.observedAt || nowIso();
  }

  function persistLatestState(state) {
    try {
      if (!global.chrome?.storage?.local?.set || !state) {
        return;
      }
      global.chrome.storage.local.set({
        autoHeLlegadoLatestState: {
          ...state,
          persistedAt: nowIso()
        }
      });
    } catch (error) {
      console.warn("[auto-he-llegado] storage.local set failed", error);
    }
  }

  function normalizeChildState(payload) {
    if (!payload || !payload.frameUrl) {
      return null;
    }
    return {
      site: payload.site || "unknown",
      lang: payload.lang || "unknown",
      phase: payload.phase || "unknown",
      frameRole: payload.frameRole || "iframe",
      frameUrl: payload.frameUrl,
      observedAt: payload.observedAt || nowIso(),
      signals: payload.signals || {},
      iframeSignals: payload.iframeSignals || {},
      blockSignals: payload.blockSignals || {},
      finalSignals: payload.finalSignals || {},
      diagnostics: payload.diagnostics || {}
    };
  }

  function inferSiteFromIframeSignals(iframeSignals) {
    const relevantFrames = iframeSignals?.relevantFrames || [];
    for (const frame of relevantFrames) {
      const inferred = common.getSiteFromHostname(frame.src || "");
      if (inferred !== "unknown") {
        return inferred;
      }
    }
    return "unknown";
  }

  function getOwnSnapshot() {
    const visibleText = common.collectVisibleText(document.body);
    const iframeSignals = iframeDetector.collectIframeSignals();
    const siteFromHostname = common.getSiteFromHostname(global.location.hostname);
    const siteFromIframe = inferSiteFromIframeSignals(iframeSignals);
    const site = siteFromHostname !== "unknown" ? siteFromHostname : siteFromIframe;
    const languageDiagnosis = languageDetector.diagnoseLanguage(visibleText);
    const lang = languageDiagnosis.lang;
    const dashboardSignals = phaseDetector.detectDashboardSignals();
    const selfieSignals = phaseDetector.detectSelfieSignals();
    const accountSignals = phaseDetector.detectAccountSignals();
    const processingSignals = phaseDetector.detectProcessingSignals(visibleText);
    const blockSignals = phaseDetector.detectBlockSignals(visibleText);
    const finalSignals = phaseDetector.detectFinalSignals(visibleText);
    const snapshot = {
      site,
      lang,
      visibleTextLength: visibleText.length,
      iframeSignals,
      dashboardSignals,
      selfieSignals,
      accountSignals,
      processingSignals,
      blockSignals,
      finalSignals
    };
    const phaseDiagnosis = phaseDetector.diagnosePhase(snapshot);
    return {
      frameRole: global.top === global ? "top" : "iframe",
      frameUrl: global.location.href,
      href: global.location.href,
      origin: global.location.origin,
      hostname: global.location.hostname,
      isTopFrame: isTopFrame(),
      frameDepth: getFrameDepth(),
      observedAt: nowIso(),
      ...snapshot,
      languageDiagnosis,
      phaseDiagnosis,
      phase: phaseDiagnosis.phase,
      diagnostics: {
        url: global.location.href,
        href: global.location.href,
        origin: global.location.origin,
        hostname: global.location.hostname,
        isTopFrame: isTopFrame(),
        frameDepth: getFrameDepth(),
        siteFromHostname,
        siteFromIframe,
        iframeCount: iframeSignals.total,
        relevantIframeCount: iframeSignals.relevantCount,
        visibleRelevantIframeCount: iframeSignals.visibleRelevantCount || 0,
        hasDocumentElement: Boolean(document.documentElement),
        hasBody: Boolean(document.body),
        expectedDomRootDetected: phaseDetector.detectExpectedDomRoot(),
        visibleTextLength: visibleText.length,
        language: languageDiagnosis,
        phaseCandidates: phaseDiagnosis.candidates,
        noDetectionReason: phaseDiagnosis.noDetectionReason
      }
    };
  }

  function scoreState(state) {
    const rankedPhases = {
      unknown: 0,
      dashboard: 1,
      iframe_entry: 2,
      selfie_stage: 3,
      loading_after_continue: 4,
      return_to_selfie: 5,
      block_read_ready: 6,
      final_submit_ready: 7,
      final_result_ready: 8
    };
    const phaseScore = rankedPhases[state.phase] || 0;
    const signalScore =
      (state.signals?.blockStrong ? 4 : 0) +
      (state.signals?.finalSuccessVisible ? 5 : 0) +
      (state.signals?.userAvatarVisible ? 3 : 0) +
      (state.iframeSignals?.hasVisibleRelevantIframe ? 2 : 0);
    return phaseScore * 10 + signalScore;
  }

  function getBestChildState() {
    let best = null;
    for (const state of childFrameStates.values()) {
      if (!best || scoreState(state) > scoreState(best)) {
        best = state;
      }
    }
    return best;
  }

  function rememberKnownFields(state) {
    if (state.site && state.site !== "unknown") {
      stateMemory.site = state.site;
    }
    if (state.lang && state.lang !== "unknown") {
      stateMemory.lang = state.lang;
    }
    if (state.frameRole) {
      stateMemory.frameRole = state.frameRole;
    }
    if (state.frameUrl) {
      stateMemory.frameUrl = state.frameUrl;
    }
    if (state.phase && state.phase !== "unknown") {
      stateMemory.phase = state.phase;
      stateMemory.phaseAt = state.observedAt || nowIso();
    }
  }

  function updatePhaseHistory(state) {
    if (!state.phase || state.phase === "unknown") {
      return;
    }
    const lastEntry = phaseHistory[phaseHistory.length - 1];
    if (lastEntry && lastEntry.phase === state.phase && lastEntry.frameRole === state.frameRole && lastEntry.frameUrl === state.frameUrl) {
      lastEntry.observedAt = state.observedAt || nowIso();
      return;
    }
    phaseHistory.push({
      phase: state.phase,
      observedAt: state.observedAt || nowIso(),
      frameRole: state.frameRole,
      frameUrl: state.frameUrl,
      site: state.site || "unknown",
      lang: state.lang || "unknown"
    });
    while (phaseHistory.length > 8) {
      phaseHistory.shift();
    }
  }

  function buildSignals(derived, own, bestChild) {
    const returnToSelfie = derived.phase === "return_to_selfie";
    return {
      fileInputVisible: Boolean(derived.selfieSignals?.fileInputVisible),
      userAvatarVisible: Boolean(derived.selfieSignals?.userAvatarVisible),
      continueCount: derived.selfieSignals?.continueCount || 0,
      selfieTextVisible: Boolean(derived.selfieSignals?.selfieTextVisible),
      selfieStrong: Boolean(derived.selfieSignals?.strong),
      borrowedCount: derived.accountSignals?.borrowedCount || 0,
      ownCount: derived.accountSignals?.ownCount || 0,
      accountOptionsVisible: (derived.accountSignals?.borrowedCount || 0) > 0 || (derived.accountSignals?.ownCount || 0) > 0,
      relevantIframeCount: own.iframeSignals?.relevantCount || 0,
      blockStrong: Boolean(derived.blockSignals?.strong),
      blockReady: Boolean(derived.blockSignals?.ready),
      blockPrice: Boolean(derived.blockSignals?.hasPrice),
      blockStation: Boolean(derived.blockSignals?.hasStation),
      blockDuration: Boolean(derived.blockSignals?.hasDuration),
      blockContainerVisible: Boolean(derived.blockSignals?.hasContainer),
      finalSubmitVisible: Boolean(derived.finalSignals?.submitVisible),
      finalSuccessVisible: Boolean(derived.finalSignals?.successVisible),
      loadingVisible: Boolean(derived.processingSignals?.loadingVisible),
      loadingStrong: Boolean(derived.processingSignals?.loadingStrong),
      iframeActive: own.iframeSignals?.hasVisibleRelevantIframe || Boolean(bestChild),
      returnToSelfie
    };
  }

  function maybePromoteReturnToSelfie(state) {
    const previousPhase = stateMemory.phase;
    if (state.phase === "selfie_stage" && previousPhase === "loading_after_continue") {
      return {
        ...state,
        phase: "return_to_selfie"
      };
    }
    return state;
  }

  function buildTopLevelState() {
    const own = maybePromoteReturnToSelfie(getOwnSnapshot());
    const bestChild = getBestChildState();
    const derived = bestChild && bestChild.phase !== "unknown" ? bestChild : own;
    rememberKnownFields(derived);
    updatePhaseHistory(derived);

    return {
      version: "0.2.0",
      observedAt: nowIso(),
      site: derived.site || own.site || bestChild?.site || stateMemory.site,
      lang: derived.lang || own.lang || bestChild?.lang || stateMemory.lang,
      phase: derived.phase || "unknown",
      lastValidPhase: stateMemory.phase,
      lastValidPhaseAt: stateMemory.phaseAt,
      lastDetectedSite: stateMemory.site,
      lastDetectedLang: stateMemory.lang,
      lastDetectedFrameRole: stateMemory.frameRole,
      lastDetectedFrameUrl: stateMemory.frameUrl,
      frameRole: own.frameRole,
      frameUrl: own.frameUrl,
      href: own.href,
      origin: own.origin,
      hostname: own.hostname,
      isTopFrame: own.isTopFrame,
      frameDepth: own.frameDepth,
      iframeActive: own.iframeSignals.hasVisibleRelevantIframe || Boolean(bestChild),
      iframeCount: own.iframeSignals.relevantCount,
      visibleIframeCount: own.iframeSignals.visibleRelevantCount || 0,
      serviceWorkerAlive: runtimeAlive,
      overlayEnabled: shouldShowOverlay(),
      activeFrame: bestChild
        ? {
            site: bestChild.site,
            lang: bestChild.lang,
            phase: bestChild.phase,
            frameRole: bestChild.frameRole,
            frameUrl: bestChild.frameUrl
          }
        : null,
      phaseHistory: phaseHistory.slice().reverse(),
      signals: buildSignals(derived, own, bestChild),
      diagnostics: {
        url: own.frameUrl,
        href: own.href,
        origin: own.origin,
        hostname: own.hostname,
        isTopFrame: own.isTopFrame,
        frameDepth: own.frameDepth,
        iframeCount: own.iframeSignals.total,
        relevantIframeCount: own.iframeSignals.relevantCount,
        visibleRelevantIframeCount: own.iframeSignals.visibleRelevantCount || 0,
        expectedDomRootDetected: own.diagnostics?.expectedDomRootDetected || false,
        hasDocumentElement: own.diagnostics?.hasDocumentElement || false,
        hasBody: own.diagnostics?.hasBody || false,
        siteFromHostname: own.diagnostics?.siteFromHostname || "unknown",
        siteFromIframe: own.diagnostics?.siteFromIframe || "unknown",
        phaseCandidates: derived.phaseDiagnosis?.candidates || own.diagnostics?.phaseCandidates || [],
        noDetectionReason: derived.phaseDiagnosis?.noDetectionReason || own.diagnostics?.noDetectionReason || null,
        visibleTextLength: own.visibleTextLength || 0,
        childFrameCount: childFrameStates.size
      },
      raw: {
        ownPhase: own.phase,
        childFrameCount: childFrameStates.size
      }
    };
  }

  function publishState(state) {
    publishStateMarkers(state);
    persistLatestState(state);
    explorer?.captureSnapshot(state);
    if (shouldShowOverlay()) {
      if (global.top === global) {
        overlay.renderOverlay(state);
      } else {
        overlay.renderIframeOverlay(state);
      }
    }
    const signature = [
      state.site,
      state.lang,
      state.phase,
      state.lastValidPhase,
      state.frameRole,
      state.iframeActive,
      state.signals?.loadingStrong,
      state.signals?.blockReady,
      state.signals?.finalSuccessVisible
    ].join("|");
    if (signature !== lastPublishedSignature) {
      lastPublishedSignature = signature;
      console.info("[auto-he-llegado] state updated", {
        site: state.site,
        lang: state.lang,
        phase: state.phase,
        lastValidPhase: state.lastValidPhase,
        signals: state.signals,
        frame: state.frameRole,
        url: state.diagnostics?.url,
        origin: state.diagnostics?.origin,
        hostname: state.diagnostics?.hostname,
        isTopFrame: state.diagnostics?.isTopFrame,
        frameDepth: state.diagnostics?.frameDepth,
        phaseCandidates: state.diagnostics?.phaseCandidates,
        noDetectionReason: state.diagnostics?.noDetectionReason
      });
    }
  }

  function emitFrameState() {
    if (global.top === global) {
      return;
    }
    const state = maybePromoteReturnToSelfie(getOwnSnapshot());
    rememberKnownFields(state);
    updatePhaseHistory(state);
    const payload = {
      ...state,
      serviceWorkerAlive: runtimeAlive,
      overlayEnabled: shouldShowOverlay(),
      phaseHistory: phaseHistory.slice().reverse(),
      signals: buildSignals(state, state, null),
      lastValidPhase: stateMemory.phase,
      lastValidPhaseAt: stateMemory.phaseAt,
      diagnostics: state.diagnostics
    };
    global.top.postMessage(
      {
        source: "auto-he-llegado-extension-frame-state",
        payload
      },
      "*"
    );
    publishState(payload);
  }

  function updateState() {
    publishPing();
    if (global.location.href !== lastUrl) {
      lastUrl = global.location.href;
      scheduleUpdate("url_change");
    }
    if (global.top === global) {
      publishState(buildTopLevelState());
    } else {
      emitFrameState();
    }
  }

  function scheduleUpdate(_reason) {
    if (updateTimer !== null) {
      global.clearTimeout(updateTimer);
    }
    updateTimer = global.setTimeout(() => {
      updateTimer = null;
      updateState();
    }, 40);
  }

  function installObservers() {
    const observer = new MutationObserver(() => scheduleUpdate("mutation"));
    observer.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeFilter: ["class", "style", "hidden", "aria-hidden", "aria-busy", "disabled", "src", "title", "data-state"]
    });
    ["load", "pageshow", "hashchange", "popstate"].forEach((eventName) => {
      global.addEventListener(eventName, () => scheduleUpdate(eventName), true);
    });
    ["click", "input", "change", "submit"].forEach((eventName) => {
      document.addEventListener(eventName, () => scheduleUpdate(eventName), true);
    });
    document.addEventListener("visibilitychange", () => scheduleUpdate("visibilitychange"), true);
    backupTimer = global.setInterval(() => updateState(), 2500);
  }

  global.addEventListener("message", (event) => {
    const data = event.data;
    if (global.top !== global || !data || data.source !== "auto-he-llegado-extension-frame-state") {
      return;
    }
    const payload = normalizeChildState(data.payload);
    if (!payload) {
      return;
    }
    childFrameStates.set(payload.frameUrl, payload);
    scheduleUpdate("frame_message");
  });

  try {
    explorer?.initialize();
    if (global.chrome?.runtime?.sendMessage) {
      global.chrome.runtime.sendMessage({ type: "auto-he-llegado:ping" }, (response) => {
        const runtimeError = global.chrome?.runtime?.lastError;
        if (runtimeError) {
          runtimeAlive = false;
          console.warn("[auto-he-llegado] runtime ping error", runtimeError.message);
          return;
        }
        runtimeAlive = Boolean(response?.ok);
        console.info("[auto-he-llegado] runtime ping ok", response);
        scheduleUpdate("runtime_ping");
      });
    }
  } catch (error) {
    runtimeAlive = false;
    console.warn("[auto-he-llegado] runtime ping threw", error);
  }

  installObservers();
  scheduleUpdate("bootstrap");
})(window);
