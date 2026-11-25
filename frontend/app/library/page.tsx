"use client";

import AuthGate from "@/components/AuthGate";
import LibraryView from "@/components/LibraryView";

// The library lives at /library: every video this account has made.
export default function LibraryPage() {
  return <AuthGate>{(account) => <LibraryView account={account} />}</AuthGate>;
}
