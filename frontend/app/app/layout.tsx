import { requireUser } from "@/lib/auth";
import { Shell } from "@/components/layout/Shell";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await requireUser("/app");
  return (
    <Shell variant="user" profile={profile}>
      {children}
    </Shell>
  );
}
