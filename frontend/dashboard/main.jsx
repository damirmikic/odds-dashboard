import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./dashboard.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// PWA: service workers need a secure context (https, or http://localhost / 127.0.0.1).
// Skipped in the Vite dev server so hot reload is not served from cache.
if ("serviceWorker" in navigator && window.isSecureContext && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.warn("Service worker registration failed:", error);
    });
  });
}
