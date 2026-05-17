import { useCallback } from "react";

interface PreeditHeaderProps {
  title: string;
  onTitleChange: (title: string) => void;
}

export function PreeditHeader({ title, onTitleChange }: PreeditHeaderProps) {
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onTitleChange(e.target.value);
    },
    [onTitleChange],
  );

  return (
    <div className="flex items-center gap-4 border-b border-gray-200 bg-white px-6 py-3">
      <input
        type="text"
        value={title}
        onChange={handleChange}
        placeholder="제목 없는 가편집"
        className="flex-1 border-none bg-transparent text-lg font-semibold text-gray-900 outline-none placeholder:text-gray-400"
      />
      <span className="text-xs text-gray-400">자동 저장됨</span>
    </div>
  );
}
