import { getThumbnailAspectClass, getDashboardGridClass, getInlineThumbnailClass, getPersonGridClass } from "@/lib/thumbnailUtils";

describe("thumbnailUtils", () => {
  describe("getThumbnailAspectClass", () => {
    it("returns aspect-video for 16:9", () => {
      expect(getThumbnailAspectClass("16:9")).toBe("aspect-video");
    });
    it("returns aspect-[9/16] for 9:16", () => {
      expect(getThumbnailAspectClass("9:16")).toBe("aspect-[9/16]");
    });
  });

  describe("getDashboardGridClass", () => {
    it("returns 4-col layout for 16:9", () => {
      expect(getDashboardGridClass("16:9")).toContain("grid-cols-4");
    });
    it("returns 6-col layout for 9:16", () => {
      expect(getDashboardGridClass("9:16")).toContain("grid-cols-6");
    });
  });

  describe("getInlineThumbnailClass", () => {
    it("returns w-32 h-20 for 16:9", () => {
      expect(getInlineThumbnailClass("16:9")).toBe("w-32 h-20");
    });
    it("returns w-14 h-24 for 9:16", () => {
      expect(getInlineThumbnailClass("9:16")).toBe("w-14 h-24");
    });
  });

  describe("getPersonGridClass", () => {
    it("returns 3-col grid for 16:9", () => {
      expect(getPersonGridClass("16:9")).toContain("grid-cols-3");
    });
    it("returns 4-col grid for 9:16", () => {
      expect(getPersonGridClass("9:16")).toContain("grid-cols-4");
    });
  });
});
