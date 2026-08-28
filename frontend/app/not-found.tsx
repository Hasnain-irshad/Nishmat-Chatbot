import { Aurora } from "@/components/landing/Aurora";
import { ButtonLink } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <>
      <Aurora />
      <main className="relative z-10 flex min-h-svh flex-col items-center justify-center px-6 text-center">
        <p className="font-display text-7xl font-light text-gilded">404</p>
        <h1 className="mt-4 font-display text-2xl font-light text-ink-50">
          This page isn&rsquo;t here
        </h1>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-400">
          The link may be old, or the lesson may not be published yet.
        </p>
        <ButtonLink href="/" className="mt-8">
          Back to the beginning
        </ButtonLink>
      </main>
    </>
  );
}
