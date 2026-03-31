"use client";

import { SearchFilters, hasTagFilters, TAG_FILTER_FIELDS } from "@/lib/types/search";
import { TagFilterInput } from "./TagFilterInput";

interface TagFiltersProps {
  filters: SearchFilters;
  onFiltersChange: (filters: SearchFilters) => void;
}

const TAG_FILTER_ROWS: {
  label: string;
  includeField: keyof SearchFilters;
  excludeField: keyof SearchFilters;
}[] = [
  { label: "Keyword tags", includeField: "keyword_tags_in", excludeField: "keyword_tags_not_in" },
  { label: "Product tags", includeField: "product_tags_in", excludeField: "product_tags_not_in" },
  { label: "Product entities", includeField: "product_entities_in", excludeField: "product_entities_not_in" },
  { label: "AI 태그", includeField: "ai_tags_in", excludeField: "ai_tags_not_in" },
];

export function TagFilters({ filters, onFiltersChange }: TagFiltersProps) {
  const updateField = (field: keyof SearchFilters, tags: string[]) => {
    onFiltersChange({
      ...filters,
      [field]: tags.length > 0 ? tags : undefined,
    });
  };

  const clearTagFilters = () => {
    const cleared = { ...filters };
    for (const f of TAG_FILTER_FIELDS) {
      delete cleared[f];
    }
    onFiltersChange(cleared);
  };

  const hasTags = hasTagFilters(filters);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-700">Scene Tags</h4>
        {hasTags && (
          <button
            onClick={clearTagFilters}
            className="text-xs text-primary-600 hover:text-primary-700"
          >
            Clear tags
          </button>
        )}
      </div>

      {TAG_FILTER_ROWS.map(({ label, includeField, excludeField }) => (
        <div key={label} className="space-y-1.5">
          <span className="text-xs font-medium text-gray-600">{label}</span>
          <div className="space-y-1">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-green-600 font-medium">Include</span>
              <TagFilterInput
                tags={(filters[includeField] as string[] | undefined) ?? []}
                onChange={(tags) => updateField(includeField, tags)}
                placeholder={`Include ${label.toLowerCase()}…`}
              />
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-red-500 font-medium">Exclude</span>
              <TagFilterInput
                tags={(filters[excludeField] as string[] | undefined) ?? []}
                onChange={(tags) => updateField(excludeField, tags)}
                placeholder={`Exclude ${label.toLowerCase()}…`}
              />
            </div>
          </div>
        </div>
      ))}

      <p className="text-[10px] text-gray-400 leading-tight">
        Use exact product phrases when possible (e.g. &quot;모이스처라이저&quot;, &quot;쿠션&quot;, &quot;마스크팩&quot;).
      </p>
    </div>
  );
}
