// figma: 1607:65302 (cache: .figma-cache/screenshots/1607-65302_reference.png)

"use client";

import { useState, type ReactNode } from "react";
import { RightPanelTabs, type RightPanelTab } from "./RightPanelTabs";

interface RightPanelProps {
  /** 텍스트 탭 컨텐츠 (legacy children prop 호환). */
  children?: ReactNode;
  /** 배경 탭 컨텐츠 (figma 1602:41198 BackgroundPanel). 미지정 시 placeholder. */
  backgroundTab?: ReactNode;
  /** 템플릿 탭 컨텐츠 (figma 1602:41198 TemplatePanel). 미지정 시 placeholder. */
  templateTab?: ReactNode;
}

export function RightPanel({
  children,
  backgroundTab,
  templateTab,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<RightPanelTab>("text");

  let body: ReactNode;
  if (activeTab === "text") {
    body = children;
  } else if (activeTab === "background") {
    body = backgroundTab ?? <Placeholder />;
  } else {
    body = templateTab ?? <Placeholder />;
  }

  return (
    <div className="flex h-full flex-col">
      <RightPanelTabs active={activeTab} onChange={setActiveTab} />
      <div className="flex-1 overflow-y-auto">{body}</div>
    </div>
  );
}

function Placeholder() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-grayscale-400">
      준비 중
    </div>
  );
}
