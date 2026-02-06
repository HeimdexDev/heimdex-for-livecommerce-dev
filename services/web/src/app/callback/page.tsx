"use client";

import dynamic from "next/dynamic";

const CallbackContent = dynamic(
  () => import("./CallbackContent"),
  { ssr: false }
);

export default function CallbackPage() {
  return <CallbackContent />;
}
