import { PersonVideosPage } from "@/features/people/components/PersonVideosPage";
import { AuthGuard } from "@/components/AuthGuard";

export default function PersonVideosRoute({
  params,
}: {
  params: { personId: string };
}) {
  return (
    <AuthGuard>
      <PersonVideosPage personClusterId={params.personId} />
    </AuthGuard>
  );
}
