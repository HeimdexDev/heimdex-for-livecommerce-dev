"use client";

import { useSearch } from "../hooks/useSearch";
import { SearchBar } from "./SearchBar";
import { AlphaSlider } from "./AlphaSlider";
import { FilterPanel } from "./FilterPanel";
import { SearchResults } from "./SearchResults";

export function SearchContainer() {
  const {
    alpha,
    filters,
    response,
    isLoading,
    error,
    showDebug,
    orgSlug,
    isAuthenticated,
    authLoading,
    user,
    isAuth0Enabled,
    setAlpha,
    setShowDebug,
    handleSearch,
    handleFiltersChange,
    login,
    logout,
  } = useSearch();

  const renderError = () => {
    if (!error) return null;

    if (error.type === "unauthorized") {
      return (
        <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="font-medium text-amber-800">Session Expired</p>
          <p className="text-sm text-amber-700 mt-1">{error.message}</p>
          <button
            onClick={login}
            className="mt-3 px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 transition-colors"
          >
            Login Again
          </button>
        </div>
      );
    }

    if (error.type === "forbidden") {
      return (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="font-medium text-red-800">Access Denied</p>
          <p className="text-sm text-red-700 mt-1">{error.message}</p>
          <p className="text-sm text-red-600 mt-2">
            You may be logged into a different organization. Try logging out and back in.
          </p>
          <button
            onClick={logout}
            className="mt-3 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
          >
            Logout
          </button>
        </div>
      );
    }

    if (error.type === "tenancy") {
      return (
        <div className="mb-6 p-4 bg-orange-50 border border-orange-200 rounded-lg">
          <p className="font-medium text-orange-800">Invalid Organization URL</p>
          <p className="text-sm text-orange-700 mt-1">{error.message}</p>
          <p className="text-sm text-orange-600 mt-2">
            Make sure you&apos;re accessing the app via <code className="bg-orange-100 px-1 rounded">{'{{org}}.app.heimdex.local'}</code>
          </p>
        </div>
      );
    }

    return (
      <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
        <p className="font-medium">Search Error</p>
        <p className="text-sm">{error.message}</p>
      </div>
    );
  };

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
                <svg
                  className="w-6 h-6 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Heimdex</h1>
                <p className="text-xs text-gray-500">Video Search Platform</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500">
                Org: <span className="font-medium text-gray-700">{orgSlug || "..."}</span>
              </span>
              
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={showDebug}
                  onChange={(e) => setShowDebug(e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                Debug Mode
              </label>

              {authLoading ? (
                <span className="text-sm text-gray-400">Loading...</span>
              ) : isAuthenticated ? (
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-600">
                    {user?.email || "User"}
                  </span>
                  <button
                    onClick={logout}
                    className="px-3 py-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                  >
                    Logout
                  </button>
                </div>
              ) : (
                <button
                  onClick={login}
                  className="px-4 py-1.5 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-lg transition-colors"
                >
                  {isAuth0Enabled ? "Login" : "Dev Login"}
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="mb-6 space-y-4">
          <SearchBar onSearch={handleSearch} isLoading={isLoading} />
          
          <div className="card p-4">
            <AlphaSlider value={alpha} onChange={setAlpha} />
          </div>
        </div>

        {renderError()}

        <div className="flex gap-6">
          <aside className="w-64 flex-shrink-0">
            <div className="card p-4 sticky top-4">
              <FilterPanel
                facets={response?.facets ?? null}
                filters={filters}
                onFiltersChange={handleFiltersChange}
              />
            </div>
          </aside>

          <div className="flex-1 min-w-0">
            {response ? (
              <SearchResults
                results={response.results}
                totalCandidates={response.total_candidates}
                showDebug={showDebug}
              />
            ) : (
              <div className="text-center py-16 text-gray-500">
                <svg
                  className="w-16 h-16 mx-auto mb-4 text-gray-300"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
                <p className="text-lg font-medium">Search your video library</p>
                <p className="text-sm mt-1">
                  Enter a search query above to find scenes in your videos.
                  <br />
                  Supports both English and Korean.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-gray-200 mt-12 py-6">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-gray-500">
          <p>Heimdex v0.1.0 - Development Build</p>
          <p className="mt-1">
            Video playback requires the Heimdex agent running on your machine.
          </p>
        </div>
      </footer>
    </div>
  );
}
