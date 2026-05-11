// ============================================================================
// 자막 tab in the auto-shorts edit-clips right panel.
//
// Phase A: thin shell that delegates to the existing ``SubtitleEditor``
// without passing ``onRerenderRequested`` — the page-level
// ``ExportShortsButton`` now owns the render trigger, so the legacy in-editor
// footer button is hidden.
//
// Phase B: pipes a controlled search query + scene-clip list through to the
// editor so cues filter on text and group under scene headers per Figma.
//
// Phase C: forwards the imperative ref through so the StyleTab can push
// page-level style writes through the SAME hook the text editor uses.
//
// Phase E will fold SubtitleEditor's internals into this file.
// ============================================================================

"use client";

import { forwardRef, type ForwardedRef } from "react";

import {
  SubtitleEditor,
  type SubtitleEditorHandle,
  type SubtitleEditorProps,
} from "./SubtitleEditor";

type Props = Omit<SubtitleEditorProps, "onRerenderRequested" | "isRendering">;

export const SubtitlesTab = forwardRef(function SubtitlesTab(
  props: Props,
  ref: ForwardedRef<SubtitleEditorHandle>,
) {
  // Explicitly drop ``onRerenderRequested`` / ``isRendering`` so the
  // legacy footer render button stays hidden — the page-level export
  // button is the canonical render trigger now.
  return <SubtitleEditor ref={ref} {...props} />;
});
