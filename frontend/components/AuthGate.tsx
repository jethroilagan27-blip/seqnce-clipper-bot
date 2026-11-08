"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  JOB_STORAGE_KEY,
  getHealth,
  getMe,
  loadStoredToken,
  logout,
  setAuthToken,
  setMediaToken,
  setUnauthorizedHandler,
  type AuthUser,
  type Session,
} from "@/lib/api";
import LoginView from "./LoginView";
import Shell from "./Shell";

export type AccountInfo = {
  /** null when the server doesn't use accounts (local use). */
  user: AuthUser | null;
  /** Re-read the user's quota (call after an upload or a chat message). */
  refresh: () => void;
  signOut: () => void;
};

const MEDIA_REFRESH_MS = 60 * 60 * 1000; // media tokens last 6 h; renew hourly

// Shows the app straight away when the server has no accounts; otherwise a sign-in screen first.
export default function AuthGate({ children }: { children: (account: AccountInfo) => ReactNode }) {
  const [phase, setPhase] = useState<"loading" | "login" | "ready" | "offline">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [required, setRequired] = useState(false); // does this server use accounts at all?
  const [signupOpen, setSignupOpen] = useState(false); // can anyone create an account, or is an invite code needed?

  const refresh = useCallback(() => {
    if (!required) return;
    getMe()
      .then((me) => {
        setUser(me.user);
        setMediaToken(me.media_token);
      })
      .catch(() => {}); // a 401 is handled by the unauthorized handler
  }, [required]);

  const toLogin = useCallback((message: string | null) => {
    setAuthToken(null);
    setUser(null);
    setNotice(message);
    setPhase("login");
    try {
      localStorage.removeItem(JOB_STORAGE_KEY); // don't resume the previous person's job
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => toLogin("Your session has ended. Please sign in again."));
    return () => setUnauthorizedHandler(null);
  }, [toLogin]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const health = await getHealth();
        if (cancelled) return;
        setRequired(health.auth_required);
        setSignupOpen(Boolean(health.signup_open));
        if (!health.auth_required) {
          setPhase("ready");
          return;
        }
        if (!loadStoredToken()) {
          setPhase("login");
          return;
        }
        const me = await getMe();
        if (cancelled) return;
        setUser(me.user);
        setMediaToken(me.media_token);
        setPhase("ready");
      } catch {
        if (cancelled) return;
        // 401 already routed to the login screen by the handler; anything else means the server is unreachable
        setPhase((p) => (p === "login" ? p : "offline"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // keep the media token (and quota) fresh while the tab stays open
  useEffect(() => {
    if (phase !== "ready" || !required) return;
    const t = setInterval(refresh, MEDIA_REFRESH_MS);
    return () => clearInterval(t);
  }, [phase, required, refresh]);

  function onSession(s: Session) {
    setAuthToken(s.token);
    setMediaToken(s.media_token);
    setUser(s.user);
    setNotice(null);
    setPhase("ready");
  }

  function signOut() {
    void logout();
    toLogin(null);
  }

  if (phase === "loading")
    return (
      <Shell user={null}>
        <p className="text-center text-sm text-white/40">Connecting…</p>
      </Shell>
    );

  if (phase === "offline")
    return (
      <Shell user={null}>
      <div className="space-y-4 text-center">
        <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          Can&apos;t reach the Seqnce server. Is the backend running?
        </p>
        <button
          onClick={() => {
            setPhase("loading");
            setAttempt((n) => n + 1);
          }}
          className="rounded-xl border border-white/20 px-5 py-2.5 text-sm hover:bg-white/5"
        >
          Try again
        </button>
      </div>
      </Shell>
    );

  if (phase === "login")
    return (
      <Shell user={null}>
        <LoginView onSession={onSession} notice={notice} openSignup={signupOpen} />
      </Shell>
    );

  return <>{children({ user, refresh, signOut })}</>;
}
