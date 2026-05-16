// ============================================================================
// 스타일 tab — page-level SubtitleStyleSpec editor for the auto-shorts
// edit-clips right panel.
//
// Renders only the fields the FFmpeg drawtext renderer respects today
// (Decision #2 in .claude/plans/edit-clips-right-panel-tabs.md). Rotation,
// shadow blur, shadow spread, italic, underline, horizontal flip are
// dropped — they'd produce a WYSIWYG lie.
//
// Pure presentation — caller owns the SubtitleStyleDraft state. Apply
// happens at the page layer (which de-normalises the draft into every
// cue's ``style`` field on PATCH).
// ============================================================================

"use client";

import { useId, type ChangeEvent } from "react";

import { cn } from "@/lib/utils";

import {
  makeDefaultStyle,
  mergeStyle,
  type SubtitleStyleDraft,
} from "../lib/global-style";

interface Props {
  /**
   * Current global style. ``null`` is the "혼합됨" state — cues across
   * the clip have different styles. The tab surfaces an Apply-to-all
   * affordance in that case so the operator can collapse to a single
   * style with one click.
   */
  currentStyle: SubtitleStyleDraft | null;
  /** Fires for every field tweak (live preview). */
  onStyleChange: (next: SubtitleStyleDraft) => void;
  /**
   * Fires when the operator clicks "글로벌로 적용" in the mixed-state
   * surface. The page promotes the currently-edited draft to every cue.
   */
  onApplyToAll?: () => void;
  /** Disables every input while a save is in flight. */
  disabled?: boolean;
  className?: string;
}

export function StyleTab({
  currentStyle,
  onStyleChange,
  onApplyToAll,
  disabled,
  className,
}: Props) {
  const effective = currentStyle ?? makeDefaultStyle();
  const isMixed = currentStyle === null;

  const update = (partial: Partial<SubtitleStyleDraft>) => {
    onStyleChange(mergeStyle(effective, partial));
  };

  return (
    <div
      className={cn("flex flex-col gap-6", className)}
      data-testid="style-tab"
    >
      {isMixed ? (
        <div
          className="flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"
          data-testid="style-tab-mixed-banner"
        >
          <span>
            장면별로 자막 스타일이 다릅니다. 한 스타일로 통일하시겠어요?
          </span>
          {onApplyToAll ? (
            <button
              type="button"
              onClick={onApplyToAll}
              className="rounded bg-amber-600 px-2 py-1 text-xs font-medium text-white hover:bg-amber-700"
              data-testid="style-tab-apply-all"
            >
              글로벌로 적용
            </button>
          ) : null}
        </div>
      ) : null}

      <FontRow
        style={effective}
        update={update}
        disabled={disabled}
      />

      <Section title="윤곽선">
        <div className="grid grid-cols-2 items-center gap-3">
          <Field label="굵기">
            <NumberStepper
              value={effective.stroke_width}
              min={0}
              max={10}
              suffix="px"
              onChange={(v) => update({ stroke_width: v })}
              disabled={disabled}
              testId="style-tab-stroke-width"
            />
          </Field>
          <ColorField
            label="색"
            value={effective.stroke_color ?? "#FF3B30"}
            onChange={(v) => update({ stroke_color: v })}
            disabled={disabled}
            testId="style-tab-stroke-color"
          />
        </div>
      </Section>

      <Section title="불투명도">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(effective.background_opacity * 100)}
            onChange={(e) =>
              update({ background_opacity: e.target.valueAsNumber / 100 })
            }
            disabled={disabled}
            className="flex-1"
            data-testid="style-tab-opacity-slider"
            aria-label="배경 불투명도"
          />
          <span className="w-12 text-right text-xs text-gray-600">
            {Math.round(effective.background_opacity * 100)}%
          </span>
        </div>
      </Section>

      <Section title="배경">
        <div className="grid grid-cols-2 items-center gap-3">
          <Field label="색">
            <ColorField
              value={effective.background_color ?? "#FFFFFF"}
              onChange={(v) => update({ background_color: v })}
              disabled={disabled}
              testId="style-tab-bg-color"
              label=""
            />
          </Field>
          <Field label="패딩">
            <NumberStepper
              value={effective.background_padding}
              min={0}
              max={50}
              suffix="px"
              onChange={(v) => update({ background_padding: v })}
              disabled={disabled}
              testId="style-tab-bg-padding"
            />
          </Field>
        </div>
      </Section>

      <Section title="위치">
        <div className="grid grid-cols-2 items-center gap-3">
          <Field label="X">
            <NumberStepper
              value={Math.round(effective.position_x * 100)}
              min={0}
              max={100}
              suffix="%"
              onChange={(v) => update({ position_x: clamp01(v / 100) })}
              disabled={disabled}
              testId="style-tab-position-x"
            />
          </Field>
          <Field label="Y">
            <NumberStepper
              value={Math.round(effective.position_y * 100)}
              min={0}
              max={100}
              suffix="%"
              onChange={(v) => update({ position_y: clamp01(v / 100) })}
              disabled={disabled}
              testId="style-tab-position-y"
            />
          </Field>
        </div>
      </Section>

      <Section title="그림자">
        <label
          className="flex items-center gap-2 text-xs text-gray-700"
          data-testid="style-tab-shadow-toggle-label"
        >
          <input
            type="checkbox"
            checked={effective.shadow_enabled}
            onChange={(e) => update({ shadow_enabled: e.target.checked })}
            disabled={disabled}
            data-testid="style-tab-shadow-toggle"
          />
          그림자 켜기
        </label>
        {effective.shadow_enabled ? (
          <div className="grid grid-cols-3 items-center gap-3">
            <Field label="X">
              <NumberStepper
                value={effective.shadow_offset_x}
                min={-20}
                max={20}
                suffix="px"
                onChange={(v) => update({ shadow_offset_x: v })}
                disabled={disabled}
                testId="style-tab-shadow-offset-x"
              />
            </Field>
            <Field label="Y">
              <NumberStepper
                value={effective.shadow_offset_y}
                min={-20}
                max={20}
                suffix="px"
                onChange={(v) => update({ shadow_offset_y: v })}
                disabled={disabled}
                testId="style-tab-shadow-offset-y"
              />
            </Field>
            <ColorField
              label="색"
              value={effective.shadow_color ?? "#000000"}
              onChange={(v) => update({ shadow_color: v })}
              disabled={disabled}
              testId="style-tab-shadow-color"
            />
          </div>
        ) : null}
      </Section>
    </div>
  );
}

// ----------------------------------------------------------------------
// Top row: font family + size + weight + align (per Figma row 1)
// ----------------------------------------------------------------------

interface FontRowProps {
  style: SubtitleStyleDraft;
  update: (partial: Partial<SubtitleStyleDraft>) => void;
  disabled?: boolean;
}

function FontRow({ style, update, disabled }: FontRowProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={style.font_family}
        onChange={(e) =>
          update({
            font_family: e.target.value as "Pretendard" | "Noto Sans KR",
          })
        }
        disabled={disabled}
        className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900"
        data-testid="style-tab-font-family"
      >
        <option value="Pretendard">Pretendard</option>
        <option value="Noto Sans KR">Noto Sans KR</option>
      </select>
      <NumberStepper
        value={style.font_size_px}
        min={8}
        max={200}
        suffix="pt"
        onChange={(v) => update({ font_size_px: v })}
        disabled={disabled}
        testId="style-tab-font-size"
      />
      <ToggleButton
        active={style.font_weight >= 700}
        onClick={() =>
          update({ font_weight: style.font_weight >= 700 ? 400 : 700 })
        }
        disabled={disabled}
        testId="style-tab-font-bold"
        ariaLabel="굵게"
      >
        B
      </ToggleButton>
      <select
        value={style.text_align}
        onChange={(e) =>
          update({
            text_align: e.target.value as "left" | "center" | "right",
          })
        }
        disabled={disabled}
        className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900"
        data-testid="style-tab-text-align"
      >
        <option value="left">왼쪽</option>
        <option value="center">가운데</option>
        <option value="right">오른쪽</option>
      </select>
      <ColorField
        label=""
        value={style.font_color}
        onChange={(v) => update({ font_color: v })}
        disabled={disabled}
        testId="style-tab-font-color"
      />
    </div>
  );
}

// ----------------------------------------------------------------------
// Tiny presentational primitives — kept inline because no other consumer.
// ----------------------------------------------------------------------

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-xs text-gray-600">
      {label ? <span className="shrink-0">{label}</span> : null}
      {children}
    </label>
  );
}

interface NumberStepperProps {
  value: number;
  min: number;
  max: number;
  suffix?: string;
  onChange: (value: number) => void;
  disabled?: boolean;
  testId?: string;
}

function NumberStepper({
  value,
  min,
  max,
  suffix,
  onChange,
  disabled,
  testId,
}: NumberStepperProps) {
  const clampedSet = (next: number) => {
    if (Number.isNaN(next)) return;
    onChange(Math.max(min, Math.min(max, next)));
  };
  return (
    <div className="inline-flex items-center rounded border border-gray-300 bg-white text-sm">
      <button
        type="button"
        onClick={() => clampedSet(value - 1)}
        disabled={disabled}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 disabled:text-gray-300"
        data-testid={testId ? `${testId}-dec` : undefined}
        aria-label="감소"
      >
        −
      </button>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          clampedSet(e.target.valueAsNumber)
        }
        disabled={disabled}
        className="w-12 border-0 bg-transparent px-1 py-1 text-center text-gray-900 focus:outline-none"
        data-testid={testId}
      />
      {suffix ? (
        <span className="pr-1 text-xs text-gray-500">{suffix}</span>
      ) : null}
      <button
        type="button"
        onClick={() => clampedSet(value + 1)}
        disabled={disabled}
        className="px-2 py-1 text-gray-500 hover:text-gray-900 disabled:text-gray-300"
        data-testid={testId ? `${testId}-inc` : undefined}
        aria-label="증가"
      >
        +
      </button>
    </div>
  );
}

interface ToggleButtonProps {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
  testId?: string;
  ariaLabel?: string;
}

function ToggleButton({
  active,
  onClick,
  disabled,
  children,
  testId,
  ariaLabel,
}: ToggleButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      data-active={active}
      aria-pressed={active}
      aria-label={ariaLabel}
      className={cn(
        "flex h-8 w-8 items-center justify-center rounded border text-sm font-bold",
        active
          ? "border-gray-900 bg-gray-900 text-white"
          : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
      )}
    >
      {children}
    </button>
  );
}

interface ColorFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  testId?: string;
}

function ColorField({
  label,
  value,
  onChange,
  disabled,
  testId,
}: ColorFieldProps) {
  const fieldId = useId();
  return (
    <div className="flex items-center gap-2">
      {label ? (
        <label htmlFor={fieldId} className="text-xs text-gray-600">
          {label}
        </label>
      ) : null}
      <input
        id={fieldId}
        type="color"
        value={normaliseHex(value)}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        disabled={disabled}
        className="h-8 w-8 cursor-pointer rounded border border-gray-300 bg-white p-0"
        data-testid={testId}
      />
    </div>
  );
}

function clamp01(v: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(1, v));
}

function normaliseHex(value: string): string {
  // ``<input type="color">`` requires #RRGGBB. Accept any hex; bail out on
  // weird values to avoid React warnings.
  if (/^#[0-9A-Fa-f]{6}$/.test(value)) return value;
  return "#000000";
}
