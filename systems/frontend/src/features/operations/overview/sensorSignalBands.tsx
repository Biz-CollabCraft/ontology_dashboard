import type { OperationsSensorBandSpec } from "../api/operationsContracts";

export type SensorChartDomain = { min: number; max: number };

function finiteBandValues(bands: OperationsSensorBandSpec | null | undefined) {
  return (bands?.ranges ?? [])
    .flatMap((range) => [range.lower, range.upper])
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
}

export function sensorChartDomain(
  values: number[],
  bands: OperationsSensorBandSpec | null | undefined,
): SensorChartDomain {
  const finite = values.filter((value) => Number.isFinite(value));
  const candidates = [...finite, ...finiteBandValues(bands)];
  if (!candidates.length) return { min: 0, max: 1 };
  let min = Math.min(...candidates);
  let max = Math.max(...candidates);
  if (min === max) {
    const pad = Math.max(Math.abs(max) * 0.08, 1);
    min -= pad;
    max += pad;
  } else {
    const pad = Math.max((max - min) * 0.08, 1e-6);
    min -= pad;
    max += pad;
  }
  return { min, max };
}

export function sensorBandY(
  value: number,
  domain: SensorChartDomain,
  top: number,
  height: number,
) {
  const span = Math.max(domain.max - domain.min, 1e-6);
  return top + (1 - (value - domain.min) / span) * height;
}

export function SensorSignalBandBackground({
  bands,
  domain,
  x = 0,
  y = 0,
  width = 100,
  height = 100,
}: {
  bands: OperationsSensorBandSpec | null | undefined;
  domain: SensorChartDomain;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}) {
  if (!bands?.ranges?.length) return null;
  const order = { critical: 0, attention: 1, normal: 2 };
  return (
    <g className="sensor-signal-bands" aria-hidden="true">
      {[...bands.ranges]
        .sort((a, b) => order[a.status] - order[b.status])
        .map((range, index) => {
          const lower = Math.max(range.lower ?? domain.min, domain.min);
          const upper = Math.min(range.upper ?? domain.max, domain.max);
          if (!(upper > lower)) return null;
          const topY = sensorBandY(upper, domain, y, height);
          const bottomY = sensorBandY(lower, domain, y, height);
          return (
            <rect
              key={`${range.status}-${index}-${lower}-${upper}`}
              className={`sensor-signal-band sensor-signal-band-${range.status}`}
              x={x}
              y={topY}
              width={width}
              height={Math.max(0, bottomY - topY)}
            />
          );
        })}
    </g>
  );
}
