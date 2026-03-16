"use client";

import { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import { ApiClientProvider } from "@/lib/api";
import { OrgSettingsProvider } from "@/lib/orgSettings";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <AuthProvider>
      <ApiClientProvider>
        <OrgSettingsProvider>
          {children}
        </OrgSettingsProvider>
      </ApiClientProvider>
    </AuthProvider>
  );
}
