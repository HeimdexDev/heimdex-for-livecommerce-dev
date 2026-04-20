import { describe, expect, it } from "vitest";

import { reasonChip, reasonChipsFor } from "../lib/reason-chip-copy";

describe("reasonChip", () => {
  it("maps static 'no_person_detected' to success chip", () => {
    const chip = reasonChip("no_person_detected");
    expect(chip.label).toBe("인물 없음");
    expect(chip.variant).toBe("success");
  });

  it("formats continuous_block with scene count", () => {
    expect(reasonChip("continuous_block:3_scenes").label).toBe("연속 장면 3개");
    expect(reasonChip("continuous_block:3_scenes").variant).toBe("success");
  });

  it("formats cherry_picked with scene count", () => {
    const chip = reasonChip("cherry_picked:2_scenes");
    expect(chip.label).toBe("선별 장면 2개");
    expect(chip.variant).toBe("info");
  });

  it("translates known keyword tags in sales_intent", () => {
    const chip = reasonChip("sales_intent:cta,price");
    expect(chip.label).toBe("판매 포인트: 구매 유도, 가격 소개");
  });

  it("passes unknown keyword tags through verbatim", () => {
    const chip = reasonChip("sales_intent:cta,unknown_new_tag");
    expect(chip.label).toContain("unknown_new_tag");
  });

  it("labels demo_keywords separately from sales_intent", () => {
    const sales = reasonChip("sales_intent:cta");
    const demo = reasonChip("demo_keywords:product_demo");
    expect(sales.label).not.toBe(demo.label);
  });

  it("formats product_tags with raw value", () => {
    expect(reasonChip("product_tags:스킨케어").label).toBe("상품 카테고리: 스킨케어");
  });

  it("formats product_entities", () => {
    expect(reasonChip("product_entities:세럼").label).toBe("상품 언급: 세럼");
  });

  it("formats persons_in_scene count", () => {
    expect(reasonChip("persons_in_scene:2").label).toBe("인물 2명");
  });

  it("identifies target_person_present as success", () => {
    const chip = reasonChip("target_person_present:person_abc");
    expect(chip.variant).toBe("success");
    expect(chip.label).toContain("선택한 인물");
  });

  it("treats unknown prefix as neutral pass-through", () => {
    const chip = reasonChip("totally_unknown:value");
    expect(chip.variant).toBe("neutral");
    expect(chip.label).toBe("totally_unknown:value");
  });

  it("treats empty string defensively", () => {
    const chip = reasonChip("   ");
    expect(chip.label).toBe("-");
    expect(chip.variant).toBe("neutral");
  });
});

describe("reasonChipsFor", () => {
  it("returns all chips when under max", () => {
    const { visible, overflow } = reasonChipsFor(["no_person_detected", "continuous_block:2_scenes"], 3);
    expect(visible).toHaveLength(2);
    expect(overflow).toBe(0);
  });

  it("truncates and reports overflow count", () => {
    const { visible, overflow } = reasonChipsFor(
      ["a:1", "b:2", "c:3", "d:4", "e:5"],
      3,
    );
    expect(visible).toHaveLength(3);
    expect(overflow).toBe(2);
  });

  it("preserves input order in visible chips", () => {
    const inputs = ["no_person_detected", "sales_intent:cta", "demo_keywords:product_demo"];
    const { visible } = reasonChipsFor(inputs, 3);
    expect(visible.map((c) => c.raw)).toEqual(inputs);
  });
});
