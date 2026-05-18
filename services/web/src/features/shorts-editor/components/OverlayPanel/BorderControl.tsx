"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널)
// 윤곽선 컨트롤 — 굵기 NumericStepper + 색상 swatch
// BackgroundPanel + TextOverlayPanel 공용

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { NumericStepper } from "../primitives/NumericStepper";
import { t } from "../../lib/i18n/strings";

interface BorderControlProps {
  width: number;
  color: string;
  onWidthChange: (next: number) => void;
  onColorChange: (next: string) => void;
  /**
   * Optional click handler for opening a custom color picker dialog
   * (color picker dialog). When omitted the native picker handles
   * color change via onColorChange.
   */
  onColorClick?: () => void;
  disabled?: boolean;
}

/**
 * Border / stroke controls — width stepper + color swatch.
 *
 * Headless of effect state: callers decide when to render (e.g. only when
 * `effects.stroke != null`). This component owns no toggle; it's purely the
 * width + color row.
 */
export function BorderControl({
  width,
  color,
  onWidthChange,
  onColorChange,
  onColorClick,
  disabled = false,
}: BorderControlProps) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-medium text-grayscale-500">{t.effects.width}</span>
      <div className="flex items-stretch gap-2">
        <NumericStepper
          value={width}
          min={0}
          max={50}
          onChange={onWidthChange}
          unit="px"
          ariaLabel={`${t.effects.stroke} width`}
          disabled={disabled}
          className="flex-1"
        />
        {onColorClick ? (
          <button
            type="button"
            onClick={onColorClick}
            disabled={disabled}
            aria-label={`${t.effects.stroke} color`}
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
            onChange={onColorChange}
            ariaLabel={`${t.effects.stroke} color`}
            size="md"
            disabled={disabled}
          />
        )}
      </div>
    </div>
  );
}
