"use client";

import AuthGate from "@/components/AuthGate";
import PhotoStudio from "@/components/photos/PhotoStudio";

// Photo mode lives at /photos. To remove it: delete this folder, components/photos/ and the mode switch in Shell.tsx.
export default function PhotosPage() {
  return <AuthGate>{(account) => <PhotoStudio account={account} />}</AuthGate>;
}
