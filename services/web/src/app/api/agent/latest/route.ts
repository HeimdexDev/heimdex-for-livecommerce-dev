import { NextResponse } from "next/server";
import { fetchManifest, toPublicManifest } from "@/lib/agentUpdates";

export const dynamic = "force-dynamic";

/**
 * GET /api/agent/latest
 *
 * Proxies the agent update manifest. Returns a sanitised version that
 * excludes internal download URLs (the client uses /api/agent/download
 * for the actual redirect).
 */
export async function GET() {
  try {
    const manifest = await fetchManifest();
    const publicManifest = toPublicManifest(manifest);

    return NextResponse.json(publicManifest, {
      headers: {
        "Cache-Control": "public, max-age=60, stale-while-revalidate=120",
      },
    });
  } catch {
    return NextResponse.json(
      {
        error: "에이전트 업데이트 정보를 가져올 수 없습니다.",
        fallback_url: "https://github.com/jlee-heimdex/heimdex-agent/releases",
      },
      { status: 503 },
    );
  }
}
