// Swoop browser integration: hands browser downloads and "Download with Swoop"
// link clicks to the Swoop native messaging host, with the request headers the
// browser would send. Cookies are forwarded only by the Firefox build and only
// for intercepted downloads, whose URL is already the final one after redirects:
// aria2 would repeat the Cookie header on any further redirect, even cross-site.
// If Swoop is unavailable the browser keeps the download, so nothing is lost.

const api = globalThis.browser ?? globalThis.chrome;
const HOST = "io.github.swoop";
const MENU_ID = "swoop-download";
const SUPPORTED_URL = /^(https?|ftp):\/\//i;

function basename(path) {
  return path ? path.split(/[\\/]/).pop() || undefined : undefined;
}

function cookieHeader(cookies) {
  return cookies.map((c) => (c.name ? `${c.name}=${c.value}` : c.value)).join("; ");
}

async function requestHeaders(url, referrer, cookieStoreId, withCookies) {
  const headers = { "User-Agent": navigator.userAgent };
  if (referrer && SUPPORTED_URL.test(referrer)) headers.Referer = referrer;
  if (withCookies && api.cookies) {
    // firstPartyDomain: null also matches cookies isolated by first-party isolation.
    const cookies = await api.cookies.getAll({ url, storeId: cookieStoreId, firstPartyDomain: null });
    if (cookies.length) headers.Cookie = cookieHeader(cookies);
  }
  return headers;
}

async function sendToSwoop(url, { filename, referrer, cookieStoreId, withCookies = false } = {}) {
  const headers = await requestHeaders(url, referrer, cookieStoreId, withCookies);
  const message = { action: "download", url, headers };
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
    await sendToSwoop(item.finalUrl || item.url, {
      filename: basename(item.filename),
      referrer: item.referrer,
      cookieStoreId: item.cookieStoreId,
      withCookies: true,
    });
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

api.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID || !SUPPORTED_URL.test(info.linkUrl ?? "")) return;
  if (tab?.incognito) return; // private browsing data never leaves the browser
  // No cookies here: a link is often a redirector to another site.
  sendToSwoop(info.linkUrl, { referrer: info.pageUrl }).catch((error) =>
    console.warn("Swoop rejected the link:", error),
  );
});
