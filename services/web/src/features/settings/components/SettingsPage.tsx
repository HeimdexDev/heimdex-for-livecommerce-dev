"use client";

import Link from "next/link";
import { useAuth, getOrgSlug } from "@/lib/auth";

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
    </svg>
  );
}

function DeviceIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z" />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function OrgIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
    </svg>
  );
}

interface SettingsLinkCardProps {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}

function SettingsLinkCard({ href, icon, title, description }: SettingsLinkCardProps) {
  return (
    <Link
      href={href}
      className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-5 transition-all hover:border-indigo-200 hover:bg-indigo-50/30 hover:shadow-sm"
    >
      <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        <p className="mt-0.5 text-sm text-gray-500">{description}</p>
      </div>
      <ChevronRightIcon />
    </Link>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const orgSlug = getOrgSlug();

  const displayName = user?.name || user?.email || "-";
  const displayEmail = user?.email || "-";

  return (
    <div className="mx-auto max-w-3xl pt-4">
      {/* Breadcrumb */}
      <div className="mb-6 flex items-center gap-3 text-sm text-gray-500">
        <Link href="/" className="rounded-full p-1 hover:bg-gray-200">
          <BackArrowIcon />
        </Link>
        <Link href="/" className="hover:text-gray-700">전체 아카이브 검색</Link>
        <span>{">"}</span>
        <span className="text-gray-700">설정</span>
      </div>

      {/* Page title */}
      <h1 className="text-2xl font-bold text-gray-900">설정</h1>

      {/* Account info */}
      <section className="mt-8">
        <div className="flex items-center gap-2 text-gray-700">
          <UserIcon />
          <h2 className="text-lg font-bold text-gray-900">계정 정보</h2>
        </div>
        <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
          <dl className="space-y-4">
            <div className="flex items-baseline gap-4">
              <dt className="w-[120px] flex-shrink-0 text-sm text-gray-500">이름</dt>
              <dd className="text-sm font-medium text-gray-900">{displayName}</dd>
            </div>
            <div className="flex items-baseline gap-4">
              <dt className="w-[120px] flex-shrink-0 text-sm text-gray-500">이메일</dt>
              <dd className="text-sm font-medium text-gray-900">{displayEmail}</dd>
            </div>
          </dl>
        </div>
      </section>

      {/* Organization info */}
      <section className="mt-8">
        <div className="flex items-center gap-2 text-gray-700">
          <OrgIcon />
          <h2 className="text-lg font-bold text-gray-900">조직 정보</h2>
        </div>
        <div className="mt-4 rounded-xl border border-gray-200 bg-white p-6">
          <dl className="space-y-4">
            <div className="flex items-baseline gap-4">
              <dt className="w-[120px] flex-shrink-0 text-sm text-gray-500">조직 이름</dt>
              <dd className="text-sm font-medium text-gray-900">{orgSlug || "-"}</dd>
            </div>
          </dl>
        </div>
      </section>

      {/* Management menu */}
      <section className="mt-8">
        <h2 className="text-lg font-bold text-gray-900">관리 메뉴</h2>
        <div className="mt-4 space-y-3">
          <SettingsLinkCard
            href="/settings/people"
            icon={<PersonIcon />}
            title="인물 라벨 관리"
            description="영상에서 인식된 인물의 라벨을 관리합니다."
          />
          <SettingsLinkCard
            href="/settings/devices"
            icon={<DeviceIcon />}
            title="디바이스 관리"
            description="연결된 에이전트 디바이스를 관리합니다."
          />
        </div>
      </section>
    </div>
  );
}
