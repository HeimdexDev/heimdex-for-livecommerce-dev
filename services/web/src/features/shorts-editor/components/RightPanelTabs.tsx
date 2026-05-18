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
  // figma 1663:45754 — h=32 border-b border-neutral-h-100, full-width strip
  // sitting inside the RightPanel's p-20 wrapper. Each tab takes flex-1 and
  // active state lifts a 2px heimdex-navy underline.
  return (
    <div className="flex h-[32px] w-full shrink-0 items-start border-b border-neutral-h-100">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`flex flex-1 items-start justify-center pb-[2px] text-[16px] tracking-[-0.4px] transition-colors ${
            active === tab.id
              ? "border-b-2 border-heimdex-navy-500 font-semibold text-grayscale-800"
              : "border-b-2 border-transparent font-semibold text-neutral-h-500 hover:text-grayscale-800"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
