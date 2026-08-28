"use client";

import { useEffect, useRef } from "react";

interface Star {
  x: number;
  y: number;
  r: number;
  depth: number; // 0 = far, 1 = near — drives parallax and brightness
  twinklePhase: number;
  twinkleSpeed: number;
  hue: "gold" | "violet" | "white";
}

interface Shooting {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
}

const HUES: Record<Star["hue"], string> = {
  gold: "237, 201, 106",
  violet: "167, 139, 250",
  white: "240, 238, 255",
};

/**
 * A depth-layered star field on canvas.
 *
 * Three parallax depths respond to pointer movement at different rates, which
 * is what actually reads as 3D — a single flat layer just looks like confetti.
 * Occasional shooting stars keep it alive without demanding attention.
 *
 * Canvas rather than DOM nodes: ~260 animated elements as divs would cost far
 * too much on a mid-range phone.
 */
export function Starfield() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let stars: Star[] = [];
    let shooting: Shooting[] = [];
    let raf = 0;
    let running = true;

    // Pointer parallax, smoothed so it glides rather than snaps.
    const pointer = { x: 0, y: 0 };
    const eased = { x: 0, y: 0 };

    function build() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas!.clientWidth;
      height = canvas!.clientHeight;
      canvas!.width = Math.floor(width * dpr);
      canvas!.height = Math.floor(height * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Density scales with area, capped so huge monitors do not melt.
      const count = Math.min(Math.round((width * height) / 5200), 320);
      stars = Array.from({ length: count }, () => {
        const depth = Math.random();
        const roll = Math.random();
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          r: 0.35 + depth * 1.5,
          depth,
          twinklePhase: Math.random() * Math.PI * 2,
          twinkleSpeed: 0.0006 + Math.random() * 0.0016,
          hue: roll > 0.9 ? "gold" : roll > 0.72 ? "violet" : "white",
        };
      });
    }

    function spawnShooting() {
      // Always enters from the upper-left quadrant, travelling down-right.
      const startX = Math.random() * width * 0.5;
      const startY = Math.random() * height * 0.35;
      const speed = 5 + Math.random() * 3.5;
      shooting.push({
        x: startX,
        y: startY,
        vx: speed,
        vy: speed * (0.35 + Math.random() * 0.25),
        life: 0,
        maxLife: 70 + Math.random() * 40,
      });
    }

    function draw(t: number) {
      if (!running) return;
      ctx!.clearRect(0, 0, width, height);

      // Ease the parallax offset toward the pointer.
      eased.x += (pointer.x - eased.x) * 0.045;
      eased.y += (pointer.y - eased.y) * 0.045;

      for (const s of stars) {
        // Near stars move more than far ones — that is the depth cue.
        const px = s.x + eased.x * (4 + s.depth * 26);
        const py = s.y + eased.y * (4 + s.depth * 26);

        const twinkle = reduced
          ? 0.7
          : 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(t * s.twinkleSpeed + s.twinklePhase));
        const alpha = (0.16 + s.depth * 0.6) * twinkle;

        ctx!.beginPath();
        ctx!.arc(px, py, s.r, 0, Math.PI * 2);
        ctx!.fillStyle = `rgba(${HUES[s.hue]}, ${alpha.toFixed(3)})`;
        ctx!.fill();

        // Only the brightest few get an expensive glow pass.
        if (s.depth > 0.86) {
          ctx!.beginPath();
          ctx!.arc(px, py, s.r * 4.5, 0, Math.PI * 2);
          const g = ctx!.createRadialGradient(px, py, 0, px, py, s.r * 4.5);
          g.addColorStop(0, `rgba(${HUES[s.hue]}, ${(alpha * 0.35).toFixed(3)})`);
          g.addColorStop(1, `rgba(${HUES[s.hue]}, 0)`);
          ctx!.fillStyle = g;
          ctx!.fill();
        }
      }

      if (!reduced) {
        shooting = shooting.filter((sh) => sh.life < sh.maxLife);
        for (const sh of shooting) {
          sh.life += 1;
          sh.x += sh.vx;
          sh.y += sh.vy;

          const progress = sh.life / sh.maxLife;
          // Fade in over the first 15%, out over the rest.
          const fade = progress < 0.15 ? progress / 0.15 : 1 - (progress - 0.15) / 0.85;
          const tailX = sh.x - sh.vx * 13;
          const tailY = sh.y - sh.vy * 13;

          const grad = ctx!.createLinearGradient(tailX, tailY, sh.x, sh.y);
          grad.addColorStop(0, "rgba(237, 201, 106, 0)");
          grad.addColorStop(1, `rgba(255, 245, 214, ${(fade * 0.85).toFixed(3)})`);

          ctx!.beginPath();
          ctx!.moveTo(tailX, tailY);
          ctx!.lineTo(sh.x, sh.y);
          ctx!.strokeStyle = grad;
          ctx!.lineWidth = 1.4;
          ctx!.lineCap = "round";
          ctx!.stroke();
        }

        if (Math.random() < 0.0022 && shooting.length < 2) spawnShooting();
      }

      raf = requestAnimationFrame(draw);
    }

    function onPointerMove(e: PointerEvent) {
      // Normalised to roughly [-1, 1] from the centre of the viewport.
      pointer.x = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.y = (e.clientY / window.innerHeight - 0.5) * 2;
    }

    function onVisibility() {
      // Do not burn battery in a background tab.
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        raf = requestAnimationFrame(draw);
      }
    }

    let resizeTimer: number;
    function onResize() {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(build, 150);
    }

    build();
    raf = requestAnimationFrame(draw);
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.clearTimeout(resizeTimer);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 h-full w-full"
      style={{ zIndex: 0 }}
    />
  );
}
