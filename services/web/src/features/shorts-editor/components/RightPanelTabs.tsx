// figma: 1607:65302 (cache: .figma-cache/screenshots/1607-65302_reference.png)

"use client";

export type RightPanelTab = "text" | "background" | "template";

interface RightPanelTabsProps {
  active: RightPanelTab;
  onChange: (tab: RightPanelTab) => void;
}

const TABS: { id: RightPanelTab; label: string }[] = [
  { id: "text", label: "텍스트" },
  { id: "background", label: "배경" },
  { id: "template", label: "템플릿" },
];

export function RightPanelTabs({ active, onChange }: RightPanelTabsProps) {
  return (
    <div className="flex items-center gap-4 border-b border-grayscale-200 px-4 pt-4">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`pb-2 text-sm transition-colors ${
            active === tab.id
              ? "border-b-2 border-heimdex-navy-500 font-semibold text-grayscale-800"
              : "border-b-2 border-transparent font-medium text-grayscale-400 hover:text-grayscale-800"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
