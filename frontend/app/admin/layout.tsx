import { requireAdmin } from "@/lib/auth";
import { Shell } from "@/components/layout/Shell";

/**
 * The role gate for every admin page.
 *
 * `requireAdmin` reads `profiles.role` from the database — this is real
 * enforcement, not a hidden nav item. The FastAPI backend checks the same
 * thing independently, so a direct API call from a learner still fails.
 */
export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await requireAdmin("/admin");
  return (
    <Shell variant="admin" profile={profile}>
      {children}
    </Shell>
  );
}
