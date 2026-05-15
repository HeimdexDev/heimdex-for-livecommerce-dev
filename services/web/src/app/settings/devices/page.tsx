import { DevicesSettings } from "@/features/devices";
import { AuthGuard } from "@/components/AuthGuard";

export default function DevicesPage() {
  return (
    <AuthGuard>
      <DevicesSettings />
    </AuthGuard>
  );
}
