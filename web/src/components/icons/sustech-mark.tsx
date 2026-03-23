import { cn } from "@/lib/utils";
import { withBasePath } from "@/lib/public-path";

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
        "relative inline-flex items-center justify-center overflow-hidden",
        className,
      )}
      aria-hidden={decorative}
    >
      <img
        src={withBasePath("/branding/sustech-logo.png")}
        alt={decorative ? "" : "南方科技大学校徽"}
        className="h-full w-full object-contain"
      />
    </div>
  );
}
