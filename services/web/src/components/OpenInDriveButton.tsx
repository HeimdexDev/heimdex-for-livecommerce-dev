"use client";

const SOURCE_CONFIG: Record<string, { title: string; ariaLabel: string }> = {
  gdrive: { title: "Google 드라이브에서 열기", ariaLabel: "Google 드라이브에서 열기" },
  youtube: { title: "YouTube에서 열기", ariaLabel: "YouTube에서 열기" },
};

export function OpenInDriveButton({
  sourceType,
  webViewLink,
  className,
}: {
  sourceType: "gdrive" | "removable_disk" | "local" | string | null;
  webViewLink?: string | null;
  className?: string;
}) {
  const config = sourceType ? SOURCE_CONFIG[sourceType] : undefined;
  if (!config || !webViewLink) {
    return null;
  }

  return (
    <a
      href={webViewLink}
      target="_blank"
      rel="noopener noreferrer"
      title={config.title}
      aria-label={config.ariaLabel}
      className={
        className ??
        "inline-flex items-center justify-center rounded-md border border-gray-200 p-1.5 text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700"
      }
      onClick={(e) => e.stopPropagation()}
    >
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 3h7m0 0v7m0-7L10 14" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h5" />
      </svg>
    </a>
  );
}
