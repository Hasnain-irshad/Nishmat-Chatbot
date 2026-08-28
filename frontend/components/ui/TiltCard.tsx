"use client";

import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TiltCardProps {
  children: ReactNode;
  className?: string;
  /** Maximum tilt in degrees. Keep it modest — big angles look like a toy. */
  intensity?: number;
}

/**
 * Perspective tilt that follows the pointer, with a specular highlight that
 * tracks the same position. The highlight is what sells the 3D — a bare
 * rotation reads as a wobble, but a moving light source reads as a surface.
 */
export function TiltCard({ children, className, intensity = 9 }: TiltCardProps) {
  const ref = useRef<HTMLDivElement>(null);

  const mx = useMotionValue(0.5);
  const my = useMotionValue(0.5);

  const spring = { stiffness: 190, damping: 20, mass: 0.5 };
  const rotateY = useSpring(useTransform(mx, [0, 1], [-intensity, intensity]), spring);
  const rotateX = useSpring(useTransform(my, [0, 1], [intensity, -intensity]), spring);

  const glareX = useTransform(mx, (v) => `${v * 100}%`);
  const glareY = useTransform(my, (v) => `${v * 100}%`);

  function handleMove(e: React.PointerEvent) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    mx.set((e.clientX - rect.left) / rect.width);
    my.set((e.clientY - rect.top) / rect.height);
  }

  function handleLeave() {
    mx.set(0.5);
    my.set(0.5);
  }

  return (
    <div className="scene-3d">
      <motion.div
        ref={ref}
        onPointerMove={handleMove}
        onPointerLeave={handleLeave}
        style={{ rotateX, rotateY }}
        whileHover={{ z: 30 }}
        transition={{ type: "spring", stiffness: 220, damping: 22 }}
        className={cn(
          "layer-3d group relative overflow-hidden rounded-xl3 p-px",
          className,
        )}
      >
        {/* Gradient hairline border */}
        <div
          aria-hidden
          className="absolute inset-0 rounded-xl3 opacity-60 transition-opacity duration-500 group-hover:opacity-100"
          style={{
            background:
              "linear-gradient(140deg, rgba(237,201,106,0.5), rgba(167,139,250,0.28) 45%, rgba(255,255,255,0.06) 100%)",
          }}
        />

        <div className="glass relative h-full rounded-[calc(1.75rem-1px)] p-6 sm:p-7">
          {/* Pointer-tracked specular highlight */}
          <motion.div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
            style={{
              background: useTransform(
                [glareX, glareY],
                ([x, y]) =>
                  `radial-gradient(360px circle at ${x} ${y}, rgba(255,247,221,0.16), transparent 55%)`,
              ),
            }}
          />
          <div className="relative" style={{ transform: "translateZ(28px)" }}>
            {children}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
