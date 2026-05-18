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

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[80px_1fr_auto] items-center gap-2">
        <span className="text-xs text-grayscale-500">
          {t.effects.shadowPositionColor}
        </span>
        <div className="flex gap-2">
          <NumericStepper
            value={offsetX}
            min={-100}
            max={100}
            onChange={(v) => emit({ offsetX: v })}
            unit="X"
            ariaLabel="shadow offset X"
            disabled={disabled}
            className="flex-1"
          />
          <NumericStepper
            value={offsetY}
            min={-100}
            max={100}
            onChange={(v) => emit({ offsetY: v })}
            unit="Y"
            ariaLabel="shadow offset Y"
            disabled={disabled}
            className="flex-1"
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

      <div className="grid grid-cols-[80px_1fr] items-center gap-2">
        <span className="text-xs text-grayscale-500">{t.effects.blur}</span>
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

      <div className="grid grid-cols-[80px_1fr] items-center gap-2">
        <span className="text-xs text-grayscale-500">{t.effects.spread}</span>
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
    </div>
  );
}
