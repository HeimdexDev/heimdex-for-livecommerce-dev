/**
 * Korean strings for the V2 overlay panel.
 *
 * Lifted from inline JSX into one place so a future i18next migration is
 * a search-and-replace from `t.x.y` to `t("x.y")` rather than hunting
 * across 12 components. No actual translation runtime today — just keys.
 */

export const t = {
  tabs: {
    text: "텍스트",
    background: "배경",
  },
  actions: {
    addText: "텍스트 추가",
    addBackground: "단색 배경 추가",
    insertImage: "이미지 삽입",
    insertImageDisabledTooltip: "곧 제공 예정",
    deleteSelected: "삭제",
    saveCurrentStyle: "현재 스타일 저장",
  },
  text: {
    contentPlaceholder: "내용을 입력해주세요.",
    fontFamily: "글꼴",
    fontSize: "크기",
    bold: "굵게",
    italic: "기울임",
    underline: "밑줄",
    align: "정렬",
    lineSpacing: "줄 간격",
    color: "글자 색",
    highlight: "강조 색",
  },
  alignment: {
    left: "왼쪽",
    center: "가운데",
    right: "오른쪽",
  },
  background: {
    fillColor: "채우기 색",
    layerOrder: "레이어",
    sendToBack: "맨 뒤로",
    sendBackward: "뒤로",
    bringForward: "앞으로",
    bringToFront: "맨 앞으로",
  },
  transform: {
    sectionLabel: "변형",
    size: "크기",
    positionRotation: "위치/회전",
    width: "W",
    height: "H",
  },
  effects: {
    opacity: "불투명도",
    stroke: "윤곽선",
    shadow: "그림자",
    shadowPositionColor: "위치/색상",
    position: "위치",
    blur: "블러",
    spread: "확산",
    width: "굵기",
  },
  preset: {
    sectionLabel: "프리셋",
    namePlaceholder: "프리셋 이름을 적어주세요.",
    saveButton: "현재 스타일 저장",
    sharedBadge: "공유됨",
    shareToggleLabel: "조직 공유",
    deletePresetTooltip: "프리셋 삭제",
    emptyState: "저장된 프리셋이 없습니다.",
    loadingState: "프리셋 불러오는 중…",
    dialogTitle: "현재 스타일 저장",
    dialogConfirm: "저장",
    dialogCancel: "취소",
    applyButton: "적용하기",
  },
  empty: {
    panelHint: "타임라인에서 항목을 선택하거나 위 버튼을 눌러 추가하세요.",
  },
  errors: {
    saveFailed: "프리셋 저장에 실패했습니다.",
    listFailed: "프리셋을 불러올 수 없습니다.",
  },
} as const;

export type I18n = typeof t;
