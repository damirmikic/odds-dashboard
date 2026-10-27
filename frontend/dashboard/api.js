// Server requests and per-browser settings (localStorage).
export async function requestJson(url, options) {
  const response = await fetch(url, options);
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
