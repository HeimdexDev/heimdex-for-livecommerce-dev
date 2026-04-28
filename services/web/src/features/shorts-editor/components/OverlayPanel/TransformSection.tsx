"use client";

import { NumericStepper } from "../primitives/NumericStepper";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlay, TransformProps } from "../../lib/overlay-types";

interface TransformSectionProps {
  overlay: EditorOverlay;
  onChange: (transform: TransformProps) => void;
}

/**
 * Transform: position (X/Y as %, since the spec stores normalized 0-1)
 * + rotation in degrees. Background overlays additionally show width/height
 * in absolute pixels.
 */
export function TransformSection({ overlay, onChange }: TransformSectionProps) {
  const tf = overlay.transform;

  const updateTransform = (patch: Partial<TransformProps>) => {
    onChange({ ...tf, ...patch });
  };

  const xPct = Math.round(tf.x * 100);
  const yPct = Math.round(tf.y * 100);
  const rotInt = Math.round(tf.rotationDeg);

  return (
    <section className="space-y-3">
      <header className="text-xs font-semibold text-gray-700">
        {t.transform.sectionLabel}
      </header>

      {/* Background-only: explicit W/H */}
      {overlay.kind === "background" && (
        <Row label={t.transform.size}>
          <NumericStepper
            value={tf.widthPx ?? 0}
            min={1}
            max={10000}
            onChange={(v) => updateTransform({ widthPx: v })}
            unit={t.transform.width}
            ariaLabel={`${t.transform.size} width`}
            className="flex-1"
          />
          <NumericStepper
            value={tf.heightPx ?? 0}
            min={1}
            max={10000}
            onChange={(v) => updateTransform({ heightPx: v })}
            unit={t.transform.height}
            ariaLabel={`${t.transform.size} height`}
            className="flex-1"
          />
        </Row>
      )}

      <Row label={t.transform.positionRotation}>
        <NumericStepper
          value={xPct}
          min={0}
          max={100}
          onChange={(v) => updateTransform({ x: v / 100 })}
          unit="X"
          ariaLabel="X position"
          className="flex-1"
        />
        <NumericStepper
          value={yPct}
          min={0}
          max={100}
          onChange={(v) => updateTransform({ y: v / 100 })}
          unit="Y"
          ariaLabel="Y position"
          className="flex-1"
        />
        <NumericStepper
          value={rotInt}
          min={-360}
          max={360}
          onChange={(v) => updateTransform({ rotationDeg: v })}
          unit="°"
          ariaLabel="rotation"
          className="flex-1"
        />
      </Row>
    </section>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[80px_1fr] items-center gap-2">
      <span className="text-xs text-gray-500">{label}</span>
      <div className="flex items-stretch gap-2">{children}</div>
    </div>
  );
}
