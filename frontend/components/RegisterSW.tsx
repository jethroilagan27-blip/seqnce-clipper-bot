"use client";

import { useEffect } from "react";

// Registers the service worker (public/sw.js) that makes the site installable as a phone app.
// Only in the real (built) site: during development a worker would just get in the way.
export default function RegisterSW() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* not installable here (e.g. plain http): the site still works normally */
    });
  }, []);
  return null;
}
