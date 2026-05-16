"use client";

// figma: 1602:41198 (배경 섹션) / 1607:65302 (텍스트·템플릿 패널 효과 영역)
// 효과 섹션 — 불투명도 LabeledSlider + 윤곽선(BorderControl) + 그림자(ShadowControl)
// 텍스트·배경 패널 공용. radius·padding 은 primitive 에 위임.

import { LabeledSlider } from "../primitives/LabeledSlider";
import { BorderControl } from "./BorderControl";
import { ShadowControl } from "./ShadowControl";
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
          <BorderControl
            width={effects.stroke.widthPx}
            color={effects.stroke.color}
            onWidthChange={(widthPx) =>
              update({ stroke: { ...(effects.stroke as StrokeProps), widthPx } })
            }
            onColorChange={(color) =>
              update({ stroke: { ...(effects.stroke as StrokeProps), color } })
            }
          />
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
          <ShadowControl
            offsetX={effects.shadow.offsetX}
            offsetY={effects.shadow.offsetY}
            spread={effects.shadow.spreadPx}
            blur={effects.shadow.blurPx}
            color={effects.shadow.color}
            onChange={(next) =>
              update({
                shadow: {
                  color: next.color,
                  offsetX: next.offsetX,
                  offsetY: next.offsetY,
                  blurPx: next.blur,
                  spreadPx: next.spread,
                },
              })
            }
          />
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
      <h3 className="mb-2 text-xs font-semibold text-grayscale-800">{label}</h3>
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mb-2 flex w-full items-center justify-between text-xs font-semibold text-grayscale-800 hover:text-heimdex-navy-500"
    >
      <span>{label}</span>
      <span
        className={enabled ? "text-heimdex-navy-500" : "text-grayscale-300"}
      >{enabled ? "ON" : "OFF"}</span>
    </button>
  );
}
