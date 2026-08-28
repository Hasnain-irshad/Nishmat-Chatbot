"use client";

import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useRef } from "react";
import Image from "next/image";

/**
 * The hero emblem: the client's photograph of the arch in Jerusalem carved
 * with the opening words of Nishmat, set inside orbiting rings.
 *
 * Genuinely 3D — the rings are laid down on the X axis with `rotateX`, so they
 * read as orbits around the disc rather than flat circles, and the whole
 * assembly tilts toward the pointer inside a shared perspective.
 */
export function Emblem() {
  const ref = useRef<HTMLDivElement>(null);

  const mx = useMotionValue(0);
  const my = useMotionValue(0);

  const spring = { stiffness: 140, damping: 18, mass: 0.6 };
  const rotateY = useSpring(useTransform(mx, [-1, 1], [-22, 22]), spring);
  const rotateX = useSpring(useTransform(my, [-1, 1], [16, -16]), spring);

  function handleMove(e: React.PointerEvent) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Sample from a generous area around the emblem so it reacts before the
    // pointer is directly on top of it.
    mx.set(((e.clientX - rect.left) / rect.width - 0.5) * 2);
    my.set(((e.clientY - rect.top) / rect.height - 0.5) * 2);
  }

  function handleLeave() {
    mx.set(0);
    my.set(0);
  }

  return (
    <div
      ref={ref}
      onPointerMove={handleMove}
      onPointerLeave={handleLeave}
      className="scene-3d relative mx-auto grid h-44 w-44 place-items-center sm:h-52 sm:w-52"
    >
      {/* Ambient bloom behind everything */}
      <div
        aria-hidden
        className="animate-pulse-glow absolute h-40 w-40 rounded-full blur-3xl sm:h-48 sm:w-48"
        style={{
          background:
            "radial-gradient(circle, rgba(237,201,106,0.42) 0%, rgba(167,139,250,0.18) 45%, transparent 70%)",
        }}
      />

      <motion.div
        style={{ rotateX, rotateY }}
        className="layer-3d relative grid h-full w-full place-items-center"
      >
        {/* Orbit ring — laid flat on X so it reads as depth, not a flat circle */}
        <div
          aria-hidden
          className="animate-spin-slow absolute h-40 w-40 rounded-full border border-dashed border-gold-300/35 sm:h-48 sm:w-48"
          style={{ transform: "rotateX(72deg)" }}
        />
        <div
          aria-hidden
          className="animate-spin-reverse absolute h-36 w-36 rounded-full border border-violet-400/30 sm:h-44 sm:w-44"
          style={{ transform: "rotateX(64deg) rotateZ(28deg)" }}
        />

        {/* Upright dotted halo */}
        <div
          aria-hidden
          className="animate-spin-slow absolute h-[7.5rem] w-[7.5rem] rounded-full border border-dotted border-gold-200/30 sm:h-32 sm:w-32"
          style={{ transform: "translateZ(18px)" }}
        />

        {/* The medallion — the client's own photograph of the arch in
            Jerusalem carved with the opening words of Nishmat. */}
        <div
          className="relative grid h-24 w-24 place-items-center overflow-hidden rounded-full sm:h-28 sm:w-28"
          style={{
            transform: "translateZ(40px)",
            boxShadow:
              "0 0 0 1px rgba(237,201,106,0.5), 0 0 36px -6px rgba(237,201,106,0.55), inset 0 0 22px rgba(0,0,0,0.45)",
          }}
        >
          <Image
            src="/logo.jpg"
            alt="The arch in Jerusalem carved with the opening words of Nishmat Kol Chai"
            width={224}
            height={224}
            priority
            className="h-full w-full object-cover"
            style={{ filter: "saturate(1.05) contrast(1.04)" }}
          />

          {/* Specular sheen, so it reads as glass rather than a pasted photo */}
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-full"
            style={{
              background:
                "linear-gradient(150deg, rgba(255,255,255,0.28) 0%, transparent 45%)",
            }}
          />
        </div>
      </motion.div>
    </div>
  );
}
