import type { Metadata } from "next";
import { Providers } from "./providers";
import { AppLayout } from "@/components/layout/AppLayout";
import { SceneBasketProvider } from "@/features/basket/useSceneBasket";
import { BasketPanel } from "@/features/basket/BasketPanel";
import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Heimdex - Video Search",
  description: "Search your video library with natural language",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <Providers>
          <SceneBasketProvider>
            <AppLayout>{children}</AppLayout>
            <BasketPanel />
          </SceneBasketProvider>
        </Providers>
      </body>
    </html>
  );
}
