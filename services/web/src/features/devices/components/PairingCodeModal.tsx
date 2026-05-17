"use client";

import { useEffect, useState } from "react";

interface PairingCodeModalProps {
  isOpen: boolean;
  onClose: () => void;
  code: string;
  expiresAt: string;
}

export function PairingCodeModal({
  isOpen,
  onClose,
  code,
  expiresAt,
}: PairingCodeModalProps) {
  const [copied, setCopied] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);

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

  if (!isOpen) {
    return null;
  }

  const isExpired = secondsRemaining <= 0;
  const minutes = Math.floor(secondsRemaining / 60);
  const seconds = secondsRemaining % 60;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may fail in non-secure contexts
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close pairing code dialog"
      />
      <div className="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">
          Device Pairing Code
        </h3>
        <p className="text-sm text-gray-500 mb-6">
          Enter this code in the Agent setup screen to pair a new device.
        </p>

        <div className="flex justify-center mb-4">
          <span
            className={
              "text-4xl font-mono tracking-[0.5em] pl-[0.5em] py-3 px-4 rounded-lg " +
              (isExpired
                ? "bg-gray-100 text-gray-400 line-through"
                : "bg-primary-50 text-primary-700")
            }
          >
            {code}
          </span>
        </div>

        <div className="text-center mb-6">
          {isExpired ? (
            <span className="text-sm font-medium text-red-600">
              Code expired
            </span>
          ) : (
            <span className="text-sm text-gray-500">
              Expires in{" "}
              <span className="font-medium text-gray-700">
                {minutes}:{seconds.toString().padStart(2, "0")}
              </span>
            </span>
          )}
        </div>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
            onClick={onClose}
          >
            Close
          </button>
          <button
            type="button"
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleCopy}
            disabled={isExpired}
          >
            {copied ? "Copied!" : "Copy Code"}
          </button>
        </div>
      </div>
    </div>
  );
}
