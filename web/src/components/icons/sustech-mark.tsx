import { cn } from "@/lib/utils";

export function SustechMark({
  className,
  decorative = true,
}: {
  className?: string;
  decorative?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative inline-flex items-center justify-center overflow-hidden rounded-[1.35rem] border border-white/70 bg-white/90 text-[#184847] shadow-[0_14px_40px_rgba(24,72,71,0.18)]",
        className,
      )}
      aria-hidden={decorative}
    >
      <img
        src="/branding/sustech-logo.png"
        alt={decorative ? "" : "南方科技大学校徽"}
        className="h-full w-full object-contain p-[10%]"
      />
    </div>
  );
}
