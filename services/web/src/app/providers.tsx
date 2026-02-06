"use client";

import { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import { ApiClientProvider } from "@/lib/api";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <AuthProvider>
      <ApiClientProvider>
        {children}
      </ApiClientProvider>
    </AuthProvider>
  );
}
