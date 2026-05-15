interface Props {
  className?: string;
}

export function TooltipArrow({ className }: Props) {
  return (
    <svg
      className={className}
      width="10"
      height="8"
      viewBox="0 0 10 8"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d="M5 0L10 8H0L5 0Z" fill="currentColor" />
    </svg>
  );
}
