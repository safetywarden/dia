import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import Brand from "@/components/brand";
import { currentUser } from "@/lib/session";
import { signOut } from "./login/actions";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "BCONZ DIA — Demand Intelligence",
  description: "Organisations that have publicly stated a data need, and the lawful way to reach them.",
  robots: { index: false, follow: false },
  icons: { apple: "/brand/bconz-icon.png" },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  return (
    <html lang="en" className={geist.className}>
      <body>
        {user && (
          <header className="top">
            <Link href="/" aria-label="BCONZ DIA home"><Brand /></Link>
            <nav>
              <Link href="/">Searches</Link>
              <Link href="/suppression">Do-not-contact</Link>
            </nav>
            <form action={signOut} className="who">
              <span className="muted">{user}</span>
              <button className="link">Sign out</button>
            </form>
          </header>
        )}
        {children}
      </body>
    </html>
  );
}
