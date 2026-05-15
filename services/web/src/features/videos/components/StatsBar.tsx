"use client";

import type { VideoStats } from "@/lib/types";

interface StatsBarProps {
  stats: VideoStats | null;
  isLoading: boolean;
}

function StatCard({ label, value, isLoading }: { label: string; value: string | number; isLoading: boolean }) {
  return (
    <div className="card p-4">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      {isLoading ? (
        <div className="mt-1 h-8 w-16 bg-gray-200 rounded animate-pulse" />
      ) : (
        <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
      )}
    </div>
  );
}

export function StatsBar({ stats, isLoading }: StatsBarProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Total Videos" value={stats?.total_videos ?? 0} isLoading={isLoading} />
      <StatCard label="Total Scenes" value={stats?.total_scenes ?? 0} isLoading={isLoading} />
      <StatCard label="Libraries" value={stats?.total_libraries ?? 0} isLoading={isLoading} />
      <StatCard label="Scenes (24h)" value={stats?.scenes_last_24h ?? 0} isLoading={isLoading} />
    </div>
  );
}
