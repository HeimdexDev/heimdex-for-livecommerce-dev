import { HeimdexSymbol } from "./HeimdexSymbol";
import { HeimdexWordmark } from "./HeimdexWordmark";

interface Props {
  className?: string;
}

export function HeimdexBrand({ className }: Props) {
  return (
    <div className={className}>
      <div className="flex h-[33px] items-center gap-[9px]" aria-label="Heimdex">
        <HeimdexSymbol className="h-[33px] w-[31px] text-[#0a2240]" />
        <HeimdexWordmark className="h-[23px] w-[110px] text-black" />
      </div>
    </div>
  );
}
