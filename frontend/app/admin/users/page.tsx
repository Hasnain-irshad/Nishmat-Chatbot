import type { Metadata } from "next";
import { ComingSoon } from "@/components/ui/ComingSoon";

export const metadata: Metadata = { title: "People" };

export default function Page() {
  return (
    <ComingSoon
      title="People"
      description="Everyone with an account, and who holds the administrator role."
      phase="Phase 13"
    />
  );
}
