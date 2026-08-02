export type ChartPoint = {
  x: number;
  y: number;
};

export type CubicSegment = {
  start: ChartPoint;
  control1: ChartPoint;
  control2: ChartPoint;
  end: ChartPoint;
};

export type MonotoneGeometry = {
  line: string;
  area: string;
  segments: CubicSegment[];
};

const formatCoordinate = (value: number) =>
  Number(value.toFixed(3)).toString();

const pointCommand = (point: ChartPoint) =>
  `${formatCoordinate(point.x)} ${formatCoordinate(point.y)}`;

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(maximum, Math.max(minimum, value));

export type ChartDomain = {
  min: number;
  max: number;
};

/** Domínio do eixo Y ancorado na média da amostra exibida.
 *
 * Min-máx puro faz o gráfico mentir por escala: uma série que oscila 0,4pp
 * ocupa exatamente a mesma altura que uma que oscila 30pp, então a primeira lê
 * como despencando quando na prática está parada. O dado exibido continua sendo
 * o dado — nenhum ponto é suavizado — mas a régua passa a ser proporcional.
 *
 * O piso relativo é a peça que resolve: a amplitude nunca fica menor que uma
 * fração da própria média, o que funciona igual para percentual, contagem ou
 * PDL sem o chamador precisar declarar unidade. */
export function resolveChartDomain(
  values: number[],
  options: {
    /** Folga acima da amplitude real, para o traço não encostar na borda. */
    padding?: number;
    /** Amplitude mínima como fração da média (unidade-agnóstico). */
    relativeFloor?: number;
    /** Amplitude mínima absoluta, quando a unidade é conhecida. */
    minSpan?: number;
    /** Limites duros da unidade, ex.: [0, 100] para percentual. */
    bounds?: [number, number];
  } = {},
): ChartDomain {
  const { padding = 0.15, relativeFloor = 0.12, minSpan = 0, bounds } = options;
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return { min: 0, max: 1 };

  const mean = finite.reduce((sum, value) => sum + value, 0) / finite.length;
  const reach = Math.max(...finite.map((value) => Math.abs(value - mean)));

  const floor = Math.max(minSpan, Math.abs(mean) * relativeFloor) / 2;
  // Série perfeitamente plana com média zero ainda precisa de alguma altura.
  const half = Math.max(reach * (1 + padding), floor, Number.EPSILON);

  let min = mean - half;
  let max = mean + half;
  if (bounds) {
    min = clamp(min, bounds[0], bounds[1]);
    max = clamp(max, bounds[0], bounds[1]);
    if (max - min < Number.EPSILON) {
      min = bounds[0];
      max = bounds[1];
    }
  }
  return { min, max };
}

export function normalizeTimelineX(
  timestamps: number[],
  left: number,
  right: number,
): number[] {
  if (timestamps.length === 0) return [];
  if (timestamps.length === 1) return [left];

  const start = timestamps[0];
  const span = timestamps[timestamps.length - 1] - start;

  if (span <= 0) {
    return timestamps.map(
      (_, index) => left + ((right - left) * index) / (timestamps.length - 1),
    );
  }

  return timestamps.map(
    (timestamp) => left + ((timestamp - start) / span) * (right - left),
  );
}

export function buildMonotoneGeometry(
  points: ChartPoint[],
  baseline: number,
): MonotoneGeometry {
  if (points.length === 0) {
    return { line: "", area: "", segments: [] };
  }

  const first = points[0];
  if (points.length === 1) {
    const line = `M${pointCommand(first)}`;
    return {
      line,
      area: `M${formatCoordinate(first.x)} ${formatCoordinate(baseline)} L${pointCommand(first)} L${formatCoordinate(first.x)} ${formatCoordinate(baseline)} Z`,
      segments: [],
    };
  }

  const intervalWidths = points.slice(0, -1).map((point, index) => {
    const width = points[index + 1].x - point.x;
    return width > 0 ? width : Number.EPSILON;
  });
  const secants = intervalWidths.map(
    (width, index) => (points[index + 1].y - points[index].y) / width,
  );
  const tangents = new Array<number>(points.length);

  tangents[0] = secants[0];
  tangents[tangents.length - 1] = secants[secants.length - 1];

  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = secants[index - 1];
    const next = secants[index];

    if (previous === 0 || next === 0 || previous * next <= 0) {
      tangents[index] = 0;
      continue;
    }

    const previousWidth = intervalWidths[index - 1];
    const nextWidth = intervalWidths[index];
    const weight1 = 2 * nextWidth + previousWidth;
    const weight2 = nextWidth + 2 * previousWidth;
    tangents[index] =
      (weight1 + weight2) / (weight1 / previous + weight2 / next);
  }

  const segments = points.slice(0, -1).map((start, index) => {
    const end = points[index + 1];
    const width = end.x - start.x;
    const minimumY = Math.min(start.y, end.y);
    const maximumY = Math.max(start.y, end.y);

    return {
      start,
      control1: {
        x: start.x + width / 3,
        y: clamp(
          start.y + (tangents[index] * width) / 3,
          minimumY,
          maximumY,
        ),
      },
      control2: {
        x: end.x - width / 3,
        y: clamp(
          end.y - (tangents[index + 1] * width) / 3,
          minimumY,
          maximumY,
        ),
      },
      end,
    };
  });

  const curves = segments
    .map(
      ({ control1, control2, end }) =>
        `C${pointCommand(control1)} ${pointCommand(control2)} ${pointCommand(end)}`,
    )
    .join(" ");
  const line = `M${pointCommand(first)} ${curves}`;
  const last = points[points.length - 1];
  const area =
    `M${formatCoordinate(first.x)} ${formatCoordinate(baseline)} ` +
    `L${pointCommand(first)} ${curves} ` +
    `L${formatCoordinate(last.x)} ${formatCoordinate(baseline)} Z`;

  return { line, area, segments };
}
