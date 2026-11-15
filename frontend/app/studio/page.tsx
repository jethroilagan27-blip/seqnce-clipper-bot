"use client";

import AuthGate from "@/components/AuthGate";
import StudioApp from "@/components/studio/StudioApp";

// Studio lives at /studio. To remove it: delete this folder, components/studio/ and the Studio tab in Shell.tsx.
export default function StudioPage() {
  return <AuthGate>{(account) => <StudioApp account={account} />}</AuthGate>;
}
