import type { Metadata } from "next";
import Link from "next/link";
import { currentUser } from "@/lib/session";
import { signOut } from "./login/actions";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atlas Demand",
  description: "Organisations that have publicly stated a data need, and the lawful way to reach them.",
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  return (
    <html lang="en">
      <body>
        {user && (
          <header className="top">
            <Link href="/" className="brand">Atlas <span>Demand</span></Link>
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
