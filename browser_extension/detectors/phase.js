(function initPhaseDetector(global) {
  if (global.AutoHeLlegadoPhaseDetector) {
    return;
  }

  const common = global.AutoHeLlegadoObserverCommon;

  function getVisibleActionButtons() {
    return common.findMatchingElements(
      "button, [role='button'], a, input[type='button'], input[type='submit']",
      (node) => common.isNodeVisible(node)
    );
  }

  function getNodeActionText(node) {
    if (!node) {
      return "";
    }
    const directValue =
      typeof node.value === "string" && node.value.trim()
        ? node.value
        : "";
    return common.normalizeText(directValue || common.safeText(node));
  }

  function countVisibleActionButtons(labels) {
    const normalizedLabels = labels.map((label) => common.normalizeText(label));
    let count = 0;
    for (const node of getVisibleActionButtons()) {
      const text = getNodeActionText(node);
      if (text && normalizedLabels.includes(text)) {
        count += 1;
      }
    }
    return count;
  }

  function countAllVisibleActionButtons() {
    return getVisibleActionButtons().length;
  }

  function detectPhase(snapshot) {
    return diagnosePhase(snapshot).phase;
  }

  function diagnosePhase(snapshot) {
    const retryVisible = snapshot.selfieSignals.retryCount > 0;
    const selfieVisible = Boolean(snapshot.selfieSignals.strong);
    const loadingVisible = Boolean(snapshot.processingSignals.loadingStrong);
    const blockVisible = Boolean(snapshot.blockSignals.ready);
    const blockContextVisible = Boolean(snapshot.blockSignals.contextReady);
    const finalSubmitVisible = Boolean(snapshot.finalSignals.submitVisible && blockContextVisible && !selfieVisible && !loadingVisible);
    const resultVisible = Boolean(snapshot.finalSignals.successVisible && !selfieVisible && !loadingVisible);

    const candidates = [
      {
        phase: "return_to_selfie",
        matched: retryVisible,
        reason: retryVisible ? "retry_button_visible" : "retry_button_missing"
      },
      {
        phase: "selfie_stage",
        matched: selfieVisible,
        reason: selfieVisible ? "selfie_signal_visible" : "selfie_signal_missing"
      },
      {
        phase: "loading_after_continue",
        matched: Boolean(loadingVisible && !selfieVisible),
        reason: loadingVisible && !selfieVisible ? "loading_signal_visible" : "loading_signal_missing"
      },
      {
        phase: "block_read_ready",
        matched: Boolean(blockVisible && !selfieVisible && !loadingVisible),
        reason: blockVisible && !selfieVisible && !loadingVisible ? "block_context_visible" : "block_signal_missing"
      },
      {
        phase: "final_submit_ready",
        matched: finalSubmitVisible,
        reason: finalSubmitVisible ? "final_submit_in_block_context" : "final_submit_missing"
      },
      {
        phase: "final_result_ready",
        matched: resultVisible,
        reason: resultVisible ? "final_result_text_visible" : "final_result_text_missing"
      },
      {
        phase: "iframe_entry",
        matched: Boolean(snapshot.iframeSignals.hasVisibleRelevantIframe || snapshot.iframeSignals.hasRelevantIframe),
        reason: snapshot.iframeSignals.hasVisibleRelevantIframe || snapshot.iframeSignals.hasRelevantIframe ? "relevant_iframe_detected" : "relevant_iframe_missing"
      },
      {
        phase: "dashboard",
        matched: Boolean(snapshot.dashboardSignals.dashboardVisible),
        reason: snapshot.dashboardSignals.dashboardVisible ? "dashboard_visible" : "dashboard_not_visible"
      }
    ];

    const selected = candidates.find((candidate) => candidate.matched) || null;
    return {
      phase: selected ? selected.phase : "unknown",
      candidates,
      noDetectionReason: selected ? null : inferNoDetectionReason(snapshot)
    };
  }

  function inferNoDetectionReason(snapshot) {
    if (!document.documentElement || !document.body) {
      return "missing_dom_root";
    }
    if ((snapshot.visibleTextLength || 0) === 0) {
      return "empty_visible_text";
    }
    if (snapshot.iframeSignals.total > 0 && !snapshot.iframeSignals.hasRelevantIframe) {
      return "iframes_present_but_not_relevant";
    }
    if (
      snapshot.selfieSignals.strong === false &&
      snapshot.processingSignals.loadingStrong === false &&
      snapshot.blockSignals.ready === false &&
      snapshot.finalSignals.successVisible === false &&
      snapshot.dashboardSignals.dashboardVisible === false
    ) {
      return "no_text_or_element_signals";
    }
    return "phase_rules_not_matched";
  }

  function detectExpectedDomRoot() {
    return Boolean(
      document.body &&
        (
          document.querySelector("main") ||
          document.querySelector("[role='main']") ||
          document.querySelector("#root") ||
          document.querySelector("#app") ||
          document.querySelector("[id*='app']") ||
          document.querySelector("[class*='app']")
        )
    );
  }

  function detectDashboardSignals() {
    const labels = [
      "Cuenta prestada",
      "Cuenta propia",
      "He llegado",
      "Selfie en ruta",
      "Borrowed account",
      "Own account",
      "I'm here",
      "Route selfie",
      "Conta emprestada",
      "Conta propria",
      "Eu cheguei",
      "Selfie em rota"
    ];
    return {
      dashboardVisible: countVisibleActionButtons(labels) >= 2
    };
  }

  function detectSelfieSignals() {
    const visibleText = common.collectVisibleText(document.body);
    const normalizedText = common.normalizeText(visibleText);
    const fileInputs = Array.from(document.querySelectorAll("input[type='file']"));
    const visibleFileInputs = fileInputs.filter((node) => common.isNodeVisible(node));
    const avatarNode = document.querySelector("#user_avatar");
    const avatarVisible = avatarNode !== null && common.isNodeVisible(avatarNode);
    const continueCount = countVisibleActionButtons(["Continuar", "Continue", "Prosseguir", "Siguiente"]);
    const retryCount = countVisibleActionButtons(["Volver a intentar", "Try again", "Tentar novamente"]);
    const selfieTextVisible = common.hasAnyToken(normalizedText, ["selfie", "foto", "camara", "camera"]);
    const continuePromptVisible = common.hasAnyToken(normalizedText, ["para continuar", "to continue", "para prosseguir"]);
    const takePhotoVisible = common.hasAnyToken(normalizedText, ["tomate una foto", "tomate foto", "take a selfie", "tirar uma foto"]);
    const cameraVisible = common.hasAnyToken(normalizedText, ["camara", "camera"]);
    const modalContinueVisible = continueCount > 0 && (continuePromptVisible || takePhotoVisible || selfieTextVisible);
    const strong =
      visibleFileInputs.length > 0 ||
      avatarVisible ||
      cameraVisible ||
      modalContinueVisible ||
      Boolean(continuePromptVisible && takePhotoVisible);

    return {
      fileInputCount: fileInputs.length,
      visibleFileInputCount: visibleFileInputs.length,
      fileInputVisible: visibleFileInputs.length > 0,
      userAvatarVisible: visibleFileInputs.length > 0 || avatarVisible || selfieTextVisible,
      continueCount,
      retryCount,
      continuePromptVisible,
      takePhotoVisible,
      cameraVisible,
      selfieTextVisible,
      strong
    };
  }

  function detectAccountSignals() {
    return {
      borrowedCount: countVisibleActionButtons(["Cuenta prestada", "Borrowed account", "Conta emprestada"]),
      ownCount: countVisibleActionButtons(["Cuenta propia", "Own account", "Personal account", "Conta propria"])
    };
  }

  function detectProcessingSignals(visibleText) {
    const busyNode =
      document.querySelector("[aria-busy='true'], [role='progressbar'], [class*='loading'], [class*='spinner']") !== null;
    const loadingTextVisible = common.hasAnyToken(visibleText, [
      "cargando",
      "loading",
      "procesando",
      "processing",
      "processando",
      "validando",
      "verificando"
    ]);
    return {
      loadingVisible: loadingTextVisible || busyNode,
      loadingStrong: busyNode || loadingTextVisible
    };
  }

  function detectBlockSignals(visibleText) {
    const text = common.normalizeText(visibleText);
    const hasPrice = common.hasAnyToken(text, ["pago", "precio", "monto", "$", "bs", "usd"]);
    const hasStation = common.hasAnyToken(text, ["estacion", "estación", "station", "parada"]);
    const hasDuration = common.hasAnyToken(text, ["duracion", "duración", "horario", "minutes", "minutos"]);
    const finalSubmitVisible = countVisibleActionButtons(["He llegado", "I'm here", "I've arrived", "Eu cheguei", "Cheguei"]) > 0;
    const fieldCount = [hasPrice, hasStation, hasDuration].filter(Boolean).length;
    const contextReady = hasPrice && hasStation && (hasDuration || finalSubmitVisible);
    const strong = contextReady && fieldCount >= 2;

    return {
      hasPrice,
      hasStation,
      hasDuration,
      fieldCount,
      hasContainer: strong,
      informativeTextVisible: strong,
      informativeWithoutButtons: false,
      finalSubmitVisible,
      contextReady,
      strong,
      ready: strong
    };
  }

  function detectFinalSignals(visibleText) {
    const successVisible = common.hasAnyToken(visibleText, [
      "aprobado",
      "rechazado",
      "exitoso",
      "exitosamente",
      "completado",
      "approved",
      "rejected",
      "successful",
      "completed"
    ]);
    const submitCount = countVisibleActionButtons(["He llegado", "I'm here", "I've arrived", "Eu cheguei", "Cheguei"]);
    return {
      successVisible,
      submitCount,
      submitVisible: submitCount > 0
    };
  }

  global.AutoHeLlegadoPhaseDetector = {
    detectExpectedDomRoot,
    detectAccountSignals,
    detectBlockSignals,
    detectDashboardSignals,
    detectFinalSignals,
    detectPhase,
    diagnosePhase,
    detectProcessingSignals,
    detectSelfieSignals
  };
})(window);
