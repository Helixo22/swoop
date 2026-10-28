// Swoop browser integration: hands browser downloads and "Download with Swoop"
// link clicks to the Swoop native messaging host. If Swoop is unavailable the
// browser keeps the download, so nothing is ever lost.

const api = globalThis.browser ?? globalThis.chrome;
const HOST = "io.github.swoop";
const MENU_ID = "swoop-download";
const SUPPORTED_URL = /^(https?|ftp):\/\//i;

function basename(path) {
  return path ? path.split(/[\\/]/).pop() || undefined : undefined;
}

async function sendToSwoop(url, filename) {
  const message = { action: "download", url };
  if (filename) message.filename = filename;
  const reply = await api.runtime.sendNativeMessage(HOST, message);
  if (!reply?.ok) throw new Error(reply?.error ?? "no reply from Swoop");
}

function shouldIntercept(item) {
  // Leave alone downloads owned by other extensions (Chromium only reports
  // byExtensionId), private-window downloads and items not actually starting.
  if (item.byExtensionId || item.incognito || item.state !== "in_progress") return false;
  return SUPPORTED_URL.test(item.finalUrl || item.url); // blob:, data:, file: stay
}

api.downloads.onCreated.addListener(async (item) => {
  if (!shouldIntercept(item)) return;
  await api.downloads.pause(item.id).catch(() => {});
  try {
    await sendToSwoop(item.finalUrl || item.url, basename(item.filename));
  } catch (error) {
    console.warn("Swoop unavailable, the browser keeps the download:", error);
    await api.downloads.resume(item.id).catch(() => {});
    return;
  }
  try {
    await api.downloads.cancel(item.id);
    await api.downloads.erase({ id: item.id });
  } catch (error) {
    // Swoop has it already; the browser download may have finished meanwhile.
    console.warn("Swoop took the download but the browser copy remains:", error);
  }
});

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({ id: MENU_ID, title: "Download with Swoop", contexts: ["link"] });
});

api.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID || !SUPPORTED_URL.test(info.linkUrl ?? "")) return;
  sendToSwoop(info.linkUrl).catch((error) => console.warn("Swoop rejected the link:", error));
});
