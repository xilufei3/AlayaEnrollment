import { AnimatePresence, motion } from "framer-motion";
import { SquarePen } from "lucide-react";

import { SustechMark } from "../icons/sustech-mark";
import { TooltipIconButton } from "./tooltip-icon-button";

type ThreadHeaderProps = {
  variant: "landing" | "chat";
  onResetThread?: () => void;
  className?: string;
};

const HEADER_TRANSITION = {
  duration: 0.2,
  ease: "easeInOut",
} as const;

export function ThreadHeader({
  variant,
  onResetThread,
  className,
}: ThreadHeaderProps) {
  return (
    <div className={className}>
      <AnimatePresence initial={false} mode="wait">
        {variant === "landing" ? (
          <motion.section
            key="landing-header"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={HEADER_TRANSITION}
            className="overflow-hidden"
          >
            <div className="mx-auto w-full max-w-[50.4rem]">
              <div className="surface-glass relative overflow-hidden rounded-[1.8rem] border border-white/75 px-[1.125rem] py-[0.95rem] shadow-[0_22px_50px_rgba(24,72,71,0.1)] sm:px-[1.35rem] sm:py-4">
                <div className="pointer-events-none absolute -right-12 top-0 h-32 w-32 rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--primary)_16%,transparent),transparent_68%)]" />
                <div className="pointer-events-none absolute bottom-0 left-8 h-[5.5rem] w-[5.5rem] rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--accent-gold)_12%,transparent),transparent_72%)]" />

                <div className="relative mx-auto w-full max-w-[34rem] text-center">
                  <div className="space-y-[0.6rem]">
                    <div className="inline-flex flex-row items-center justify-center gap-1.5">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center">
                        <SustechMark className="h-[3.75rem] w-[3.75rem]" />
                      </div>
                      <div className="inline-flex items-center rounded-full border border-primary/12 bg-primary/8 px-3 py-1 text-[10px] font-semibold tracking-[0.18em] text-primary">
                        SUSTech Admissions
                      </div>
                    </div>
                    <h2 className="text-center font-serif text-[1.55rem] font-semibold leading-tight text-foreground sm:text-[1.8rem]">
                      你好，欢迎咨询南科大招生。
                    </h2>
                  </div>
                </div>
              </div>
            </div>
          </motion.section>
        ) : (
          <motion.div
            key="chat-header"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={HEADER_TRANSITION}
            className="overflow-hidden"
          >
            <div className="surface-glass mx-auto grid h-[51px] w-full max-w-[50.4rem] grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-[1.1rem] border border-white/72 px-3 py-2 shadow-[0_14px_34px_rgba(24,72,71,0.1)] sm:px-4">
              <div aria-hidden="true" />

              <button
                type="button"
                className="flex min-w-0 cursor-pointer items-center justify-center gap-2.5 text-left opacity-80 transition-opacity duration-150 ease-in-out hover:opacity-100"
                onClick={onResetThread}
              >
                <SustechMark className="h-8 w-8 sm:h-9 sm:w-9" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium tracking-[0.08em] text-primary/90">
                    SUSTech Admissions
                  </p>
                </div>
              </button>

              <div className="justify-self-end">
                <TooltipIconButton
                  size="lg"
                  className="size-9 cursor-pointer rounded-full p-1.5 transition-colors duration-150 ease-in-out hover:bg-black/5"
                  tooltip="开始新对话"
                  variant="ghost"
                  onClick={onResetThread}
                >
                  <SquarePen className="size-4.5" />
                </TooltipIconButton>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
