"use client";

import { SparkleIcon } from "./icons";
import { skipReasonCopy } from "../lib/skip-reason-copy";
import type { ScoringModeRequest } from "@/lib/types";

interface EmptyStateProps {
  reason: string | null | undefined;
  mode?: ScoringModeRequest;
}

export function EmptyState({ reason, mode }: EmptyStateProps) {
  const message = skipReasonCopy(reason, mode);
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50/50 px-8 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-indigo-500">
        <SparkleIcon className="h-5 w-5" />
      </span>
      <p className="mt-4 text-sm font-medium text-gray-900">자동 생성된 쇼츠가 없습니다</p>
      <p className="mt-1 max-w-md text-xs text-gray-500">{message}</p>
    </div>
  );
}
