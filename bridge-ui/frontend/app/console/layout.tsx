import type { Metadata } from "next";
import "./console.css";

export const metadata: Metadata = {
  title: "Bridge Console",
  description: "Firewall-style operations console for the Bridge platform",
};

// Additive route segment. The root layout (app/layout.tsx) already wraps every
// route in AppContextProvider + ConfirmProvider, so the console inherits global
// state without re-wrapping. The `.bridge-console` scope class confines every
// rule in console.css to this subtree — the legacy app is never touched.
export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <div className="bridge-console">{children}</div>;
}
