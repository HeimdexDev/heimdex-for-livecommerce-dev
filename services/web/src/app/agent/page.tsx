"use client";

import { useEffect, useState, useCallback } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { getOrgSlug } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { AgentPlatform, AgentManifestPublic } from "@/lib/agentUpdates";

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------

function detectPlatform(): AgentPlatform | null {
  if (typeof navigator === "undefined") return null;
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("mac")) {
    // Very rough heuristic — Apple Silicon Macs report "macintosh" in UA.
    // There's no reliable way to distinguish arm64 vs x86 from UA alone,
    // so we default to arm64 (the most common Mac sold since late 2020).
    return "darwin-arm64";
  }
  if (ua.includes("win")) return "windows-amd64";
  return null;
}

// ---------------------------------------------------------------------------
// Bytes formatter
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Download button config
// ---------------------------------------------------------------------------

const PLATFORMS: {
  id: AgentPlatform;
  label: string;
  icon: string;
}[] = [
  { id: "darwin-arm64", label: "macOS (Apple Silicon)", icon: "apple" },
  { id: "darwin-amd64", label: "macOS (Intel)", icon: "apple" },
  { id: "windows-amd64", label: "Windows", icon: "windows" },
];

// ---------------------------------------------------------------------------
// Page content
// ---------------------------------------------------------------------------

function AgentPageContent() {
  const [manifest, setManifest] = useState<AgentManifestPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [detectedPlatform, setDetectedPlatform] =
    useState<AgentPlatform | null>(null);
  const [orgSlug, setOrgSlug] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    setDetectedPlatform(detectPlatform());
    setOrgSlug(getOrgSlug());
  }, []);

  const fetchLatest = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/agent/latest");
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(
          body.error || "에이전트 정보를 불러올 수 없습니다.",
        );
        return;
      }
      const data: AgentManifestPublic = await res.json();
      setManifest(data);
      setError(null);
    } catch {
      setError("네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLatest();
  }, [fetchLatest]);

  const origin =
    typeof window !== "undefined" ? window.location.origin : "";

  return (
    <div className="mx-auto max-w-3xl pt-10 pb-20">
      {/* Header */}
      <div className="mb-10">
        <h1 className="text-2xl font-bold text-gray-900">
          Heimdex 에이전트
        </h1>
        <p className="mt-2 text-gray-500">
          로컬 영상은 로컬에 두고, 검색은 웹에서
        </p>
      </div>

      {/* Download section */}
      <section className="mb-12 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">다운로드</h2>

        {loading && (
          <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
            최신 버전 확인 중...
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            <p>{error}</p>
            <a
              href="https://github.com/jlee-heimdex/heimdex-agent/releases"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block text-amber-800 underline"
            >
              GitHub Releases에서 직접 다운로드
            </a>
          </div>
        )}

        {manifest && (
          <>
            <p className="mt-2 text-sm text-gray-500">
              최신 버전:{" "}
              <span className="font-medium text-gray-700">
                v{manifest.version}
              </span>
              {manifest.release_date && (
                <span className="ml-2 text-gray-400">
                  ({manifest.release_date})
                </span>
              )}
            </p>

            <div className="mt-5 flex flex-wrap gap-3">
              {PLATFORMS.map((p) => {
                const available = manifest.platforms.includes(p.id);
                const recommended = p.id === detectedPlatform;

                return (
                  <a
                    key={p.id}
                    href={
                      available
                        ? `/api/agent/download?platform=${p.id}`
                        : undefined
                    }
                    className={cn(
                      "relative flex items-center gap-2.5 rounded-lg border px-5 py-3 text-sm font-medium transition-colors",
                      available
                        ? recommended
                          ? "border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                          : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                        : "pointer-events-none border-gray-100 bg-gray-50 text-gray-400",
                    )}
                  >
                    {p.icon === "apple" ? (
                      <AppleIcon className="h-4 w-4" />
                    ) : (
                      <WindowsIcon className="h-4 w-4" />
                    )}
                    {p.label}
                    {recommended && (
                      <span className="ml-1 rounded bg-indigo-100 px-1.5 py-0.5 text-xs font-medium text-indigo-600">
                        추천
                      </span>
                    )}
                  </a>
                );
              })}
            </div>

            {/* Details disclosure */}
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              className="mt-4 text-xs text-gray-400 hover:text-gray-600"
            >
              {showDetails ? "자세히 닫기" : "자세히 (SHA256, 파일 크기)"}
            </button>

            {showDetails && (
              <div className="mt-2 overflow-x-auto rounded border border-gray-100 bg-gray-50 p-3 text-xs text-gray-500">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="pb-1 pr-4 font-medium">플랫폼</th>
                      <th className="pb-1 pr-4 font-medium">크기</th>
                      <th className="pb-1 font-medium">SHA256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PLATFORMS.filter((p) =>
                      manifest.platforms.includes(p.id),
                    ).map((p) => {
                      const dl = manifest.downloads[p.id];
                      return (
                        <tr key={p.id} className="border-b border-gray-100 last:border-0">
                          <td className="py-1.5 pr-4">{p.label}</td>
                          <td className="py-1.5 pr-4">
                            {dl ? formatBytes(dl.size_bytes) : "-"}
                          </td>
                          <td className="py-1.5 font-mono">
                            {dl?.sha256 ? `${dl.sha256.slice(0, 16)}...` : "-"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {/* Setup instructions */}
      <section className="mb-12 rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">
          설정 방법
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          에이전트를 설치한 후 아래 단계를 따라 연결하세요.
        </p>

        <ol className="mt-5 space-y-5">
          <Step num={1} title="설치 후 실행">
            <p>
              다운로드한 파일을 설치하고 실행합니다. macOS에서는 메뉴바,
              Windows에서는 트레이 영역에 아이콘이 나타납니다.
            </p>
          </Step>

          <Step num={2} title="설정 페이지 열기">
            <p>
              메뉴바/트레이 아이콘을 클릭하고{" "}
              <strong>Connect...</strong>를 선택하거나, 브라우저에서 직접
              아래 주소로 접속합니다:
            </p>
            <CodeBlock>http://127.0.0.1:8787/setup</CodeBlock>
          </Step>

          <Step num={3} title="Organization 입력">
            <p>
              <strong>Organization</strong> 필드에 현재 조직의 슬러그를
              입력합니다:
            </p>
            <CodeBlock>{orgSlug || "your-org"}</CodeBlock>
          </Step>

          <Step num={4} title="Cloud API URL 입력">
            <p>
              현재 접속한 웹앱의 주소를{" "}
              <strong>Cloud API URL</strong> 필드에 입력합니다:
            </p>
            <CodeBlock>{origin || "https://devorg.app.heimdexdemo.dev"}</CodeBlock>
          </Step>

          <Step num={5} title="Pairing Code 입력 (권장)">
            <p>
              관리자로부터 받은 6자리 페어링 코드를 입력하고{" "}
              <strong>Pair Device</strong> 버튼을 클릭합니다.
            </p>
            <p className="mt-1 text-xs text-gray-400">
              페어링 코드는 10분간 유효합니다. 만료 시 관리자에게 새 코드를
              요청하세요.
            </p>
          </Step>
        </ol>

        {/* Advanced: Manual Token */}
        <details className="mt-6 rounded-lg border border-gray-100 bg-gray-50">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-gray-600 hover:text-gray-800">
            고급: Manual Token으로 연결
          </summary>
          <div className="border-t border-gray-100 px-4 py-3 text-sm text-gray-600">
            <p>
              페어링 코드 대신 API 토큰을 직접 입력할 수도 있습니다.
              설정 페이지에서 <strong>Manual Token</strong> 탭을 선택한 뒤:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>
                <strong>Organization</strong>: {orgSlug || "your-org"}
              </li>
              <li>
                <strong>Cloud API URL</strong>:{" "}
                {origin || "https://devorg.app.heimdexdemo.dev"}
              </li>
              <li>
                <strong>API Token</strong>: 관리자에게 발급받은 토큰
              </li>
              <li>
                <strong>Library ID</strong>: (선택) 비워두면 자동 감지
              </li>
            </ul>
            <p className="mt-2">
              <strong>Connect</strong> 버튼을 클릭하면 연결됩니다.
            </p>
          </div>
        </details>
      </section>

      {/* Troubleshooting */}
      <section className="rounded-xl border border-gray-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-gray-900">
          문제 해결
        </h2>

        <dl className="mt-4 space-y-4 text-sm">
          <TroubleshootItem q="설정 페이지가 안 열려요">
            에이전트가 실행 중인지 확인하세요. 브라우저에서{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">
              http://127.0.0.1:8787/health
            </code>
            에 접속해 응답이 오는지 확인합니다.
          </TroubleshootItem>

          <TroubleshootItem q="Pairing code expired">
            페어링 코드는 생성 후 10분간만 유효합니다. 관리자에게 새 코드를
            요청하세요.
          </TroubleshootItem>

          <TroubleshootItem q="Agent offline 표시">
            에이전트는 로컬(localhost)에서만 통신합니다. 웹앱에서의 Agent
            상태 표시는 클라우드 API를 통해 간접 확인하므로, 에이전트가
            클라우드에 연결되어 있어야 합니다.
          </TroubleshootItem>

          <TroubleshootItem q="macOS에서 '확인되지 않은 개발자' 경고">
            앱을 우클릭 → <strong>열기</strong> → 다시{" "}
            <strong>열기</strong>를 클릭하세요. 최초 1회만 필요합니다.
          </TroubleshootItem>
        </dl>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Step({
  num,
  title,
  children,
}: {
  num: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-4">
      <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-600">
        {num}
      </span>
      <div className="flex-1 pt-0.5">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        <div className="mt-1 text-sm text-gray-600">{children}</div>
      </div>
    </li>
  );
}

function CodeBlock({ children }: { children: React.ReactNode }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-gray-900 px-4 py-2.5 text-sm text-gray-100">
      {children}
    </pre>
  );
}

function TroubleshootItem({
  q,
  children,
}: {
  q: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="font-medium text-gray-800">{q}</dt>
      <dd className="mt-1 text-gray-500">{children}</dd>
    </div>
  );
}

function AppleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z" />
    </svg>
  );
}

function WindowsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 12V6.75l6-1.32v6.48L3 12zm6.73-.07l8.27.55V5.5l-8.27 1.3v5.13zM18 12.93l-8.27-.55v5.34L18 19v-6.07zM9 17.77l-6-1.31V12.1l6-.09v5.76z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Page export (with auth guard)
// ---------------------------------------------------------------------------

export default function AgentPage() {
  return (
    <AuthGuard>
      <AgentPageContent />
    </AuthGuard>
  );
}
