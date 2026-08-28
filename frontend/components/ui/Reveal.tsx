"use client";

import { motion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

const variants: Variants = {
  hidden: { opacity: 0, y: 22, filter: "blur(6px)" },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.75, ease: [0.16, 1, 0.3, 1] },
  },
};

interface RevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  /** Re-run the animation each time the element scrolls back into view. */
  repeat?: boolean;
}

/**
 * Scroll-triggered entrance. Framer Motion already disables transforms under
 * `prefers-reduced-motion`, and our global CSS collapses durations, so this
 * degrades to an instant appearance rather than an invisible element.
 */
export function Reveal({ children, delay = 0, className, repeat = false }: RevealProps) {
  return (
    <motion.div
      className={className}
      variants={variants}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: !repeat, margin: "-60px" }}
      transition={{ delay }}
    >
      {children}
    </motion.div>
  );
}
