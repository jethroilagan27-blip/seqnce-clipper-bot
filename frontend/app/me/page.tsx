"use client";

import AuthGate from "@/components/AuthGate";
import MeView from "@/components/MeView";

// The "Me" page lives at /me: account, personalization, custom API key, installing the app, sign out.
export default function MePage() {
  return <AuthGate>{(account) => <MeView account={account} />}</AuthGate>;
}
