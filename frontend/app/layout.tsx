import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Inter, Frank_Ruhl_Libre } from "next/font/google";
import "./globals.css";

const cormorant = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-cormorant",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Hebrew face with proper nikud support.
const frank = Frank_Ruhl_Libre({
  subsets: ["hebrew", "latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-frank",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Nishmat AI — A Journey of Praise",
    template: "%s · Nishmat AI",
  },
  description:
    "A weekly journey through the words of Nishmat Kol Chai. Read the lessons, and ask anything you are wondering about.",
  openGraph: {
    title: "Nishmat AI — A Journey of Praise",
    description:
      "A weekly journey through the words of Nishmat Kol Chai.",
    type: "website",
  },
  robots: { index: true, follow: true },
  // The browser-tab mark: the same arch, cropped square.
  icons: {
    icon: [{ url: "/icon.png", type: "image/png", sizes: "64x64" }],
    apple: [{ url: "/apple-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#060518",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${cormorant.variable} ${inter.variable} ${frank.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
