// Server requests and per-browser settings (localStorage).
let serverDown = false;
const downListeners = new Set();

function setServerDown(value) {
  if (serverDown === value) return;
  serverDown = value;
  downListeners.forEach((listener) => listener());
}

// True while the last request failed because the server did not answer (shown as an offline banner; the boards retry by themselves).
export const serverDownStore = {
  subscribe(listener) {
    downListeners.add(listener);
    return () => downListeners.delete(listener);
  },
  get: () => serverDown,
};

export async function requestJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    setServerDown(true);
    throw new Error("Server nije dostupan, ponovo pokušavam automatski.", { cause: error });
  }
  // 502-504 come from the reverse proxy when the app behind it is down; the service worker's offline copy has this header
  const down = [502, 503, 504].includes(response.status) || !!response.headers.get("X-PB-Cache");
  setServerDown(down);
  if (down && !response.headers.get("X-PB-Cache")) throw new Error("Server nije dostupan, ponovo pokušavam automatski.");
  const result = await response.json().catch((error) => {
    if (error.name === "AbortError" || response.ok) throw error;
    return {};
  });
  if (!response.ok) throw new Error(result.error || `Zahtev nije uspeo (${response.status})`);
  // set by the service worker when it answers offline from its copy of the last good response
  const cachedAt = response.headers.get("X-PB-Cache");
  if (cachedAt && result && typeof result === "object") result.__cachedAt = cachedAt;
  return result;
}

export function readStored(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

export function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}
