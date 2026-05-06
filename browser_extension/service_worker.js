chrome.runtime.onInstalled.addListener(() => {
  console.info("[auto-he-llegado] service worker installed");
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "auto-he-llegado:ping") {
    console.info("[auto-he-llegado] runtime ping received");
    sendResponse({ ok: true, version: "0.1.1" });
    return true;
  }
  return false;
});
