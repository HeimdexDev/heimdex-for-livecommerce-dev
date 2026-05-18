"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ShortsCreateRedirect() {
  const params = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    const qs = params.toString();
    router.replace(`/export/shorts/editor${qs ? `?${qs}` : ""}`);
  }, [params, router]);

  return null;
}
