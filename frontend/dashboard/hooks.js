// App-wide hooks: PWA install and connectivity, colour theme, sticky header offsets.
import { useCallback, useEffect, useState } from "react";
import { readStored, writeStored } from "./api.js";

// PWA install prompt (Chrome/Edge) and connectivity state.
export function usePwa() {
  const [installEvent, setInstallEvent] = useState(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const onPrompt = (event) => {
      event.preventDefault();
      setInstallEvent(event);
    };
    const onInstalled = () => setInstallEvent(null);
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  const install = useCallback(async () => {
    if (!installEvent) return;
    installEvent.prompt();
    await installEvent.userChoice.catch(() => null);
    setInstallEvent(null);
  }, [installEvent]);
  return { canInstall: !!installEvent, install, online };
}

export function useTheme() {
  const [theme, setTheme] = useState(() => readStored("theme", null)
    || (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writeStored("theme", theme);
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}

export function useStickyHeaderOffsets() {
  useEffect(() => {
    const app = document.querySelector(".app");
    if (!app) return;

    const root = document.documentElement;
    const resizeObserver = new ResizeObserver(update);
    const mutationObserver = new MutationObserver(update);
    const observed = new Set();

    function update() {
      const topbar = app.querySelector(".topbar");
      const filters = app.querySelector(".filters");
      for (const element of [topbar, filters]) {
        if (element && !observed.has(element)) {
          observed.add(element);
          resizeObserver.observe(element);
        }
      }

      const topbarHeight = topbar?.getBoundingClientRect().height || 0;
      const filtersHeight = filters?.getBoundingClientRect().height || 0;
      root.style.setProperty("--sticky-topbar-height", `${topbarHeight}px`);
      root.style.setProperty("--sticky-filters-height", `${filtersHeight}px`);
    }

    mutationObserver.observe(app, { childList: true, subtree: true });
    window.addEventListener("resize", update);
    update();
    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener("resize", update);
      root.style.removeProperty("--sticky-topbar-height");
      root.style.removeProperty("--sticky-filters-height");
    };
  }, []);
}
