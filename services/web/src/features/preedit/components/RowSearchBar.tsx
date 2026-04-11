import { useState, useCallback } from "react";

interface RowSearchBarProps {
  query: string;
  onSearch: (query: string) => void;
  isLoading: boolean;
}

export function RowSearchBar({ query, onSearch, isLoading }: RowSearchBarProps) {
  const [input, setInput] = useState(query);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (input.trim()) {
        onSearch(input.trim());
      }
    },
    [input, onSearch],
  );

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="찾고 싶은 장면을 설명해보세요..."
        className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 outline-none transition-colors focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
      />
      <button
        type="submit"
        disabled={isLoading || !input.trim()}
        className="rounded-lg bg-indigo-500 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-600 disabled:bg-gray-300 disabled:text-gray-500"
      >
        {isLoading ? (
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
        ) : (
          "검색"
        )}
      </button>
    </form>
  );
}
