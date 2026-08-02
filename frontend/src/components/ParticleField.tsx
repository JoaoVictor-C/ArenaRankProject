import { useMemo, useRef, type CSSProperties } from "react";
import * as motion from "../lib/motion";

type ParticleFieldProps = {
  variant?: "global" | "route";
};

type Mote = {
  left: number;
  top: number;
  size: number;
  alpha: number;
  travelDuration: number;
  swayDuration: number;
  swayDistance: number;
  gold: boolean;
};

type MoteStyle = CSSProperties & {
  "--pfield-alpha": number;
};

const randomBetween = (min: number, max: number) =>
  min + Math.random() * (max - min);

export function ParticleField({ variant = "global" }: ParticleFieldProps) {
  const fieldRef = useRef<HTMLDivElement>(null);
  const motes = useMemo<Mote[]>(() => {
    const count = variant === "global" ? 34 : 16;
    return Array.from({ length: count }, (_, index) => ({
      left: randomBetween(1, 99),
      top: randomBetween(0, 100),
      size: Math.floor(randomBetween(1, 4)),
      alpha: randomBetween(0.05, 0.11),
      travelDuration: randomBetween(22, 48),
      swayDuration: randomBetween(9, 16),
      swayDistance: randomBetween(10, 18) * (index % 2 === 0 ? 1 : -1),
      gold: (index + 1) % 4 === 0,
    }));
  }, [variant]);

  /*
   * Alguns testes de rota isolam motion.ts com um mock parcial. Fora deles,
   * a checagem centralizada mantém a textura estática em reduced motion.
   */
  const reducedMotion =
    "prefersReducedMotion" in motion ? motion.prefersReducedMotion() : true;
  const loops = useMemo<motion.LoopMotion[]>(
    () =>
      reducedMotion
        ? []
        : motes.flatMap((mote, index) => {
            const selector = `[data-pfield-mote="${index}"]`;
            return [
              {
                selector,
                to: { y: variant === "global" ? "-115vh" : -700 },
                duration: mote.travelDuration,
                repeat: -1,
                ease: "none",
              },
              {
                selector,
                to: { x: mote.swayDistance },
                duration: mote.swayDuration,
                repeat: -1,
                yoyo: true,
                ease: "sine.inOut",
              },
            ];
          }),
    [motes, reducedMotion, variant],
  );

  motion.useGsapLoop(fieldRef, loops, [variant], {
    minimal: true,
    disabled: reducedMotion,
  });

  return (
    <div
      ref={fieldRef}
      className={`pfield pfield--${variant}`}
      aria-hidden="true"
    >
      {motes.map((mote, index) => (
        <span
          key={index}
          className={`pfield__mote${mote.gold ? " pfield__mote--gold" : ""}`}
          data-pfield-mote={index}
          style={
            {
              left: `${mote.left}%`,
              top: `${mote.top}%`,
              width: mote.size,
              height: mote.size,
              "--pfield-alpha": mote.alpha,
            } as MoteStyle
          }
        />
      ))}
    </div>
  );
}
