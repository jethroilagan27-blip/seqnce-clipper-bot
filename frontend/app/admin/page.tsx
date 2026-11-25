"use client";

import AdminView from "@/components/AdminView";
import AuthGate from "@/components/AuthGate";

// The admin page lives at /admin (admins only: the server refuses everyone else).
export default function AdminPage() {
  return <AuthGate>{(account) => <AdminView account={account} />}</AuthGate>;
}
