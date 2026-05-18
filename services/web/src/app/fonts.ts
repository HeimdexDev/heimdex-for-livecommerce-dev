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

/**
 * S-Core Dream — Korean editorial typeface. Files dropped in
 * public/fonts/SCoreDream/. Regular = SCDream4 (W400), Bold = SCDream6
 * (W600).
 */
export const sCoreDream = localFont({
  src: [
    {
      path: "../../public/fonts/SCoreDream/SCDream4-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/SCoreDream/SCDream6-Bold.otf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-score-dream",
  display: "swap",
  preload: false,
});

/**
 * NanumSquare — Naver Hangeul. Regular + Bold OTF.
 */
export const nanumSquare = localFont({
  src: [
    {
      path: "../../public/fonts/NanumSquare/NanumSquare-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/NanumSquare/NanumSquare-Bold.otf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-nanum-square",
  display: "swap",
  preload: false,
});

/**
 * SUIT — sun.fo SUIT typeface. Regular + Bold OTF.
 */
export const suit = localFont({
  src: [
    {
      path: "../../public/fonts/SUIT/SUIT-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/SUIT/SUIT-Bold.otf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-suit",
  display: "swap",
  preload: false,
});

/**
 * KoPub World Dotum — KOPUS dot-style typeface. Medium serves as the
 * 400-weight slot (the Light variant reads too thin for body copy).
 */
export const koPubWorldDotum = localFont({
  src: [
    {
      path: "../../public/fonts/KoPubWorldDotum/KoPubWorldDotum-Regular.otf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/KoPubWorldDotum/KoPubWorldDotum-Bold.otf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-kopub-dotum",
  display: "swap",
  preload: false,
});
