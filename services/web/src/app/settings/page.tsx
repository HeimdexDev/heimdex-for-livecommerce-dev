import { SettingsPage } from "@/features/settings";
import { AuthGuard } from "@/components/AuthGuard";

export default function Settings() {
  return (
    <AuthGuard>
      <SettingsPage />
    </AuthGuard>
  );
}
