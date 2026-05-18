import localFont from "next/font/local";

/**
 * Pretendard — primary editor font (Korean + Latin).
 * Self-hosted from `public/fonts/Pretendard/`. Exposed via the
 * `--font-pretendard` CSS variable; consumers should reach it via the
 * `font-pretendard` Tailwind class or `var(--font-pretendard)` directly.
 */
export const pretendard = localFont({
  src: [
    {
      path: "../../public/fonts/Pretendard/Pretendard-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/Pretendard/Pretendard-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-pretendard",
  display: "swap",
  preload: true,
});

/**
 * Noto Sans KR — secondary editor font for users who prefer the Noto
 * silhouette over Pretendard. Not preloaded — only fetched when a
 * subtitle actually selects it (lazy via @font-face declaration).
 */
export const notoSansKR = localFont({
  src: [
    {
      path: "../../public/fonts/NotoSansKR/NotoSansKR-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/NotoSansKR/NotoSansKR-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-noto-kr",
  display: "swap",
  preload: false,
});

// S-Core Dream / NanumSquare / SUIT / KoPubWorldDotum: declared as
// explicit @font-face blocks in app/globals.css (sources pointing at
// /fonts/<NAME>/*.otf under public/). Not routed through next/font so
// the runtime path is plain static asset loading — easier to verify
// in the network panel and immune to build-time hashing edge cases.
