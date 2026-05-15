import { PeopleSettings } from "@/features/people";
import { AuthGuard } from "@/components/AuthGuard";

export default function PeoplePage() {
  return (
    <AuthGuard>
      <PeopleSettings />
    </AuthGuard>
  );
}
