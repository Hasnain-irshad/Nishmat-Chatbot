import type { Metadata } from "next";
import { ComingSoon } from "@/components/ui/ComingSoon";

export const metadata: Metadata = { title: "Style library" };

export default function Page() {
  return (
    <ComingSoon
      title="Style library"
      description="Approved lessons the AI writes from. Two or three relevant examples are retrieved for every new lesson."
      phase="Phase 6"
    />
  );
}
