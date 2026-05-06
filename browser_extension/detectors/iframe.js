(function initIframeDetector(global) {
  if (global.AutoHeLlegadoIframeDetector) {
    return;
  }

  const common = global.AutoHeLlegadoObserverCommon;

  function collectIframeSignals() {
    const frames = Array.from(document.querySelectorAll("iframe"));
    const relevantFrames = frames
      .map((frame, index) => {
        const src = frame.getAttribute("src") || "";
        const title = frame.getAttribute("title") || "";
        const name = frame.getAttribute("name") || "";
        const ariaLabel = frame.getAttribute("aria-label") || "";
        const label = `${src} ${title} ${name} ${ariaLabel}`;
        const normalized = common.normalizeText(label);
        const relevant =
          normalized.includes("paripe.io/imhere-light") ||
          normalized.includes("imhere") ||
          normalized.includes("he llegado") ||
          normalized.includes("i'm here") ||
          normalized.includes("ive arrived") ||
          normalized.includes("eu cheguei") ||
          normalized.includes("instant");
        return {
          index,
          src,
          title,
          relevant,
          visible: common.isNodeVisible(frame)
        };
      })
      .filter((item) => item.relevant);

    const activeElement = document.activeElement;
    const activeIframe =
      activeElement && activeElement.tagName === "IFRAME"
        ? relevantFrames.find((frame) => frames[frame.index] === activeElement) || null
        : null;
    const visibleRelevantFrames = relevantFrames.filter((frame) => frame.visible);

    return {
      total: frames.length,
      relevantCount: relevantFrames.length,
      visibleRelevantCount: visibleRelevantFrames.length,
      relevantFrames,
      visibleRelevantFrames,
      hasRelevantIframe: relevantFrames.length > 0,
      hasVisibleRelevantIframe: visibleRelevantFrames.length > 0,
      activeIframe
    };
  }

  global.AutoHeLlegadoIframeDetector = {
    collectIframeSignals
  };
})(window);
