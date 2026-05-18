"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널)
// 그림자 컨트롤 — 위치 X/Y NumericStepper + 색상 swatch + 확산 stepper + 블러 LabeledSlider
// BackgroundPanel + TextOverlayPanel 공용

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { LabeledSlider } from "../primitives/LabeledSlider";
import { NumericStepper } from "../primitives/NumericStepper";
import { t } from "../../lib/i18n/strings";

export interface ShadowControlValue {
  offsetX: number;
  offsetY: number;
  spread: number;
  color: string;
  blur: number;
}

interface ShadowControlProps {
  offsetX: number;
  offsetY: number;
  spread: number;
  color: string;
  blur: number;
  onChange: (next: ShadowControlValue) => void;
  /**
   * Optional click handler for opening a custom color picker dialog
   * (color picker dialog). When omitted the native picker handles
   * color change via the swatch button.
   */
  onColorClick?: () => void;
  disabled?: boolean;
}

/**
 * Shadow controls — offset X/Y stepper + color swatch + blur slider + spread stepper.
 *
 * Headless of effect state: callers decide when to render (e.g. only when
 * `effects.shadow != null`). This component owns no toggle.
 *
 * onChange always receives the FULL ShadowControlValue, so callers can
 * spread it into their domain shape without merging.
 */
export function ShadowControl({
  offsetX,
  offsetY,
  spread,
  color,
  blur,
  onChange,
  onColorClick,
  disabled = false,
}: ShadowControlProps) {
  const emit = (patch: Partial<ShadowControlValue>) => {
    onChange({ offsetX, offsetY, spread, color, blur, ...patch });
  };

  // figma 2026-05-18 redesign — row 1 packs position (X/Y) + spread (px) +
  // color chip under their own sub-labels; row 2 is the blur slider. The
  // older layout (position → blur → spread in separate full-width rows)
  // was dropped because the right wrapper is only 371px wide and the goal
  // capture shows all three primary numeric controls on a single line.
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[1fr_auto_auto] items-end gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-medium text-grayscale-500">{t.effects.position}</span>
          <div className="grid grid-cols-2 gap-1">
            <NumericStepper
              value={offsetX}
              min={-100}
              max={100}
              onChange={(v) => emit({ offsetX: v })}
              unit="X"
              ariaLabel="shadow offset X"
              disabled={disabled}
            />
            <NumericStepper
              value={offsetY}
              min={-100}
              max={100}
              onChange={(v) => emit({ offsetY: v })}
              unit="Y"
              ariaLabel="shadow offset Y"
              disabled={disabled}
            />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] font-medium text-grayscale-500">{t.effects.spread}</span>
          <NumericStepper
            value={spread}
            min={0}
            max={100}
            onChange={(v) => emit({ spread: v })}
            unit="px"
            ariaLabel={t.effects.spread}
            disabled={disabled}
          />
        </div>
        {onColorClick ? (
          <button
            type="button"
            onClick={onColorClick}
            disabled={disabled}
            aria-label={`${t.effects.shadow} color`}
            className="h-9 w-9 rounded-lg border border-grayscale-200 bg-white p-0.5 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span
              className="block h-full w-full rounded"
              style={{ backgroundColor: color }}
            />
          </button>
        ) : (
          <ColorSwatchButton
            color={color}
            onChange={(c) => emit({ color: c })}
            ariaLabel={`${t.effects.shadow} color`}
            size="md"
            disabled={disabled}
          />
        )}
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-medium text-grayscale-500">{t.effects.blur}</span>
        <LabeledSlider
          value={blur}
          onChange={(v) => emit({ blur: v })}
          min={0}
          max={200}
          formatReadout={(v) => `${v}px`}
          ariaLabel={t.effects.blur}
          disabled={disabled}
        />
      </div>
    </div>
  );
}
