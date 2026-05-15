"use client";

interface AgentTroubleshootingProps {
  onRetry: () => void;
}

export function AgentTroubleshooting({ onRetry }: AgentTroubleshootingProps) {
  return (
    <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg">
      <div className="flex items-start gap-3">
        <svg
          className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5"
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
        <div className="flex-1">
          <p className="font-medium text-amber-800">
            Heimdex Agent is not responding
          </p>
          <p className="text-sm text-amber-700 mt-1">
            Video playback requires the agent running at{" "}
            <code className="bg-amber-100 px-1 rounded text-xs">
              http://127.0.0.1:8787
            </code>
          </p>

          <ul className="mt-3 space-y-1.5 text-sm text-amber-700">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-amber-400 rounded-full flex-shrink-0" />
              Check that the Heimdex agent process is running
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-amber-400 rounded-full flex-shrink-0" />
              Verify no firewall is blocking port 8787
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-amber-400 rounded-full flex-shrink-0" />
              Try restarting the agent application
            </li>
          </ul>

          <button
            onClick={onRetry}
            className="mt-3 px-4 py-1.5 text-sm font-medium text-amber-700 bg-amber-100 hover:bg-amber-200 rounded-lg transition-colors"
          >
            Retry connection
          </button>
        </div>
      </div>
    </div>
  );
}
