(function initLanguageDetector(global) {
  if (global.AutoHeLlegadoLanguageDetector) {
    return;
  }

  const common = global.AutoHeLlegadoObserverCommon;

  const TOKENS = {
    es: [
      "cuenta prestada",
      "cuenta propia",
      "he llegado",
      "selfie en ruta",
      "continuar",
      "estacion",
      "duracion",
      "horario",
      "pago"
    ],
    en: [
      "borrowed account",
      "own account",
      "i'm here",
      "i've arrived",
      "route selfie",
      "continue",
      "station",
      "duration",
      "schedule",
      "payment"
    ],
    pt: [
      "conta emprestada",
      "conta propria",
      "eu cheguei",
      "selfie em rota",
      "selfie na rota",
      "prosseguir",
      "estacao",
      "duracao",
      "horario",
      "pagamento"
    ]
  };

  function detectLanguage(visibleText) {
    return diagnoseLanguage(visibleText).lang;
  }

  function diagnoseLanguage(visibleText) {
    const text = common.normalizeText(visibleText);
    if (!text) {
      return {
        lang: "unknown",
        reason: "no_visible_text",
        htmlLang: common.normalizeText(document.documentElement?.getAttribute("lang") || ""),
        tokenScores: {
          es: 0,
          en: 0,
          pt: 0
        }
      };
    }
    const htmlLang = common.normalizeText(document.documentElement?.getAttribute("lang") || "");
    if (htmlLang.startsWith("es")) {
      return {
        lang: "es",
        reason: "html_lang",
        htmlLang,
        tokenScores: {
          es: 0,
          en: 0,
          pt: 0
        }
      };
    }
    if (htmlLang.startsWith("en")) {
      return {
        lang: "en",
        reason: "html_lang",
        htmlLang,
        tokenScores: {
          es: 0,
          en: 0,
          pt: 0
        }
      };
    }
    if (htmlLang.startsWith("pt")) {
      return {
        lang: "pt",
        reason: "html_lang",
        htmlLang,
        tokenScores: {
          es: 0,
          en: 0,
          pt: 0
        }
      };
    }
    let bestLang = "unknown";
    let bestScore = 0;
    const tokenScores = {
      es: 0,
      en: 0,
      pt: 0
    };
    for (const [lang, tokens] of Object.entries(TOKENS)) {
      const score = tokens.reduce((total, token) => total + (text.includes(common.normalizeText(token)) ? 2 : 0), 0);
       tokenScores[lang] = score;
      if (score > bestScore) {
        bestScore = score;
        bestLang = lang;
      }
    }
    return {
      lang: bestScore >= 2 ? bestLang : "unknown",
      reason: bestScore >= 2 ? "token_score" : "insufficient_language_tokens",
      htmlLang,
      tokenScores
    };
  }

  global.AutoHeLlegadoLanguageDetector = {
    detectLanguage,
    diagnoseLanguage
  };
})(window);
