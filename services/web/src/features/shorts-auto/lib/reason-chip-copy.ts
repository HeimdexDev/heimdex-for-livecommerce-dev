// Parse the concatenator's raw reason strings into compact Korean chips.
//
// Backend produces reasons like:
//   "continuous_block:3_scenes"
//   "cherry_picked:2_scenes"
//   "sales_intent:cta,price"
//   "demo_keywords:product_demo,closeup_detail"
//   "product_tags:스킨케어,메이크업"
//   "product_entities:세럼"
//   "persons_in_scene:1"
//   "target_person_present:person_abc123"
//   "no_person_detected"
//
// Pure function. Unknown prefixes pass through as raw — defensive so
// the UI never crashes on an unexpected reason.

export interface ReasonChip {
  label: string;       // KR label
  raw: string;         // the raw reason for diagnostics
  variant: "info" | "success" | "neutral";
}

const STATIC_LABELS: Record<string, { label: string; variant: ReasonChip["variant"] }> = {
  no_person_detected: { label: "인물 없음", variant: "success" },
};

const KEYWORD_TAG_LABELS: Record<string, string> = {
  cta: "구매 유도",
  price: "가격 소개",
  benefit: "혜택",
  coupon: "쿠폰",
  product_demo: "상품 시연",
  closeup_detail: "클로즈업",
  wearing_show: "착용 시연",
  cooking_show: "요리 시연",
  tutorial: "튜토리얼",
  unboxing: "언박싱",
};

function formatTagList(raw: string, dict: Record<string, string>): string {
  const out: string[] = [];
  for (const tag of raw.split(",").map((s) => s.trim()).filter(Boolean)) {
    out.push(dict[tag] ?? tag);
  }
  return out.join(", ");
}

export function reasonChip(rawReason: string): ReasonChip {
  const rawTrim = rawReason.trim();
  if (!rawTrim) {
    return { label: "-", raw: rawReason, variant: "neutral" };
  }

  if (STATIC_LABELS[rawTrim]) {
    return { ...STATIC_LABELS[rawTrim], raw: rawReason };
  }

  const colonIdx = rawTrim.indexOf(":");
  if (colonIdx === -1) {
    return { label: rawTrim, raw: rawReason, variant: "neutral" };
  }

  const prefix = rawTrim.slice(0, colonIdx);
  const value = rawTrim.slice(colonIdx + 1);

  switch (prefix) {
    case "continuous_block": {
      const n = value.split("_")[0] ?? value;
      return { label: `연속 장면 ${n}개`, raw: rawReason, variant: "success" };
    }
    case "cherry_picked": {
      const n = value.split("_")[0] ?? value;
      return { label: `선별 장면 ${n}개`, raw: rawReason, variant: "info" };
    }
    case "sales_intent":
      return { label: `판매 포인트: ${formatTagList(value, KEYWORD_TAG_LABELS)}`, raw: rawReason, variant: "info" };
    case "demo_keywords":
      return { label: `시연: ${formatTagList(value, KEYWORD_TAG_LABELS)}`, raw: rawReason, variant: "info" };
    case "product_tags":
      return { label: `상품 카테고리: ${value}`, raw: rawReason, variant: "info" };
    case "product_entities":
      return { label: `상품 언급: ${value}`, raw: rawReason, variant: "info" };
    case "persons_in_scene":
      return { label: `인물 ${value}명`, raw: rawReason, variant: "info" };
    case "target_person_present":
      return { label: "선택한 인물 등장", raw: rawReason, variant: "success" };
    default:
      return { label: rawTrim, raw: rawReason, variant: "neutral" };
  }
}

export function reasonChipsFor(rawReasons: readonly string[], max = 3): {
  visible: ReasonChip[];
  overflow: number;
} {
  const chips = rawReasons.map(reasonChip);
  if (chips.length <= max) {
    return { visible: chips, overflow: 0 };
  }
  return { visible: chips.slice(0, max), overflow: chips.length - max };
}
