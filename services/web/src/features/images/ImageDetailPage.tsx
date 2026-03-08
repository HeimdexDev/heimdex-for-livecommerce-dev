"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getVideoScenes } from "@/lib/api/videos";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { OpenInDriveButton } from "@/components/OpenInDriveButton";
import type { VideoScenesResponse } from "@/lib/types";

interface ImageDetailPageProps {
  imageId: string;
}

export function ImageDetailPage({ imageId }: ImageDetailPageProps) {
  const { getAccessToken } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<VideoScenesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const tokenGetter = () => getAccessToken();
        const res = await getVideoScenes(imageId, 1, 0, tokenGetter);
        if (!cancelled) setData(res);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [imageId, getAccessToken]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12">
        <p className="text-center text-gray-500">이미지를 찾을 수 없습니다.</p>
        <div className="mt-4 text-center">
          <Link href="/" className="text-sm text-indigo-500 hover:text-indigo-600">
            검색으로 돌아가기
          </Link>
        </div>
      </div>
    );
  }

  const title = data.video_title || "제목 없음";
  const scene = data.scenes[0];
  const sceneId = scene ? scene.scene_id : `${imageId}_scene_000`;
  const sourceType = (data.source_type ?? "gdrive") as "gdrive" | "removable_disk" | "local";

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-4 flex items-center gap-1.5 text-sm text-gray-500 transition-colors hover:text-gray-700"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
        </svg>
        뒤로가기
      </button>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="overflow-hidden rounded-xl bg-gray-100">
            <SceneThumbnail
              videoId={imageId}
              sceneId={sceneId}
              agentAvailable={true}
              className="w-full"
              sourceType={sourceType}
            />
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-gray-900 break-all">{title}</h1>
              <OpenInDriveButton
                sourceType={sourceType}
                webViewLink={data.web_view_link}
                className="flex-shrink-0 inline-flex items-center justify-center rounded p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
              />
            </div>

            <dl className="mt-4 space-y-3 text-sm">
              {data.source_path && (
                <div>
                  <dt className="text-xs font-medium text-gray-400">경로</dt>
                  <dd className="mt-0.5 text-gray-700 break-all">{data.source_path}</dd>
                </div>
              )}
              {data.capture_time && (
                <div>
                  <dt className="text-xs font-medium text-gray-400">촬영일</dt>
                  <dd className="mt-0.5 text-gray-700">
                    {new Date(data.capture_time).toLocaleDateString("ko-KR")}
                  </dd>
                </div>
              )}
              {data.library_name && (
                <div>
                  <dt className="text-xs font-medium text-gray-400">라이브러리</dt>
                  <dd className="mt-0.5 text-gray-700">{data.library_name}</dd>
                </div>
              )}
            </dl>
          </div>

          {scene && (
            <>
              {scene.scene_caption && (
                <div className="rounded-xl bg-white p-5 shadow-sm">
                  <h3 className="text-xs font-medium text-gray-400">AI 캡션</h3>
                  <p className="mt-1.5 text-sm text-gray-700 leading-relaxed">{scene.scene_caption}</p>
                </div>
              )}

              {scene.transcript_raw && scene.transcript_char_count > 0 && (
                <div className="rounded-xl bg-white p-5 shadow-sm">
                  <h3 className="text-xs font-medium text-gray-400">OCR 텍스트</h3>
                  <p className="mt-1.5 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{scene.transcript_raw}</p>
                </div>
              )}

              {scene.keyword_tags.length > 0 && (
                <div className="rounded-xl bg-white p-5 shadow-sm">
                  <h3 className="text-xs font-medium text-gray-400">태그</h3>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {scene.keyword_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
