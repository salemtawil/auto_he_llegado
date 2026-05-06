(function initAutoHeLlegadoCommon(global) {
  if (global.AutoHeLlegadoObserverCommon) {
    return;
  }

  const WHITESPACE_RE = /\s+/g;

  function normalizeText(value) {
    return (value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(WHITESPACE_RE, " ")
      .trim()
      .toLowerCase();
  }

  function safeText(node) {
    if (!node) {
      return "";
    }
    if (typeof node.innerText === "string" && node.innerText.trim()) {
      return node.innerText;
    }
    if (typeof node.textContent === "string") {
      return node.textContent;
    }
    return "";
  }

  function collectVisibleText(root) {
    return safeText(root || document.body);
  }

  function isNodeVisible(node) {
    if (!node || typeof node.getBoundingClientRect !== "function") {
      return false;
    }
    const style = global.getComputedStyle ? global.getComputedStyle(node) : null;
    if (style && (style.display === "none" || style.visibility === "hidden" || style.opacity === "0")) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function countMatchingElements(selector, predicate) {
    const nodes = Array.from(document.querySelectorAll(selector));
    if (!predicate) {
      return nodes.length;
    }
    let count = 0;
    for (const node of nodes) {
      try {
        if (predicate(node)) {
          count += 1;
        }
      } catch (_error) {
        // Ignore a broken node and keep counting.
      }
    }
    return count;
  }

  function findMatchingElements(selector, predicate) {
    const nodes = Array.from(document.querySelectorAll(selector));
    if (!predicate) {
      return nodes;
    }
    return nodes.filter((node) => {
      try {
        return predicate(node);
      } catch (_error) {
        return false;
      }
    });
  }

  function textIncludesAny(text, variants) {
    const normalized = normalizeText(text);
    return variants.some((variant) => normalized.includes(normalizeText(variant)));
  }

  function countButtonsByLabels(labels) {
    return countMatchingElements(
      "button, [role='button'], a, input[type='button'], input[type='submit']",
      (node) => isNodeVisible(node) && textIncludesAny(safeText(node), labels)
    );
  }

  function getSiteFromHostname(hostname) {
    const normalized = normalizeText(hostname);
    if (normalized.includes("compinche.io")) {
      return "compinche";
    }
    if (normalized.includes("paripe.io")) {
      return "paripe";
    }
    if (normalized.includes("compinche")) {
      return "compinche";
    }
    if (normalized.includes("paripe")) {
      return "paripe";
    }
    return "unknown";
  }

  function hasAnyToken(text, tokens) {
    const normalized = normalizeText(text);
    return tokens.some((token) => normalized.includes(normalizeText(token)));
  }

  function getFlagFromCommandLine(flagName, fallback) {
    try {
      const value = global.location.search;
      void value;
    } catch (_error) {
      // ignore
    }
    return fallback;
  }

  global.AutoHeLlegadoObserverCommon = {
    collectVisibleText,
    countButtonsByLabels,
    countMatchingElements,
    findMatchingElements,
    getFlagFromCommandLine,
    getSiteFromHostname,
    hasAnyToken,
    isNodeVisible,
    normalizeText,
    safeText,
    textIncludesAny
  };
})(window);
