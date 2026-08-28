"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  BookOpen,
  MessagesSquare,
  LayoutDashboard,
  FilePlus2,
  Library,
  LayoutTemplate,
  Sparkles,
  Users,
  Menu,
  X,
  ExternalLink,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { UserMenu } from "@/components/layout/UserMenu";
import { Logo } from "@/components/ui/Logo";
import type { Profile } from "@/types/database";

export type ShellVariant = "user" | "admin";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Match only the exact path, not descendants. */
  exact?: boolean;
}

const NAV: Record<ShellVariant, { section: string; items: NavItem[] }[]> = {
  user: [
    {
      section: "Learning",
      items: [
        { href: "/app", label: "Lessons", icon: BookOpen, exact: true },
        { href: "/app/chat", label: "Ask a question", icon: MessagesSquare },
      ],
    },
  ],
  admin: [
    {
      section: "Overview",
      items: [{ href: "/admin", label: "Dashboard", icon: LayoutDashboard, exact: true }],
    },
    {
      section: "Lessons",
      items: [
        { href: "/admin/lessons/new", label: "Create lesson", icon: FilePlus2 },
        { href: "/admin/lessons", label: "All lessons", icon: Library },
      ],
    },
    {
      section: "Configuration",
      items: [
        { href: "/admin/templates", label: "Templates", icon: LayoutTemplate },
        { href: "/admin/style-examples", label: "Style library", icon: Sparkles },
        { href: "/admin/users", label: "People", icon: Users },
      ],
    },
  ],
};

export function Shell({
  variant,
  profile,
  children,
}: {
  variant: ShellVariant;
  profile: Profile;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const groups = NAV[variant];

  return (
    <div className="relative min-h-svh">
      {/* Ground — quieter than the landing page; people work in here for a long time */}
      <div
        aria-hidden
        className="fixed inset-0"
        style={{
          background:
            "linear-gradient(165deg, #070620 0%, #0d0a2a 45%, #120d38 100%)",
        }}
      />
      <div
        aria-hidden
        className="fixed left-1/2 top-0 h-[45vh] w-[80vw] -translate-x-1/2 rounded-full opacity-45 blur-[130px]"
        style={{
          background:
            "radial-gradient(circle, rgba(124,58,237,0.3) 0%, transparent 70%)",
        }}
      />

      {/* ------------------------------------------------ desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-white/[0.07] bg-night-950/60 backdrop-blur-xl lg:flex">
        <SidebarContent
          variant={variant}
          groups={groups}
          pathname={pathname}
          onNavigate={() => {}}
        />
      </aside>

      {/* ------------------------------------------------- mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-night-950/75 backdrop-blur-sm lg:hidden"
              aria-hidden
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 320, damping: 34 }}
              className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-white/10 bg-night-900 lg:hidden"
              role="dialog"
              aria-label="Navigation"
            >
              <SidebarContent
                variant={variant}
                groups={groups}
                pathname={pathname}
                onNavigate={() => setMobileOpen(false)}
                onClose={() => setMobileOpen(false)}
              />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* --------------------------------------------------------- main */}
      <div className="relative z-10 lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-white/[0.07] bg-night-950/70 px-4 backdrop-blur-xl sm:px-6">
          <button
            onClick={() => setMobileOpen(true)}
            className="grid h-9 w-9 place-items-center rounded-lg text-ink-300 transition-colors hover:bg-white/[0.07] hover:text-ink-50 lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>

          <div className="flex-1" />

          {variant === "admin" && (
            <Link
              href="/app"
              className="hidden items-center gap-1.5 rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-300 transition-colors hover:border-gold-300/35 hover:text-ink-50 sm:inline-flex"
            >
              View as learner
              <ExternalLink className="h-3 w-3" aria-hidden />
            </Link>
          )}

          <UserMenu profile={profile} />
        </header>

        <main className="px-4 py-7 sm:px-6 lg:px-8 lg:py-9">{children}</main>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- sidebar */

function SidebarContent({
  variant,
  groups,
  pathname,
  onNavigate,
  onClose,
}: {
  variant: ShellVariant;
  groups: { section: string; items: NavItem[] }[];
  pathname: string;
  onNavigate: () => void;
  onClose?: () => void;
}) {
  return (
    <>
      <div className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5">
        <Link href={variant === "admin" ? "/admin" : "/app"} className="group flex items-center gap-2.5">
          <Logo size={32} className="transition-transform duration-500 group-hover:rotate-[8deg]" />
          <span className="flex flex-col leading-none">
            <span className="font-display text-base font-medium text-ink-50">Nishmat AI</span>
            {variant === "admin" && (
              <span className="mt-0.5 text-[0.6rem] uppercase tracking-[0.2em] text-gold-300/80">
                Admin
              </span>
            )}
          </span>
        </Link>

        {onClose && (
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-400 hover:bg-white/[0.07] hover:text-ink-50"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
        {groups.map((group) => (
          <div key={group.section}>
            <p className="mb-2 px-3 text-[0.65rem] font-medium uppercase tracking-[0.18em] text-ink-500">
              {group.section}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = item.exact
                  ? pathname === item.href
                  : pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-200",
                        active
                          ? "bg-gradient-to-r from-gold-300/15 to-violet-500/[0.07] text-ink-50"
                          : "text-ink-300 hover:bg-white/[0.05] hover:text-ink-50",
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId={`nav-active-${variant}`}
                          className="absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-r-full bg-gold-300"
                          transition={{ type: "spring", stiffness: 380, damping: 32 }}
                        />
                      )}
                      <item.icon
                        className={cn(
                          "h-[1.05rem] w-[1.05rem] shrink-0 transition-colors",
                          active ? "text-gold-200" : "text-ink-400 group-hover:text-ink-200",
                        )}
                      />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/[0.07] px-5 py-4">
        <p className="hebrew text-center text-sm text-gold-200/50" lang="he">
          נִשְׁמַת כָּל חַי
        </p>
      </div>
    </>
  );
}
