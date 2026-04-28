"use client";

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { LabeledSlider } from "../primitives/LabeledSlider";
import { NumericStepper } from "../primitives/NumericStepper";
import { t } from "../../lib/i18n/strings";
import type {
  EffectsProps,
  ShadowProps,
  StrokeProps,
} from "../../lib/overlay-types";

interface EffectsSectionProps {
  effects: EffectsProps;
  onChange: (effects: EffectsProps) => void;
}

const DEFAULT_STROKE: StrokeProps = { color: "#FF0000", widthPx: 2 };
const DEFAULT_SHADOW: ShadowProps = {
  color: "#FF0000",
  offsetX: 0,
  offsetY: 4,
  blurPx: 12,
  spreadPx: 0,
};

/**
 * Combined Opacity / Stroke / Shadow controls.
 *
 * Section-per-effect to mirror Figma. Opacity always present; stroke + shadow
 * have an "off" state (null) that the toggle blanks out the sub-controls
 * with a default object on enable.
 */
export function EffectsSection({ effects, onChange }: EffectsSectionProps) {
  const update = (patch: Partial<EffectsProps>) => {
    onChange({ ...effects, ...patch });
  };

  const updateShadow = (patch: Partial<ShadowProps>) => {
    if (!effects.shadow) return;
    update({ shadow: { ...effects.shadow, ...patch } });
  };

  return (
    <div className="space-y-4">
      {/* Opacity ------------------------------------------------------------- */}
      <section>
        <Header label={t.effects.opacity} />
        <LabeledSlider
          value={Math.round(effects.opacity * 100)}
          onChange={(v) => update({ opacity: v / 100 })}
          min={0}
          max={100}
          formatReadout={(v) => `${v}%`}
          ariaLabel={t.effects.opacity}
        />
      </section>

      {/* Stroke -------------------------------------------------------------- */}
      <section>
        <Header
          label={t.effects.stroke}
          enabled={effects.stroke != null}
          onToggle={() =>
            update({ stroke: effects.stroke ? null : { ...DEFAULT_STROKE } })
          }
        />
        {effects.stroke && (
          <div className="grid grid-cols-[80px_1fr_auto] items-center gap-2">
            <span className="text-xs text-gray-500">{t.effects.stroke}</span>
            <NumericStepper
              value={effects.stroke.widthPx}
              min={0}
              max={50}
              onChange={(v) =>
                update({
                  stroke: { ...effects.stroke!, widthPx: v },
                })
              }
              unit="px"
              ariaLabel="stroke width"
            />
            <ColorSwatchButton
              color={effects.stroke.color}
              onChange={(color) =>
                update({ stroke: { ...effects.stroke!, color } })
              }
              ariaLabel={`${t.effects.stroke} color`}
              size="md"
            />
          </div>
        )}
      </section>

      {/* Shadow -------------------------------------------------------------- */}
      <section>
        <Header
          label={t.effects.shadow}
          enabled={effects.shadow != null}
          onToggle={() =>
            update({ shadow: effects.shadow ? null : { ...DEFAULT_SHADOW } })
          }
        />
        {effects.shadow && (
          <div className="space-y-2">
            <div className="grid grid-cols-[80px_1fr_auto] items-center gap-2">
              <span className="text-xs text-gray-500">
                {t.effects.shadowPositionColor}
              </span>
              <div className="flex gap-2">
                <NumericStepper
                  value={effects.shadow.offsetX}
                  min={-100}
                  max={100}
                  onChange={(v) => updateShadow({ offsetX: v })}
                  unit="X"
                  ariaLabel="shadow offset X"
                  className="flex-1"
                />
                <NumericStepper
                  value={effects.shadow.offsetY}
                  min={-100}
                  max={100}
                  onChange={(v) => updateShadow({ offsetY: v })}
                  unit="Y"
                  ariaLabel="shadow offset Y"
                  className="flex-1"
                />
              </div>
              <ColorSwatchButton
                color={effects.shadow.color}
                onChange={(color) => updateShadow({ color })}
                ariaLabel={`${t.effects.shadow} color`}
                size="md"
              />
            </div>

            <div className="grid grid-cols-[80px_1fr] items-center gap-2">
              <span className="text-xs text-gray-500">{t.effects.blur}</span>
              <LabeledSlider
                value={effects.shadow.blurPx}
                onChange={(v) => updateShadow({ blurPx: v })}
                min={0}
                max={200}
                formatReadout={(v) => `${v}px`}
                ariaLabel={t.effects.blur}
              />
            </div>

            <div className="grid grid-cols-[80px_1fr] items-center gap-2">
              <span className="text-xs text-gray-500">{t.effects.spread}</span>
              <NumericStepper
                value={effects.shadow.spreadPx}
                min={0}
                max={100}
                onChange={(v) => updateShadow({ spreadPx: v })}
                unit="px"
                ariaLabel={t.effects.spread}
              />
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function Header({
  label,
  enabled,
  onToggle,
}: {
  label: string;
  enabled?: boolean;
  onToggle?: () => void;
}) {
  if (onToggle == null) {
    return (
      <h3 className="mb-2 text-xs font-semibold text-gray-700">{label}</h3>
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mb-2 flex w-full items-center justify-between text-xs font-semibold text-gray-700 hover:text-gray-900"
    >
      <span>{label}</span>
      <span
        className={enabled ? "text-indigo-600" : "text-gray-300"}
      >{enabled ? "ON" : "OFF"}</span>
    </button>
  );
}
