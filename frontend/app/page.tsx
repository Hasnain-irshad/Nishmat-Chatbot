import { BookOpen, MessagesSquare, Sparkles, ArrowRight } from "lucide-react";

import { Aurora } from "@/components/landing/Aurora";
import { Starfield } from "@/components/landing/Starfield";
import { Emblem } from "@/components/landing/Emblem";
import { Divider } from "@/components/landing/Divider";
import { LandingNav } from "@/components/landing/LandingNav";
import { Reveal } from "@/components/ui/Reveal";
import { TiltCard } from "@/components/ui/TiltCard";
import { ButtonLink } from "@/components/ui/Button";

export default function LandingPage() {
  return (
    <>
      <Aurora />
      <Starfield />
      <LandingNav />

      <main className="grain relative z-10">
        {/* ================================================== HERO ========= */}
        <section className="relative flex min-h-svh flex-col items-center justify-center px-6 pb-20 pt-28 text-center">
          <Reveal>
            <div className="animate-float-slow">
              <Emblem />
            </div>
          </Reveal>

          <Reveal delay={0.15}>
            <h1 className="mt-8 font-display text-5xl font-light leading-none tracking-tight sm:text-6xl md:text-7xl">
              <span className="text-gilded text-gilded-animate">Nishmat AI</span>
            </h1>
          </Reveal>

          <Reveal delay={0.25}>
            <p className="mt-4 text-[0.72rem] font-medium uppercase tracking-[0.42em] text-ink-300 sm:text-xs">
              A Journey of Praise
            </p>
          </Reveal>

          <Reveal delay={0.4} className="w-full">
            <Divider className="mx-auto mt-12 max-w-md" mark="flame" />
          </Reveal>

          {/* ---- Dedication ---- */}
          <Reveal delay={0.5}>
            <div className="mt-10 space-y-3 text-balance">
              <p className="text-[0.98rem] leading-relaxed text-ink-200">
                This chat began as a{" "}
                <em className="font-display text-[1.12em] not-italic text-gold-200">
                  zechut
                </em>{" "}
                in memory of our dear friend{" "}
                <span aria-hidden className="text-rose-400">
                  ♥
                </span>
              </p>
              <p className="font-display text-2xl font-light text-ink-50 sm:text-[1.7rem]">
                Rachel bat Rut, Rachel Betesh a”h
              </p>
              <p className="text-[0.98rem] leading-relaxed text-ink-200">
                a woman who lived with deep gratitude
                <br />
                and a love for the tefillah of Nishmat.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.6}>
            <div className="mt-8 space-y-2">
              <p className="text-[0.98rem] text-ink-200">
                Over time, it has grown into a space of
              </p>
              <p className="font-display text-xl italic text-gold-200 sm:text-2xl">
                learning, connection, and personal meaning.
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.7} className="w-full">
            <Divider className="mx-auto mt-12 max-w-md" />
          </Reveal>

          {/* ---- The teacher ---- */}
          <Reveal delay={0.78}>
            <div className="mt-10 space-y-3">
              <p className="text-[0.98rem] text-ink-200">
                My name is{" "}
                <span className="font-display text-[1.15em] text-ink-50">
                  Rivkah Dahan
                </span>
              </p>
              <p className="text-[0.98rem] leading-relaxed text-ink-300">
                inspired by the life and perspective of my husband,
              </p>
              <p className="font-display text-xl font-light text-ink-50 sm:text-[1.4rem]">
                Harav Chaim Yechezkel Shraga <Honorific>zt&rdquo;l</Honorific>
                <br />
                <span className="text-[0.9em] text-ink-200">
                  ben Rochel Esther <Honorific>a&rdquo;h</Honorific>.
                </span>
              </p>
            </div>
          </Reveal>

          <Reveal delay={0.86} className="w-full">
            <Divider className="mx-auto mt-12 max-w-md" />
          </Reveal>

          {/* ---- Blessing ---- */}
          <Reveal delay={0.94}>
            <div className="glass glass-gold mt-10 max-w-xl rounded-xl3 px-7 py-7 sm:px-10">
              <p className="text-[0.95rem] leading-[1.9] text-ink-200">
                May our learning be a{" "}
                <em className="font-display text-[1.12em] not-italic text-gold-200">
                  zechut
                </em>{" "}
                for
                <br />
                <span className="font-display text-lg text-ink-50">
                  Rachel bat Rut <Honorific>a&rdquo;h</Honorific>
                </span>
                <br />
                and Harav Chaim Yechezkel Shraga <Honorific>zt&rdquo;l</Honorific>{" "}
                ben Rochel Esther <Honorific>a&rdquo;h</Honorific>,
                <br />
                and bring{" "}
                <em className="font-display text-[1.12em] not-italic text-gold-200">
                  yeshuot and geulah
                </em>{" "}
                to Klal Yisrael.{" "}
                <span aria-hidden className="text-gold-300">
                  ✦
                </span>
              </p>
            </div>
          </Reveal>

          {/* ---- Primary call to action ---- */}
          <Reveal delay={1.1}>
            <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row">
              <ButtonLink href="/sign-up" size="lg" className="w-64 sm:w-auto">
                Enter
                <ArrowRight className="h-4 w-4" aria-hidden />
              </ButtonLink>
              <ButtonLink
                href="/sign-in"
                variant="outline"
                size="lg"
                className="w-64 sm:w-auto"
              >
                I already have an account
              </ButtonLink>
            </div>
          </Reveal>

          <Reveal delay={1.2}>
            <p className="mt-5 text-xs text-ink-500">
              Free to join · Sign in with Google or email
            </p>
          </Reveal>
        </section>

        {/* ============================================ WHAT IS INSIDE ===== */}
        <section className="relative px-6 pb-28 pt-8">
          <div className="mx-auto max-w-5xl">
            <Reveal>
              <div className="text-center">
                <Divider className="mx-auto max-w-xs" mark="diamond" />
                <h2 className="mt-10 font-display text-3xl font-light text-ink-50 sm:text-4xl">
                  What you&rsquo;ll find inside
                </h2>
                <p className="mx-auto mt-3 max-w-lg text-[0.95rem] leading-relaxed text-ink-300">
                  Every lesson in the series, gathered in one place. Ask a
                  question and the answer comes only from the lessons themselves.
                </p>
              </div>
            </Reveal>

            <div className="mt-14 grid gap-6 md:grid-cols-3">
              {FEATURES.map((f, i) => (
                <Reveal key={f.title} delay={0.1 * i}>
                  <TiltCard className="h-full">
                    <div className="flex h-full flex-col">
                      <span
                        className="mb-5 grid h-11 w-11 place-items-center rounded-2xl"
                        style={{
                          background:
                            "linear-gradient(140deg, rgba(237,201,106,0.22), rgba(167,139,250,0.16))",
                          boxShadow: "inset 0 0 0 1px rgba(237,201,106,0.28)",
                        }}
                      >
                        <f.icon className="h-5 w-5 text-gold-200" aria-hidden />
                      </span>
                      <h3 className="font-display text-xl font-medium text-ink-50">
                        {f.title}
                      </h3>
                      <p className="mt-2.5 text-sm leading-relaxed text-ink-300">
                        {f.body}
                      </p>
                    </div>
                  </TiltCard>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* =================================================== FOOTER ====== */}
        <footer className="relative border-t border-white/[0.07] px-6 py-12">
          <div className="mx-auto flex max-w-5xl flex-col items-center gap-4 text-center">
            <p className="hebrew text-lg text-gold-200/90" lang="he">
              נִשְׁמַת כָּל חַי תְּבָרֵךְ אֶת שִׁמְךָ
            </p>
            <p className="text-xs tracking-wide text-ink-500">
              &ldquo;The soul of every living being shall bless Your Name.&rdquo;
            </p>
            <p className="mt-2 text-xs text-ink-500">
              © {new Date().getFullYear()} Nishmat AI · A Journey of Praise
            </p>
          </div>
        </footer>
      </main>
    </>
  );
}

/**
 * Keeps a Hebrew honorific whole across a line break.
 *
 * `zt"l` and `a"h` use a curly quote, and browsers treat that as a legitimate
 * place to break — which strands the final letter alone on the next line. The
 * abbreviation is one word; a break may fall before it, never inside it.
 */
function Honorific({ children }: { children: React.ReactNode }) {
  return <span className="whitespace-nowrap">{children}</span>;
}

const FEATURES = [
  {
    icon: BookOpen,
    title: "The full series",
    body: "Every published lesson, in order, with the Hebrew, the transliteration and the translation set the way they are meant to be read.",
  },
  {
    icon: MessagesSquare,
    title: "Ask anything",
    body: "Wondering about something in a lesson? Ask, and get an answer drawn from the lessons themselves, with the lesson it came from shown alongside it.",
  },
  {
    icon: Sparkles,
    title: "Your conversations, kept",
    body: "Every conversation is saved. Come back tomorrow, pick up exactly where you left off, and keep the thought going.",
  },
] as const;
