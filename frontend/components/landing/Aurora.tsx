/**
 * Slow-drifting colour fields behind the star layer.
 * Pure CSS — three blurred radial blobs on independent animation offsets.
 * Server component: no interactivity, so it costs nothing on the client.
 */
export function Aurora() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
      {/* Base vertical wash */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, #060518 0%, #100c30 38%, #1b1348 68%, #0d0a26 100%)",
        }}
      />

      {/* Violet field, upper left */}
      <div
        className="animate-drift absolute -left-[15%] -top-[20%] h-[65vh] w-[65vh] rounded-full blur-[120px]"
        style={{
          background:
            "radial-gradient(circle, rgba(124,58,237,0.42) 0%, transparent 68%)",
        }}
      />

      {/* Gold field, right */}
      <div
        className="animate-drift absolute -right-[12%] top-[22%] h-[55vh] w-[55vh] rounded-full blur-[130px]"
        style={{
          background:
            "radial-gradient(circle, rgba(237,201,106,0.2) 0%, transparent 66%)",
          animationDelay: "-7s",
        }}
      />

      {/* Deep indigo field, lower centre */}
      <div
        className="animate-drift absolute bottom-[-25%] left-[25%] h-[70vh] w-[70vh] rounded-full blur-[140px]"
        style={{
          background:
            "radial-gradient(circle, rgba(67,47,150,0.5) 0%, transparent 70%)",
          animationDelay: "-14s",
        }}
      />

      {/* Vignette keeps the eye centred */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 90% at 50% 45%, transparent 40%, rgba(6,5,24,0.65) 100%)",
        }}
      />
    </div>
  );
}
