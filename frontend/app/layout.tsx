import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import InlineScript from "@/components/InlineScript";
import RegisterSW from "@/components/RegisterSW";
import { DEFAULT_THEME, THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Seqnce – AI short-form video editor",
  description: "Upload raw footage and get an automatically edited vertical short.",
  applicationName: "Seqnce",
  appleWebApp: { capable: true, title: "Seqnce", statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
};

// Phones: full-width layout, the dark colour behind the status bar, and the page may draw under a notch (see globals.css).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0b0b10",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      data-theme={DEFAULT_THEME}
      suppressHydrationWarning // the script below may change data-theme before React starts
    >
      <head>
        <InlineScript html={THEME_SCRIPT} />
      </head>
      <body className="min-h-full flex flex-col">
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
