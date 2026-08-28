"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, LogOut, Shield, User as UserIcon } from "lucide-react";

import { initialsOf } from "@/lib/utils";
import type { Profile } from "@/types/database";

export function UserMenu({ profile }: { profile: Profile }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const name = profile.full_name?.trim() || profile.email.split("@")[0];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2.5 rounded-full border border-white/10 py-1 pl-1 pr-2.5
                   transition-all duration-300 hover:border-gold-300/35 hover:bg-white/[0.06]"
      >
        <Avatar profile={profile} />
        <span className="hidden max-w-[9rem] truncate text-sm text-ink-200 sm:block">
          {name}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-ink-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="glass glass-gold absolute right-0 top-[calc(100%+0.6rem)] w-60 overflow-hidden rounded-2xl shadow-panel"
          >
            <div className="border-b border-white/[0.07] px-4 py-3.5">
              <p className="truncate text-sm font-medium text-ink-50">{name}</p>
              <p className="mt-0.5 truncate text-xs text-ink-400">{profile.email}</p>
              {profile.role === "admin" && (
                <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-gold-300/15 px-2 py-0.5 text-[0.65rem] font-medium uppercase tracking-wider text-gold-200">
                  <Shield className="h-2.5 w-2.5" aria-hidden />
                  Administrator
                </span>
              )}
            </div>

            <div className="p-1.5">
              {profile.role === "admin" && (
                <MenuLink href="/admin" icon={Shield} onClick={() => setOpen(false)}>
                  Admin dashboard
                </MenuLink>
              )}
              <MenuLink href="/app/settings" icon={UserIcon} onClick={() => setOpen(false)}>
                Account settings
              </MenuLink>

              <form action="/auth/sign-out" method="post">
                <button
                  type="submit"
                  role="menuitem"
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm
                             text-ink-300 transition-colors hover:bg-danger/10 hover:text-rose-300"
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                  Sign out
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MenuLink({
  href,
  icon: Icon,
  children,
  onClick,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <Link
      href={href}
      role="menuitem"
      onClick={onClick}
      className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-300
                 transition-colors hover:bg-white/[0.07] hover:text-ink-50"
    >
      <Icon className="h-4 w-4" aria-hidden />
      {children}
    </Link>
  );
}

function Avatar({ profile }: { profile: Profile }) {
  if (profile.avatar_url) {
    return (
      <Image
        src={profile.avatar_url}
        alt=""
        width={28}
        height={28}
        className="h-7 w-7 rounded-full object-cover"
        unoptimized
      />
    );
  }
  return (
    <span
      aria-hidden
      className="grid h-7 w-7 place-items-center rounded-full text-[0.7rem] font-semibold text-night-950"
      style={{ background: "linear-gradient(135deg, #f4dd97, #e5b849)" }}
    >
      {initialsOf(profile)}
    </span>
  );
}
