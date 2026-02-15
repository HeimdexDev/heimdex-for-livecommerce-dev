import { DevicesSettings } from "@/features/devices";
import { AuthGuard } from "@/components/AuthGuard";

export default function DevicesPage() {
  return (
    <AuthGuard>
      <div className="max-w-7xl mx-auto px-4 py-8">
        <DevicesSettings />
      </div>
    </AuthGuard>
  );
}
