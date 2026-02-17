import { NextRequest, NextResponse } from "next/server";
import { fetchManifest, isValidPlatform } from "@/lib/agentUpdates";

export const dynamic = "force-dynamic";

/**
 * GET /api/agent/download?platform=darwin-arm64|darwin-amd64|windows-amd64
 *
 * Fetches the update manifest and 302-redirects to the actual download URL
 * for the requested platform. The redirect response uses Cache-Control:
 * no-store to prevent sticky CDN/browser caching.
 */
export async function GET(request: NextRequest) {
  const platform = request.nextUrl.searchParams.get("platform") ?? "";

  if (!isValidPlatform(platform)) {
    return NextResponse.json(
      {
        error: `유효하지 않은 플랫폼입니다: "${platform}". 사용 가능: darwin-arm64, darwin-amd64, windows-amd64`,
      },
      { status: 400 },
    );
  }

  try {
    const manifest = await fetchManifest();
    const entry = manifest.downloads[platform];

    if (!entry) {
      return NextResponse.json(
        {
          error: `해당 플랫폼의 다운로드를 찾을 수 없습니다: ${platform}`,
        },
        { status: 404 },
      );
    }

    return NextResponse.redirect(entry.url, {
      status: 302,
      headers: {
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      {
        error: "다운로드 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        fallback_url:
          "https://github.com/jlee-heimdex/heimdex-agent/releases",
      },
      { status: 503 },
    );
  }
}
