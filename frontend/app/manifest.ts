import type { MetadataRoute } from "next";

// Makes the website installable as a phone app ("Add to Home Screen"): its own icon, full screen, no browser bars.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Seqnce – AI short-form video editor",
    short_name: "Seqnce",
    description: "Upload raw footage and get an automatically edited vertical short.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0b0b10",
    theme_color: "#0b0b10",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Edit a video", url: "/", description: "Send a video to be edited" },
      { name: "Studio", url: "/studio" },
    ],
  };
}
