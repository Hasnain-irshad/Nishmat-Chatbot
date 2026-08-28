import { Hammer } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * Placeholder for a route that exists in the navigation but whose feature
 * lands in a later phase. Deliberately explicit about what is coming — a
 * blank page or a 404 would read as a bug.
 */
export function ComingSoon({
  title,
  description,
  phase,
}: {
  title: string;
  description: string;
  phase: string;
}) {
  return (
    <div className="mx-auto max-w-2xl py-8">
      <EmptyState icon={Hammer} title={title} description={description} />
      <p className="mt-5 text-center text-xs text-ink-500">
        Arriving in {phase}.
      </p>
    </div>
  );
}
