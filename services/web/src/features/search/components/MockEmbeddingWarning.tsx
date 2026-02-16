"use client";

export function MockEmbeddingWarning() {
  return (
    <div className="mb-6 p-4 bg-orange-50 border border-orange-200 rounded-lg">
      <div className="flex items-start gap-3">
        <svg
          className="w-5 h-5 text-orange-500 flex-shrink-0 mt-0.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
          />
        </svg>
        <div>
          <p className="font-medium text-orange-800">
            Semantic Search Disabled (Mock Embeddings)
          </p>
          <p className="text-sm text-orange-700 mt-1">
            The API is running with{" "}
            <code className="bg-orange-100 px-1 rounded text-xs">
              EMBEDDING_USE_MOCK=true
            </code>
            . Vector search results are random noise - only BM25 lexical matching
            is active. Search accuracy metrics from this session are{" "}
            <strong>invalid</strong>.
          </p>
          <p className="text-sm text-orange-600 mt-2">
            Set{" "}
            <code className="bg-orange-100 px-1 rounded text-xs">
              EMBEDDING_USE_MOCK=false
            </code>{" "}
            in docker-compose.yml for real semantic search.
          </p>
        </div>
      </div>
    </div>
  );
}
