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
  // figma 1663:45821 / 1607:65622 — stroke is rendered alongside Transform
  // in a 2-col row, so EffectsSection skips it when the panel chooses to
  // host it separately.
  hideStroke?: boolean;
}

const DEFAULT_STROKE: StrokeProps = { color: "#FF0000", widthPx: 25 };
const DEFAULT_SHADOW: ShadowProps = {
  color: "#FF0000",
  offsetX: 0,
  offsetY: 99,
  blurPx: 12,
  spreadPx: 25,
};

/**
 * Combined Opacity / Stroke / Shadow controls.
 *
 * Section-per-effect to mirror Figma 2026-05-18 redesign. ON/OFF toggles
 * were removed — all sub-controls render unconditionally. When the
 * underlying overlay has a null stroke / shadow we render the controls
 * against DEFAULT values; the first user interaction materialises the
 * effect in state. This matches the figma capture where every section
 * shows live values regardless of whether the user has enabled them yet.
 */
export function EffectsSection({ effects, onChange, hideStroke = false }: EffectsSectionProps) {
  const update = (patch: Partial<EffectsProps>) => {
    onChange({ ...effects, ...patch });
  };

  const stroke = effects.stroke ?? DEFAULT_STROKE;
  const shadow = effects.shadow ?? DEFAULT_SHADOW;

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

      {/* Stroke — hidden when the panel hosts it alongside Transform ------------ */}
      {!hideStroke && (
        <section>
          <Header label={t.effects.stroke} />
          <BorderControl
            width={stroke.widthPx}
            color={stroke.color}
            onWidthChange={(widthPx) => update({ stroke: { ...stroke, widthPx } })}
            onColorChange={(color) => update({ stroke: { ...stroke, color } })}
          />
        </section>
      )}

      {/* Shadow -------------------------------------------------------------- */}
      <section>
        <Header label={t.effects.shadow} />
        <ShadowControl
          offsetX={shadow.offsetX}
          offsetY={shadow.offsetY}
          spread={shadow.spreadPx}
          blur={shadow.blurPx}
          color={shadow.color}
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
      </section>
    </div>
  );
}

// Standalone stroke section — same content as EffectsSection's stroke block.
// Used by panels that pair stroke with Transform in a 2-col row.
export function StrokeBlock({
  effects,
  onChange,
}: {
  effects: EffectsProps;
  onChange: (effects: EffectsProps) => void;
}) {
  const stroke = effects.stroke ?? DEFAULT_STROKE;
  return (
    <section>
      <Header label={t.effects.stroke} />
      <BorderControl
        width={stroke.widthPx}
        color={stroke.color}
        onWidthChange={(widthPx) =>
          onChange({ ...effects, stroke: { ...stroke, widthPx } })
        }
        onColorChange={(color) =>
          onChange({ ...effects, stroke: { ...stroke, color } })
        }
      />
    </section>
  );
}

function Header({ label }: { label: string }) {
  return (
    <h3 className="mb-2 text-xs font-semibold text-grayscale-800">{label}</h3>
  );
}
