"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function LoginForm() {
  const router = useRouter();
  const { loginWithCredentials, isLoading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [emailFocused, setEmailFocused] = useState(false);
  const [passwordFocused, setPasswordFocused] = useState(false);

  const isFormValid = email.trim() !== "" && password.trim() !== "";
  const isDisabled = !isFormValid || submitting || isLoading;
  const hasError = error !== null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (isDisabled) return;

    if (!EMAIL_REGEX.test(email)) {
      setError("이메일 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요.");
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      await loginWithCredentials(email, password);
      router.replace("/");
    } catch {
      setError("이메일 또는 비밀번호가 올바르지 않습니다. 다시 확인해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  const clearError = () => {
    if (error) setError(null);
  };

  const emailBorderClass = hasError
    ? "border-2 border-red-h-500"
    : emailFocused
      ? "border-2 border-softblue-600"
      : "border border-neutral-h-300";

  const passwordBorderClass = hasError
    ? "border-2 border-red-h-500"
    : passwordFocused
      ? "border-2 border-softblue-600"
      : "border border-neutral-h-300";

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-8 w-[390px]">
      <p
        className="text-[18px] leading-[1.4] font-medium text-neutral-h-500"
        style={{ letterSpacing: "-0.45px" }}
      >
        전달받은 이메일/비밀번호로 로그인해 주세요.
      </p>

      <div className="flex flex-col gap-12">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-6">
              {/* Email field */}
              <div className="flex flex-col gap-2 w-[390px]">
                <label
                  htmlFor="login-email"
                  className="text-[16px] leading-[1.4] font-medium text-black"
                  style={{ letterSpacing: "-0.4px" }}
                >
                  이메일
                </label>
                <div
                  className={cn(
                    "bg-white rounded-lg shadow-input overflow-clip px-5 py-3 w-full transition-colors",
                    emailBorderClass
                  )}
                >
                  <input
                    id="login-email"
                    type="email"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      clearError();
                    }}
                    onFocus={() => setEmailFocused(true)}
                    onBlur={() => setEmailFocused(false)}
                    placeholder="이메일 입력"
                    className="w-full bg-transparent outline-none text-[16px] leading-[1.4] font-medium text-black placeholder:text-neutral-h-500"
                    style={{ letterSpacing: "-0.4px" }}
                    autoComplete="email"
                    disabled={submitting}
                  />
                </div>
              </div>

              {/* Password field */}
              <div className="flex flex-col gap-2 w-[390px]">
                <label
                  htmlFor="login-password"
                  className="text-[16px] leading-[1.4] font-medium text-black"
                  style={{ letterSpacing: "-0.4px" }}
                >
                  비밀번호
                </label>
                <div
                  className={cn(
                    "bg-white rounded-lg shadow-input overflow-clip px-5 py-3 w-full flex items-center gap-2.5 transition-colors",
                    passwordBorderClass
                  )}
                >
                  <input
                    id="login-password"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      clearError();
                    }}
                    onFocus={() => setPasswordFocused(true)}
                    onBlur={() => setPasswordFocused(false)}
                    placeholder="비밀번호 입력"
                    className="flex-1 min-w-0 bg-transparent outline-none text-[16px] leading-[1.4] font-medium text-black placeholder:text-neutral-h-500"
                    style={{ letterSpacing: "-0.4px" }}
                    autoComplete="current-password"
                    disabled={submitting}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="shrink-0 size-5 text-neutral-h-500 hover:text-neutral-h-700 transition-colors"
                    tabIndex={-1}
                    aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
                  >
                    {showPassword ? <EyeOnIcon /> : <EyeOffIcon />}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {hasError && (
            <p
              className="text-[16px] leading-[1.4] font-medium text-red-h-500"
              style={{ letterSpacing: "-0.4px" }}
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isDisabled}
            className={cn(
              "w-[390px] rounded-lg shadow-input px-5 py-3 text-[16px] leading-[1.4] font-semibold text-white text-center transition-colors",
              isDisabled
                ? "bg-neutral-h-300 cursor-not-allowed"
                : "bg-softblue-600 hover:opacity-90"
            )}
            style={{ letterSpacing: "-0.4px" }}
          >
            {submitting ? "로그인 중..." : "로그인"}
          </button>
        </div>

        <div className="flex items-center gap-1.5 w-[390px]">
          <p
            className="flex-1 text-right text-[14px] leading-[1.4] font-medium text-neutral-h-500"
            style={{ letterSpacing: "-0.35px" }}
          >
            Contact us
          </p>
          <a
            href="mailto:heimdex@heimdex.co"
            className="text-[14px] leading-[1.4] font-medium text-neutral-h-500 underline decoration-solid"
            style={{ letterSpacing: "-0.35px" }}
          >
            heimdex@heimdex.co
          </a>
        </div>
      </div>
    </form>
  );
}

function EyeOnIcon() {
  // Figma: 24/ outlined / action / eye / eye on (20×20)
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2 12c2.5-4.5 6-7 10-7s7.5 2.5 10 7c-2.5 4.5-6 7-10 7s-7.5-2.5-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  // Figma: 24/ outlined / action / eye / eye off (20×20)
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2 12c2.5-4.5 6-7 10-7 1.4 0 2.7.3 3.9.8M22 12c-2.5 4.5-6 7-10 7-1.4 0-2.7-.3-3.9-.8" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <line x1="3" y1="3" x2="21" y2="21" />
    </svg>
  );
}
