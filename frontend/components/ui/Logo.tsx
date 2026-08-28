import Image from "next/image";

import { cn } from "@/lib/utils";

/**
 * The Nishmat AI mark.
 *
 * A photograph of the arch in Jerusalem carved with
 * נִשְׁמַת כָּל חַי תְּבָרֵךְ אֶת שִׁמְךָ — the opening words of the prayer the
 * whole series walks through. It is the client's own image, and the same one
 * she used on her design reference.
 *
 * Cropped square on the arch (the siddur at the foot of the original turns to
 * mush below about 64px) and always rendered as a circle with a gold hairline,
 * so it sits inside the night-sky palette rather than on top of it.
 */
export function Logo({
  size = 32,
  className,
  priority = false,
  glow = false,
}: {
  size?: number;
  className?: string;
  /** Set on the hero only — it is the page's largest contentful paint. */
  priority?: boolean;
  glow?: boolean;
}) {
  return (
    <span
      className={cn(
        "relative inline-grid shrink-0 place-items-center overflow-hidden rounded-full",
        className,
      )}
      style={{
        width: size,
        height: size,
        // Ring and inner shadow keep the photograph from looking pasted on.
        boxShadow: glow
          ? "0 0 0 1px rgba(237,201,106,0.5), 0 0 34px -6px rgba(237,201,106,0.55), inset 0 0 18px rgba(0,0,0,0.35)"
          : "0 0 0 1px rgba(237,201,106,0.4), inset 0 0 12px rgba(0,0,0,0.3)",
      }}
    >
      <Image
        src="/logo.jpg"
        alt=""
        width={size * 2}
        height={size * 2}
        priority={priority}
        className="h-full w-full object-cover"
        // Warmed slightly so the limestone sits with the gold accent.
        style={{ filter: "saturate(1.05) contrast(1.04)" }}
      />
    </span>
  );
}
