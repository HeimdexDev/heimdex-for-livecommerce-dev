"use client";

// figma: 1602:41198 (배경 섹션)
// 우측 패널 "배경" 탭 — 단색/이미지 추가 + 변형·윤곽선·불투명도·그림자 컨트롤

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

import { LabeledSlider } from "./primitives/LabeledSlider";
import { NumericStepper } from "./primitives/NumericStepper";
import { ImageIcon, PlusIcon } from "./primitives/icons";
import { t } from "../lib/i18n/strings";

type FillVariant = "contain" | "cover" | "stretch";

export type BackgroundColorTarget = "stroke" | "shadow";

export interface BackgroundPanelState {
  variant: FillVariant;
  x: number;
  y: number;
  rotationDeg: number;
  widthPx: number;
  heightPx: number;
  strokeWidthPx: number;
  strokeColor: string;
  opacityPct: number;
  shadowOffsetX: number;
  shadowOffsetY: number;
  shadowSpreadPx: number;
  shadowColor: string;
  shadowBlurPx: number;
}

const DEFAULT_STATE: BackgroundPanelState = {
  variant: "cover",
  x: 0,
  y: 0,
  rotationDeg: 0,
  widthPx: 0,
  heightPx: 0,
  strokeWidthPx: 25,
  strokeColor: "#FFFFFF",
  opacityPct: 42,
  shadowOffsetX: 0,
  shadowOffsetY: 0,
  shadowSpreadPx: 25,
  shadowColor: "#000000",
  shadowBlurPx: 12,
};

interface BackgroundPanelProps {
  initialState?: Partial<BackgroundPanelState>;
  onAddSolidBackground?: () => void;
  /**
   * Called when the user picks an image via the OS file explorer.
   * Receives the selected image as a data URL (base64). Caller writes it
   * into the composition state.
   */
  onInsertImage?: (dataUrl: string) => void;
  onColorClick?: (target: BackgroundColorTarget, currentColor: string) => void;
  className?: string;
}

export function BackgroundPanel({
  initialState,
  onAddSolidBackground,
  onInsertImage,
  onColorClick,
  className,
}: BackgroundPanelProps) {
  const [state, setState] = useState<BackgroundPanelState>(() => ({
    ...DEFAULT_STATE,
    ...initialState,
  }));

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const set = <K extends keyof BackgroundPanelState>(
    key: K,
    value: BackgroundPanelState[K],
  ) => setState((prev) => ({ ...prev, [key]: value }));

  const handleInsertImageClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === "string") {
        onInsertImage?.(result);
      }
    };
    reader.readAsDataURL(file);
    // 같은 파일 재선택 시에도 onchange 가 발화하도록 value 초기화
    event.target.value = "";
  };

  return (
    <div className={cn("flex flex-col gap-4 p-4", className)}>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        onChange={handleFileChange}
        className="hidden"
        aria-hidden
      />
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            leadingIcon={<PlusIcon />}
            onClick={onAddSolidBackground}
          >
            {t.actions.addBackground}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={<ImageIcon />}
            onClick={handleInsertImageClick}
          >
            {t.actions.insertImage}
          </Button>
        </div>
        <VariantToggle
          value={state.variant}
          onChange={(v) => set("variant", v)}
        />
      </header>

      <Section label={t.transform.sectionLabel}>
        <Row label={t.transform.positionRotation}>
          <NumericStepper
            value={state.x}
            min={-100}
            max={100}
            onChange={(v) => set("x", v)}
            unit="X"
            ariaLabel="X position"
            className="flex-1"
          />
          <NumericStepper
            value={state.y}
            min={-100}
            max={100}
            onChange={(v) => set("y", v)}
            unit="Y"
            ariaLabel="Y position"
            className="flex-1"
          />
          <NumericStepper
            value={state.rotationDeg}
            min={-360}
            max={360}
            onChange={(v) => set("rotationDeg", v)}
            unit="°"
            ariaLabel="rotation"
            className="flex-1"
          />
        </Row>
        <Row label={t.transform.size}>
          <NumericStepper
            value={state.widthPx}
            min={0}
            max={10000}
            onChange={(v) => set("widthPx", v)}
            unit={t.transform.width}
            ariaLabel="width"
            className="flex-1"
          />
          <NumericStepper
            value={state.heightPx}
            min={0}
            max={10000}
            onChange={(v) => set("heightPx", v)}
            unit={t.transform.height}
            ariaLabel="height"
            className="flex-1"
          />
        </Row>
      </Section>

      <Section label={t.effects.stroke}>
        <Row label={t.effects.stroke}>
          <NumericStepper
            value={state.strokeWidthPx}
            min={0}
            max={100}
            onChange={(v) => set("strokeWidthPx", v)}
            unit="px"
            ariaLabel="stroke width"
            className="flex-1"
          />
          <ColorSwatchPlaceholder
            color={state.strokeColor}
            onClick={() => onColorClick?.("stroke", state.strokeColor)}
            ariaLabel={`${t.effects.stroke} 색`}
          />
        </Row>
      </Section>

      <Section label={t.effects.opacity}>
        <LabeledSlider
          value={state.opacityPct}
          onChange={(v) => set("opacityPct", v)}
          min={0}
          max={100}
          formatReadout={(v) => `${v}%`}
          ariaLabel={t.effects.opacity}
        />
      </Section>

      <Section label={t.effects.shadow}>
        <Row label={t.effects.shadowPositionColor}>
          <NumericStepper
            value={state.shadowOffsetX}
            min={-100}
            max={100}
            onChange={(v) => set("shadowOffsetX", v)}
            unit="X"
            ariaLabel="shadow offset X"
            className="flex-1"
          />
          <NumericStepper
            value={state.shadowOffsetY}
            min={-100}
            max={100}
            onChange={(v) => set("shadowOffsetY", v)}
            unit="Y"
            ariaLabel="shadow offset Y"
            className="flex-1"
          />
        </Row>
        <Row label={t.effects.spread}>
          <NumericStepper
            value={state.shadowSpreadPx}
            min={0}
            max={100}
            onChange={(v) => set("shadowSpreadPx", v)}
            unit="px"
            ariaLabel="shadow spread"
            className="flex-1"
          />
          <ColorSwatchPlaceholder
            color={state.shadowColor}
            onClick={() => onColorClick?.("shadow", state.shadowColor)}
            ariaLabel={`${t.effects.shadow} 색`}
          />
        </Row>
        <Row label={t.effects.blur}>
          <LabeledSlider
            value={state.shadowBlurPx}
            onChange={(v) => set("shadowBlurPx", v)}
            min={0}
            max={200}
            formatReadout={(v) => `${v}px`}
            ariaLabel={t.effects.blur}
          />
        </Row>
      </Section>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold text-grayscale-800">{label}</h3>
      {children}
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
      <span className="text-xs text-grayscale-500">{label}</span>
      <div className="flex items-stretch gap-2">{children}</div>
    </div>
  );
}

function ColorSwatchPlaceholder({
  color,
  onClick,
  ariaLabel,
}: {
  color: string;
  onClick: () => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-grayscale-200 bg-white p-0.5"
    >
      <span
        className="block h-full w-full rounded"
        style={{ backgroundColor: color }}
      />
    </button>
  );
}

const VARIANT_OPTIONS: Array<{ value: FillVariant; ariaLabel: string }> = [
  { value: "contain", ariaLabel: "맞춤" },
  { value: "cover", ariaLabel: "채움" },
  { value: "stretch", ariaLabel: "늘이기" },
];

function VariantToggle({
  value,
  onChange,
}: {
  value: FillVariant;
  onChange: (v: FillVariant) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-grayscale-200 bg-white p-0.5">
      {VARIANT_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          aria-label={opt.ariaLabel}
          aria-pressed={value === opt.value}
          className={cn(
            "inline-flex h-7 w-7 items-center justify-center rounded transition-colors",
            value === opt.value
              ? "bg-heimdex-navy-50 text-heimdex-navy-500"
              : "text-grayscale-500 hover:text-grayscale-800",
          )}
        >
          <VariantIcon variant={opt.value} />
        </button>
      ))}
    </div>
  );
}

function VariantIcon({ variant }: { variant: FillVariant }) {
  const common = {
    className: "h-4 w-4",
    fill: "none",
    viewBox: "0 0 24 24",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (variant === "contain") {
    return (
      <svg {...common} aria-hidden>
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <rect x="7" y="9" width="10" height="6" rx="1" />
      </svg>
    );
  }
  if (variant === "cover") {
    return (
      <svg {...common} aria-hidden>
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M3 12h18M12 3v18" />
      </svg>
    );
  }
  return (
    <svg {...common} aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 8h18M3 16h18" />
    </svg>
  );
}
