"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널)
// 변형 섹션 — 위치 X/Y + 회전°. 배경 패널에선 크기 W/H 추가.
// X/Y w=97 h=40, 회전 w=53 h=40, gap=8. radius·padding 은 NumericStepper primitive 위임.

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

  // figma 2026-05-18 redesign — split the row under the 변형 header into two
  // sub-labelled columns: position (X/Y) and rotation (°). Background
  // overlays add an extra size (W/H) row below. The earlier "위치/회전"
  // single-row layout with three steppers did not match the goal capture.
  return (
    <section className="space-y-2">
      <header className="text-xs font-semibold text-grayscale-800">
        {t.transform.sectionLabel}
      </header>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-medium text-grayscale-500">위치</span>
          <div className="grid grid-cols-2 gap-1">
            <NumericStepper
              value={xPct}
              min={0}
              max={100}
              onChange={(v) => updateTransform({ x: v / 100 })}
              unit="X"
              ariaLabel="X position"
            />
            <NumericStepper
              value={yPct}
              min={0}
              max={100}
              onChange={(v) => updateTransform({ y: v / 100 })}
              unit="Y"
              ariaLabel="Y position"
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-medium text-grayscale-500">회전</span>
          <NumericStepper
            value={rotInt}
            min={-360}
            max={360}
            onChange={(v) => updateTransform({ rotationDeg: v })}
            unit="°"
            ariaLabel="rotation"
          />
        </div>
      </div>

      {/* Background-only: explicit W/H underneath 위치/회전 */}
      {overlay.kind === "background" && (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-medium text-grayscale-500">{t.transform.size}</span>
          <div className="grid grid-cols-2 gap-1">
            <NumericStepper
              value={tf.widthPx ?? 0}
              min={1}
              max={10000}
              onChange={(v) => updateTransform({ widthPx: v })}
              unit={t.transform.width}
              ariaLabel={`${t.transform.size} width`}
            />
            <NumericStepper
              value={tf.heightPx ?? 0}
              min={1}
              max={10000}
              onChange={(v) => updateTransform({ heightPx: v })}
              unit={t.transform.height}
              ariaLabel={`${t.transform.size} height`}
            />
          </div>
        </div>
      )}
    </section>
  );
}
