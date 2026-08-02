import { ParticleField } from "./ParticleField";

/* Fundo do site: poeira em suspensão + blob multicolor borrado.
   SVG fiel ao design original (arena project / Leaderboard.html): gradiente radial
   roxo→amarelo→magenta→azul (opacity 0.7) num path orgânico, viewBox 1400×530. */
export function Background() {
  return (
    <>
      <ParticleField />
      <div className="blob-wrap" aria-hidden="true">
        <svg viewBox="0 0 1400 530" preserveAspectRatio="none">
          <defs>
            <radialGradient id="ar-blob-g1" cx="50%" cy="50%" r="60%">
              <stop offset="0%" stopColor="#6248ff" stopOpacity="0.7" />
              <stop offset="37%" stopColor="#e5ff48" stopOpacity="0.7" />
              <stop offset="59%" stopColor="#ff48ed" stopOpacity="0.7" />
              <stop offset="78%" stopColor="#48bdff" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#6248ff" stopOpacity="0.7" />
            </radialGradient>
          </defs>
          <path
            d="M 1113 112 C 707 395 383 271 283 170 C 254 152 183 66 60 44 C -93 17 79 377 217 462 C 356 547 834 564 1064 464 C 1358 336 1620 -240 1113 112 Z"
            fill="url(#ar-blob-g1)"
          />
        </svg>
      </div>
    </>
  );
}
