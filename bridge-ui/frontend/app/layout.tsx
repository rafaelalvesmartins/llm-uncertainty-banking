import type { Metadata } from "next";
import "./globals.css";
import ConfirmProvider from "@/components/ConfirmProvider";
import AppContextProvider from "@/components/AppContextProvider";

export const metadata: Metadata = {
  title: "Bridge Banking AI",
  description: "Real-time view of the Bridge model-risk governance pipeline",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AppContextProvider>
          <ConfirmProvider>{children}</ConfirmProvider>
        </AppContextProvider>
      </body>
    </html>
  );
}
