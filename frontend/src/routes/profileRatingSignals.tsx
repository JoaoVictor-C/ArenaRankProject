import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { gsap as GsapType } from "gsap";

import { Mi } from "../components";
import { loadAmbientMotion, prefersReducedMotion } from "../lib/motion";
import type { Modifier } from "../lib/types";
import {
  getRatingSignalMotionPlan,
  getRatingSignalTrack,
  RATING_SIGNAL_POSES,
  wrapRatingSignalIndex,
  type RatingSignalCarouselDirection,
  type RatingSignalTrackPosition,
} from "./profileRatingCarousel";
import {
  buildProfileRatingSignal,
  resolveProfileRatingModifiers,
  type ProfileRatingSignal,
  type SignalContext,
} from "./profileRatingSignalModel";
import "./profileRatingSignals.css";

interface ProfileRatingSignalsProps extends SignalContext {
  modifiers: Modifier[];
}

type Gsap = typeof GsapType;
type GsapContext = ReturnType<Gsap["context"]>;
type GsapTimeline = ReturnType<Gsap["timeline"]>;

const SWIPE_THRESHOLD = 44;

function slotElement(
  root: HTMLElement,
  position: RatingSignalTrackPosition,
): HTMLElement | null {
  return root.querySelector<HTMLElement>(`[data-slot="${position}"]`);
}

function setCanonicalSlotPoses(gsap: Gsap, root: HTMLElement): void {
  (
    [
      "farPrevious",
      "previous",
      "active",
      "next",
      "farNext",
    ] as RatingSignalTrackPosition[]
  ).forEach((position) => {
    const element = slotElement(root, position);
    if (!element) return;
    gsap.set(element, RATING_SIGNAL_POSES[position]);
  });
}

function signalTone(card: ProfileRatingSignal): string {
  if (card.kind === "boosting" || card.kind === "penalidade") {
    return "tone-integrity";
  }
  if (card.kind === "protecao") return "tone-protection";
  if (card.impact > 0) return "tone-positive";
  if (card.impact < 0) return "tone-negative";
  return "tone-neutral";
}

export function ProfileRatingSignals({
  modifiers,
  placement,
  premade,
  crDelta,
}: ProfileRatingSignalsProps) {
  const cards = useMemo(
    () =>
      resolveProfileRatingModifiers(modifiers, crDelta)
        .map((modifier) =>
          buildProfileRatingSignal(modifier, { placement, premade, crDelta }),
        )
        .filter((card): card is ProfileRatingSignal => card !== null),
    [crDelta, modifiers, placement, premade],
  );
  const [activeStep, setActiveStep] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);
  const [liveMessage, setLiveMessage] = useState("");
  const rootRef = useRef<HTMLElement>(null);
  const pointerStartRef = useRef<{ id: number; x: number } | null>(null);
  const busyRef = useRef(false);
  const gsapRef = useRef<Gsap | null>(null);
  const gsapContextRef = useRef<GsapContext | null>(null);
  const timelineRef = useRef<GsapTimeline | null>(null);
  const multiple = cards.length > 1;
  const activeIndex = wrapRatingSignalIndex(activeStep, cards.length);
  const track = useMemo(
    () => getRatingSignalTrack(activeStep, cards.length),
    [activeStep, cards.length],
  );

  const commitStep = useCallback(
    (nextStep: number) => {
      const normalizedIndex = wrapRatingSignalIndex(nextStep, cards.length);
      const nextCard = cards[normalizedIndex];
      setActiveStep(nextStep);
      setLiveMessage(
        nextCard ? `${nextCard.title}: ${nextCard.formattedImpact}` : "",
      );
      busyRef.current = false;
      setIsAnimating(false);
    },
    [cards],
  );

  const rotate = useCallback(
    (direction: RatingSignalCarouselDirection) => {
      if (cards.length < 2 || busyRef.current) return;

      const nextStep = activeStep + direction;
      const root = rootRef.current;
      const gsap = gsapRef.current;
      if (!root || !gsap || prefersReducedMotion()) {
        commitStep(nextStep);
        return;
      }

      const farPrevious = slotElement(root, "farPrevious");
      const previous = slotElement(root, "previous");
      const active = slotElement(root, "active");
      const next = slotElement(root, "next");
      const farNext = slotElement(root, "farNext");
      const incoming = direction === 1 ? next : previous;
      if (
        !farPrevious ||
        !previous ||
        !active ||
        !next ||
        !farNext ||
        !incoming
      ) {
        commitStep(nextStep);
        return;
      }

      busyRef.current = true;
      setIsAnimating(true);
      timelineRef.current?.kill();

      const timeline = gsap.timeline({
        defaults: {
          duration: 0.46,
          ease: "power3.inOut",
          overwrite: "auto",
        },
        onComplete: () => {
          timelineRef.current = null;
          commitStep(nextStep);
        },
      });
      timelineRef.current = timeline;

      const motionPlan = getRatingSignalMotionPlan(direction);
      const elements = { farPrevious, previous, active, next, farNext };
      motionPlan.movers.forEach(({ position, pose }) => {
        timeline.to(elements[position], RATING_SIGNAL_POSES[pose], 0);
      });
      timeline
        .to(
          elements[motionPlan.exiting.position],
          {
            ...RATING_SIGNAL_POSES[motionPlan.exiting.pose],
            duration: 0.46,
          },
          0,
        );

      const incomingAccent = incoming.querySelector<HTMLElement>(
        ".rating-signal-accent",
      );
      if (incomingAccent) {
        timeline.fromTo(
          incomingAccent,
          { scaleX: 0.28 },
          {
            scaleX: 1,
            duration: 0.32,
            ease: "power3.out",
            transformOrigin: "0% 50%",
          },
          0.12,
        );
      }
    },
    [activeStep, cards.length, commitStep],
  );

  useEffect(() => {
    setActiveStep(0);
  }, [cards.length]);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let cancelled = false;
    void loadAmbientMotion().then((motion) => {
      if (cancelled || !motion || !rootRef.current) return;
      gsapRef.current = motion.gsap;
      gsapContextRef.current?.revert();
      gsapContextRef.current = motion.gsap.context(() => {
        setCanonicalSlotPoses(motion.gsap, root);
      }, root);
    });

    return () => {
      cancelled = true;
      timelineRef.current?.kill();
      timelineRef.current = null;
      gsapContextRef.current?.revert();
      gsapContextRef.current = null;
      gsapRef.current = null;
      busyRef.current = false;
    };
  }, [cards.length]);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const gsap = gsapRef.current;
    if (root && gsap) setCanonicalSlotPoses(gsap, root);
  }, [activeStep, track]);

  if (cards.length === 0) return null;

  return (
    <section
      className="rating-signals"
      aria-label="Fatores do PDL"
      ref={rootRef}
    >
      <header className="rating-signals-head">
        <span className="rating-signals-heading">
          <small>Raio-X do resultado</small>
          <b>Fatores do PDL</b>
        </span>
        {multiple && (
          <span className="rating-signals-tools">
            <span className="rating-signals-count" aria-hidden="true">
              {activeIndex + 1} / {cards.length}
            </span>
            <span className="rating-signals-nav">
              <button
                type="button"
                aria-label="Fator anterior"
                disabled={isAnimating}
                onClick={() => rotate(-1)}
              >
                <Mi name="arrow_back" />
              </button>
              <button
                type="button"
                aria-label="Próximo fator"
                disabled={isAnimating}
                onClick={() => rotate(1)}
              >
                <Mi name="arrow_forward" />
              </button>
            </span>
          </span>
        )}
      </header>

      <div
        className={`rating-signals-stage${multiple ? "" : " is-single"}`}
        aria-label="Carrossel circular dos fatores"
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            rotate(-1);
          }
          if (event.key === "ArrowRight") {
            event.preventDefault();
            rotate(1);
          }
        }}
        onPointerDown={(event) => {
          if (!event.isPrimary) return;
          pointerStartRef.current = {
            id: event.pointerId,
            x: event.clientX,
          };
        }}
        onPointerUp={(event) => {
          const start = pointerStartRef.current;
          pointerStartRef.current = null;
          if (!start || start.id !== event.pointerId) return;

          const distance = event.clientX - start.x;
          if (Math.abs(distance) < SWIPE_THRESHOLD) return;
          rotate(distance < 0 ? 1 : -1);
        }}
        onPointerCancel={() => {
          pointerStartRef.current = null;
        }}
      >
        {track.map(({ position, cardIndex, virtualIndex }) => {
          const card = cards[cardIndex];
          if (!card) return null;
          const active = position === "active";

          return (
            <article
              className={`rating-signal-card is-${position} ${signalTone(card)}`}
              data-slot={position}
              key={`signal-${virtualIndex}`}
              tabIndex={active ? 0 : -1}
              aria-hidden={active ? undefined : true}
              aria-label={
                active ? `${card.title}: ${card.formattedImpact}` : undefined
              }
            >
              <span className="rating-signal-card-head">
                <span className="rating-signal-icon" aria-hidden="true">
                  <Mi name={card.icon} />
                </span>
                <b>{card.title}</b>
              </span>
              <span
                className="rating-signal-impact-wrap"
                data-tag={card.formattedImpact}
              >
                <strong className="rating-signal-impact">
                  {card.formattedImpact}
                </strong>
                <span className="rating-signal-accent" aria-hidden="true" />
              </span>
              <p>{card.description}</p>
            </article>
          );
        })}
      </div>

      <span className="rating-signals-live" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </span>
    </section>
  );
}
