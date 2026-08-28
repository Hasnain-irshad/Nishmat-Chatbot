import type { Metadata } from "next";
import { ComingSoon } from "@/components/ui/ComingSoon";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return (
    <ComingSoon
      title="Account settings"
      description="Change your name, your email and your password."
      phase="Phase 13"
    />
  );
}
