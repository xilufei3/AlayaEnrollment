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
            <div className="mx-auto w-full max-w-4xl">
              <div className="surface-glass relative overflow-hidden rounded-[2rem] border border-white/75 px-5 py-4 shadow-[0_24px_56px_rgba(24,72,71,0.1)] sm:px-6 sm:py-[18px]">
                <div className="pointer-events-none absolute -right-12 top-0 h-36 w-36 rounded-full bg-[radial-gradient(circle,rgba(29,158,117,0.16),transparent_68%)]" />
                <div className="pointer-events-none absolute bottom-0 left-10 h-24 w-24 rounded-full bg-[radial-gradient(circle,rgba(211,154,44,0.12),transparent_72%)]" />

                <div className="relative mx-auto w-full max-w-xl text-center">
                  <div className="space-y-2.5">
                    <div className="inline-flex flex-row items-center justify-center gap-1.5">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center">
                        <SustechMark className="h-16 w-16" />
                      </div>
                      <div className="inline-flex items-center rounded-full border border-[#1D9E75]/12 bg-[#1D9E75]/8 px-3 py-1 text-[11px] font-semibold tracking-[0.18em] text-[#1D9E75]">
                        SUSTech Admissions
                      </div>
                    </div>
                    <h2 className="text-center font-serif text-[1.7rem] font-semibold leading-tight text-foreground sm:text-[2rem]">
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
            <div className="surface-glass mx-auto grid h-[52px] w-full max-w-4xl grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-[1.15rem] border border-white/72 px-3 py-2 shadow-[0_14px_34px_rgba(24,72,71,0.1)] sm:px-4">
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
                  tooltip="新建咨询"
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
