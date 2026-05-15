// UI-only auxiliary types. Cross-feature request/response shapes live in
// `@/lib/types/shorts-auto` — never import those from inside this file
// and re-export; other features should reach the shared types directly.

import type { ScoringModeRequest } from "@/lib/types";

export const AUTO_SHORTS_MODES: readonly ScoringModeRequest[] = [
  "both",
  "human",
  "product",
] as const;

export interface ModeOption {
  value: ScoringModeRequest;
  label: string;        // KR label for the radio
  description: string;  // KR helper text under the radio
}

export const MODE_OPTIONS: readonly ModeOption[] = [
  {
    value: "both",
    label: "혼합",
    description: "인물과 상품을 모두 고려해 하이라이트를 자동 선택합니다.",
  },
  {
    value: "human",
    label: "인물 중심",
    description: "선택한 인물이 등장하는 장면만 모아 쇼츠를 만듭니다.",
  },
  {
    value: "product",
    label: "상품 중심",
    description: "인물이 등장하지 않는 상품 설명 장면만 모아 쇼츠를 만듭니다.",
  },
];
