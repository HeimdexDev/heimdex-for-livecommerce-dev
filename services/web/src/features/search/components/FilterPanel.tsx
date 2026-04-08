"use client";

import { Facets, SearchFilters } from "@/lib/api";
import { hasTagFilters } from "@/lib/types/search";
import ColorPicker from "./ColorPicker";
import { TagFilters } from "./TagFilters";

interface FilterPanelProps {
  facets: Facets | null;
  filters: SearchFilters;
  onFiltersChange: (filters: SearchFilters) => void;
}

export function FilterPanel({
  facets,
  filters,
  onFiltersChange,
}: FilterPanelProps) {
  const toggleSourceType = (type: "gdrive" | "removable_disk" | "local") => {
    const current = filters.source_types || [];
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    onFiltersChange({
      ...filters,
      source_types: updated.length > 0 ? updated : undefined,
    });
  };

  const toggleLibrary = (id: string) => {
    const current = filters.library_ids || [];
    const updated = current.includes(id)
      ? current.filter((l) => l !== id)
      : [...current, id];
    onFiltersChange({
      ...filters,
      library_ids: updated.length > 0 ? updated : undefined,
    });
  };

  const togglePerson = (id: string) => {
    const current = filters.person_cluster_ids || [];
    const updated = current.includes(id)
      ? current.filter((p) => p !== id)
      : [...current, id];
    onFiltersChange({
      ...filters,
      person_cluster_ids: updated.length > 0 ? updated : undefined,
    });
  };

  const toggleExcludePerson = (id: string) => {
    const current = filters.person_cluster_ids_not_in || [];
    const updated = current.includes(id)
      ? current.filter((p) => p !== id)
      : [...current, id];
    onFiltersChange({
      ...filters,
      person_cluster_ids_not_in: updated.length > 0 ? updated : undefined,
    });
  };

  const clearFilters = () => {
    onFiltersChange({});
  };

  const hasFilters =
    (filters.source_types?.length ?? 0) > 0 ||
    (filters.library_ids?.length ?? 0) > 0 ||
    (filters.person_cluster_ids?.length ?? 0) > 0 ||
    (filters.person_cluster_ids_not_in?.length ?? 0) > 0 ||
    filters.color_family != null ||
    hasTagFilters(filters);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-gray-900">Filters</h3>
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="text-xs text-primary-600 hover:text-primary-700"
          >
            Clear all
          </button>
        )}
      </div>

      <div className="space-y-3">
        <ColorPicker
          value={filters.color_family}
          onChange={(family) =>
            onFiltersChange({ ...filters, color_family: family })
          }
        />

        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">Source Type</h4>
          <div className="space-y-1">
            {(facets?.source_types || []).map((item) => (
              <label
                key={item.value}
                className="flex items-center gap-2 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={filters.source_types?.includes(
                    item.value as "gdrive" | "removable_disk" | "local"
                  )}
                  onChange={() =>
                    toggleSourceType(item.value as "gdrive" | "removable_disk" | "local")
                  }
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-gray-600">
                  {item.value === "gdrive" ? "Google Drive" : item.value === "removable_disk" ? "Removable Disk" : "Local"}
                </span>
                <span className="text-xs text-gray-400">({item.count})</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">Libraries</h4>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {(facets?.libraries || []).map((item) => (
              <label
                key={item.value}
                className="flex items-center gap-2 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={filters.library_ids?.includes(item.value)}
                  onChange={() => toggleLibrary(item.value)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-gray-600 truncate">
                  {item.label || item.value.slice(0, 8)}
                </span>
                <span className="text-xs text-gray-400">({item.count})</span>
              </label>
            ))}
          </div>
        </div>

        {(facets?.people_cluster_ids || []).length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-2">People</h4>
            <div className="space-y-2">
              <div>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Include</span>
                <div className="space-y-1 mt-1 max-h-32 overflow-y-auto">
                  {(facets?.people_cluster_ids || []).map((item) => (
                    <label
                      key={`inc-${item.value}`}
                      className="flex items-center gap-2 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={filters.person_cluster_ids?.includes(item.value)}
                        onChange={() => togglePerson(item.value)}
                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-sm text-gray-600 truncate">
                        {item.label || `Person ${item.value.slice(-4)}`}
                      </span>
                      <span className="text-xs text-gray-400">({item.count})</span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Exclude</span>
                <div className="space-y-1 mt-1 max-h-32 overflow-y-auto">
                  {(facets?.people_cluster_ids || []).map((item) => (
                    <label
                      key={`exc-${item.value}`}
                      className="flex items-center gap-2 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={filters.person_cluster_ids_not_in?.includes(item.value)}
                        onChange={() => toggleExcludePerson(item.value)}
                        className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                      />
                      <span className="text-sm text-gray-600 truncate">
                        {item.label || `Person ${item.value.slice(-4)}`}
                      </span>
                      <span className="text-xs text-gray-400">({item.count})</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="pt-2 border-t border-gray-200">
          <TagFilters filters={filters} onFiltersChange={onFiltersChange} />
        </div>
      </div>
    </div>
  );
}
