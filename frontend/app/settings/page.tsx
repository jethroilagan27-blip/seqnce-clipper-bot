"use client";

import AuthGate from "@/components/AuthGate";
import SettingsView from "@/components/SettingsView";

// Account settings live at /settings (the Gemini key, installing the phone app).
export default function SettingsPage() {
  return <AuthGate>{(account) => <SettingsView account={account} />}</AuthGate>;
}
