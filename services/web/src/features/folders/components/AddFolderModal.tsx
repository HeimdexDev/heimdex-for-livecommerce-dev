"use client";

import { useEffect, useState, useCallback } from "react";

interface AddFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  deepLinkUrl: string;
  expiresAt: string;
}

export function AddFolderModal({
  isOpen,
  onClose,
  deepLinkUrl,
  expiresAt,
}: AddFolderModalProps) {
  const [copied, setCopied] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);
  const [autoOpened, setAutoOpened] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    const calcRemaining = () => {
      const diff = new Date(expiresAt).getTime() - Date.now();
      return Math.max(0, Math.floor(diff / 1000));
    };
    setSecondsRemaining(calcRemaining());

    const interval = setInterval(() => {
      const remaining = calcRemaining();
      setSecondsRemaining(remaining);
      if (remaining <= 0) {
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [isOpen, expiresAt]);

  useEffect(() => {
    if (!isOpen || autoOpened) return;
    setAutoOpened(true);
    const timer = setTimeout(() => {
      window.location.href = deepLinkUrl;
    }, 500);
    return () => clearTimeout(timer);
  }, [isOpen, deepLinkUrl, autoOpened]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, onClose]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(deepLinkUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may fail in non-secure contexts
    }
  }, [deepLinkUrl]);

  const handleOpenAgent = useCallback(() => {
    window.location.href = deepLinkUrl;
  }, [deepLinkUrl]);

  if (!isOpen) {
    return null;
  }

  const isExpired = secondsRemaining <= 0;
  const minutes = Math.floor(secondsRemaining / 60);
  const seconds = secondsRemaining % 60;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close add folder dialog"
      />
      <div className="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Add Folder</h3>
        <p className="text-sm text-gray-500 mb-6">
          {isExpired
            ? "This link has expired. Please close and try again."
            : "Opening Heimdex Agent on your device. Select a folder to add and it will start scanning automatically."}
        </p>

        <div className="text-center mb-4">
          {isExpired ? (
            <span className="text-sm font-medium text-red-600">Link expired</span>
          ) : (
            <span className="text-sm text-gray-500">
              Expires in{" "}
              <span className="font-medium text-gray-700">
                {minutes}:{seconds.toString().padStart(2, "0")}
              </span>
            </span>
          )}
        </div>

        <div className="space-y-3">
          <button
            type="button"
            className="w-full btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleOpenAgent}
            disabled={isExpired}
          >
            Open Heimdex Agent
          </button>

          <p className="text-xs text-gray-400 text-center">
            If the agent didn&apos;t open automatically, click the button above or
            copy the link below.
          </p>

          <div className="flex gap-2">
            <input
              type="text"
              readOnly
              value={deepLinkUrl}
              className="flex-1 text-xs font-mono text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 truncate"
            />
            <button
              type="button"
              className="px-3 py-2 text-xs font-medium text-gray-700 border border-gray-200 rounded-lg hover:bg-gray-50 whitespace-nowrap"
              onClick={handleCopy}
              disabled={isExpired}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>

        <div className="flex justify-end mt-6">
          <button
            type="button"
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
