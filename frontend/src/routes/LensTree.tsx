import {
  useRef,
  type CSSProperties,
  type KeyboardEvent,
} from "react";

import { Mi } from "../components";
import type { LensAxis, LensAxisKey, LensMetric } from "./lensModel";

export interface LensTreeProps {
  axes: LensAxis[];
  overallScore: number;
  overallPercentile: number;
  partial?: boolean;
  activeKey: LensAxisKey;
  activeMetricKey: string | null;
  onSelectAxis: (key: LensAxisKey) => void;
  onSelectMetric: (axis: LensAxisKey, metric: string) => void;
}

interface TreePoint {
  x: number;
  y: number;
}

const TREE_SIZE = 680;
const CENTER = TREE_SIZE / 2;
const BRANCH_RADIUS = 154;
const LEAF_RADIUS = 284;
const LEAF_SPREAD = 56;

const AXIS_ANGLES: Record<LensAxisKey, number> = {
  adapt: -90,
  eco: -18,
  surv: 54,
  meta: 126,
  impact: 198,
};

const AXIS_ICONS: Record<LensAxisKey, string> = {
  adapt: "shuffle",
  eco: "toll",
  surv: "shield",
  meta: "query_stats",
  impact: "electric_bolt",
};

function polarPoint(radius: number, angle: number): TreePoint {
  const radians = angle * Math.PI / 180;
  return {
    x: CENTER + Math.cos(radians) * radius,
    y: CENTER + Math.sin(radians) * radius,
  };
}

function metricAngle(axisAngle: number, index: number, count: number): number {
  if (count <= 1) return axisAngle;
  return axisAngle - LEAF_SPREAD / 2 + index * (LEAF_SPREAD / (count - 1));
}

function axisColor(key: LensAxisKey): string {
  return `var(--lens-${key})`;
}

function nodeStyle(point: TreePoint, color: string, score: number): CSSProperties {
  return {
    left: `${(point.x / TREE_SIZE) * 100}%`,
    top: `${(point.y / TREE_SIZE) * 100}%`,
    "--lens-axis-color": color,
    "--lens-node-score": `${Math.max(0, Math.min(score, 100))}%`,
  } as CSSProperties;
}

function connectorPath(from: TreePoint, to: TreePoint): string {
  const controlA = {
    x: from.x + (to.x - from.x) * 0.46,
    y: from.y + (to.y - from.y) * 0.18,
  };
  const controlB = {
    x: from.x + (to.x - from.x) * 0.82,
    y: from.y + (to.y - from.y) * 0.78,
  };
  return `M ${from.x} ${from.y} C ${controlA.x} ${controlA.y}, ${controlB.x} ${controlB.y}, ${to.x} ${to.y}`;
}

function LensTreeLeaf({
  axis,
  metric,
  point,
  selected,
  onSelect,
}: {
  axis: LensAxis;
  metric: LensMetric;
  point: TreePoint;
  selected: boolean;
  onSelect: () => void;
}) {
  const style = nodeStyle(point, axisColor(axis.key), metric.score ?? 12);

  if (!metric.available) {
    return (
      <span
        className="lens-tree-node lens-tree-leaf is-locked"
        style={style}
        role="img"
        aria-label={`${metric.label}, indisponível`}
        data-label={metric.label}
      >
        <Mi name="lock" />
      </span>
    );
  }

  return (
    <button
      type="button"
      className={`lens-tree-node lens-tree-leaf${selected ? " is-selected" : ""}`}
      style={style}
      aria-label={`${axis.label}: ${metric.label}, nota ${metric.score} de 100`}
      aria-pressed={selected}
      data-label={metric.label}
      onClick={onSelect}
    >
      <strong>{metric.score}</strong>
    </button>
  );
}

export function LensTree({
  axes,
  overallScore,
  overallPercentile,
  partial = false,
  activeKey,
  activeMetricKey,
  onSelectAxis,
  onSelectMetric,
}: LensTreeProps) {
  const axisRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const onAxisKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      next = (index + 1) % axes.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = (index - 1 + axes.length) % axes.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = axes.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    onSelectAxis(axes[next].key);
    axisRefs.current[next]?.focus();
  };

  return (
    <section
      className="lens-performance-tree"
      aria-label="Árvore de desempenho do Arena Lens"
      aria-describedby="lens-tree-description"
    >
      <p id="lens-tree-description" className="sr-only">
        A nota geral ocupa o centro. Cinco eixos formam o primeiro nível e suas métricas
        formam o segundo. Selecione um nó para abrir a análise correspondente.
      </p>

      <div className="lens-tree-viewport">
        <div className="lens-tree-canvas">
          <svg
            className="lens-tree-connectors"
            viewBox={`0 0 ${TREE_SIZE} ${TREE_SIZE}`}
            aria-hidden="true"
          >
            {axes.map((axis) => {
              const branch = polarPoint(BRANCH_RADIUS, AXIS_ANGLES[axis.key]);
              const isActive = axis.key === activeKey;
              return (
                <g
                  key={axis.key}
                  className={isActive ? "is-active" : "is-muted"}
                  style={{ "--lens-axis-color": axisColor(axis.key) } as CSSProperties}
                >
                  <path
                    className="lens-tree-trunk"
                    d={connectorPath({ x: CENTER, y: CENTER }, branch)}
                  />
                  {axis.metrics.map((metric, index) => {
                    const leaf = polarPoint(
                      LEAF_RADIUS,
                      metricAngle(AXIS_ANGLES[axis.key], index, axis.metrics.length),
                    );
                    return (
                      <path
                        key={metric.key}
                        className={`lens-tree-twig${metric.available ? "" : " is-locked"}`}
                        d={connectorPath(branch, leaf)}
                      />
                    );
                  })}
                </g>
              );
            })}
          </svg>

          <div
            className={`lens-tree-core${partial ? " is-partial" : ""}`}
            aria-label={partial ? "Nota global indisponível: Lens parcial" : `Nota geral ${overallScore} de 100`}
            role="img"
          >
            <span>Lens</span>
            <strong>{partial ? "—" : overallScore}</strong>
            <small>{partial ? "14/20 partidas" : `Top ${Math.round((1 - overallPercentile) * 100)}%`}</small>
          </div>

          {axes.map((axis, axisIndex) => {
            const branch = polarPoint(BRANCH_RADIUS, AXIS_ANGLES[axis.key]);
            const isActive = axis.key === activeKey;
            return (
              <div key={axis.key} className={`lens-tree-cluster${isActive ? " is-active" : ""}`}>
                <button
                  ref={(node) => { axisRefs.current[axisIndex] = node; }}
                  type="button"
                  id={`lens-tree-axis-${axis.key}`}
                  className="lens-tree-node lens-tree-branch"
                  style={nodeStyle(branch, axisColor(axis.key), axis.score)}
                  aria-label={`${axis.label}, nota ${axis.score} de 100`}
                  aria-controls={`lens-panel-${axis.key}`}
                  aria-pressed={isActive}
                  tabIndex={isActive ? 0 : -1}
                  data-label={axis.label}
                  onClick={() => onSelectAxis(axis.key)}
                  onKeyDown={(event) => onAxisKeyDown(event, axisIndex)}
                >
                  <Mi name={AXIS_ICONS[axis.key]} />
                  <strong>{axis.score}</strong>
                  <span className="lens-tree-branch-label">{axis.shortLabel}</span>
                </button>

                {axis.metrics.map((metric, metricIndex) => (
                  <LensTreeLeaf
                    key={metric.key}
                    axis={axis}
                    metric={metric}
                    point={polarPoint(
                      LEAF_RADIUS,
                      metricAngle(AXIS_ANGLES[axis.key], metricIndex, axis.metrics.length),
                    )}
                    selected={activeMetricKey === metric.key}
                    onSelect={() => onSelectMetric(axis.key, metric.key)}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
