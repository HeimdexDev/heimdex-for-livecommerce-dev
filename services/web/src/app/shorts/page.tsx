import { permanentRedirect } from "next/navigation";

export default function ShortsRedirect() {
  permanentRedirect("/export/shorts");
}
