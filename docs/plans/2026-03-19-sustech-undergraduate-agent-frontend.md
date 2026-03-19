# SUSTech Undergraduate Agent Frontend Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebrand the standalone Next.js chat UI into a South University of Science and Technology undergraduate admissions landing experience with a branded hero, curated quick prompts, and a cleaner chat workspace.

**Architecture:** Keep the existing LangGraph thread and streaming logic intact, and concentrate changes in the app shell, thread layout, history panel, and connection fallback UI. Introduce a small brand asset component plus lightweight presentation helpers so we can reshape the experience without changing backend behavior.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind CSS 4, Framer Motion, node:test

---

### Task 1: Lock brand copy and quick-start content

**Files:**
- Create: `web/src/components/thread/quick-prompts.ts`
- Test: `web/src/components/thread/quick-prompts.test.ts`

**Step 1: Write the failing test**

Add a `node:test` file that asserts:
- the page title copy references SUSTech undergraduate admissions
- the quick-prompt list contains at least 4 prompts
- every prompt includes a label and a prefilled question

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: FAIL because `quick-prompts.ts` does not exist yet.

**Step 3: Write minimal implementation**

Create `quick-prompts.ts` that exports:
- a `BRAND_COPY` object with title, subtitle, disclaimer, and history label copy
- a `QUICK_PROMPTS` array of branded admissions questions

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/components/thread/quick-prompts.ts web/src/components/thread/quick-prompts.test.ts
git commit -m "test: define branded admissions copy"
```

### Task 2: Add reusable SUSTech brand placeholder assets

**Files:**
- Create: `web/src/components/icons/sustech-mark.tsx`
- Modify: `web/src/app/layout.tsx`

**Step 1: Write the failing test**

No component test harness exists for this UI slice, so use a static contract:
- confirm the new component exports a React component named `SustechMark`
- confirm metadata in `layout.tsx` no longer references `Agent Inbox`

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: FAIL after extending the test with metadata assertions.

**Step 3: Write minimal implementation**

- Add a placeholder brand mark component sized for nav and hero usage.
- Update metadata title and description in `layout.tsx` to SUSTech admissions branding.

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/components/icons/sustech-mark.tsx web/src/app/layout.tsx web/src/components/thread/quick-prompts.test.ts
git commit -m "feat: add sustech brand placeholder"
```

### Task 3: Rebuild the thread shell into a branded landing workspace

**Files:**
- Modify: `web/src/components/thread/index.tsx`
- Modify: `web/src/app/globals.css`

**Step 1: Write the failing test**

Use the existing copy test to assert:
- the landing copy exposes the new branded title
- the quick prompts are exported for rendering

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: FAIL until the new copy is consumed.

**Step 3: Write minimal implementation**

- Replace LangGraph and GitHub branding with SUSTech admissions branding.
- Add a hero section for the empty-chat state.
- Add clickable quick-prompt cards that seed the textarea.
- Restyle the message area, input card, and page chrome using the new admissions palette.

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/components/thread/index.tsx web/src/app/globals.css
git commit -m "feat: redesign admissions chat workspace"
```

### Task 4: Refresh the thread history panel and fallback connection screen

**Files:**
- Modify: `web/src/components/thread/history/index.tsx`
- Modify: `web/src/providers/Stream.tsx`

**Step 1: Write the failing test**

Extend the copy test to assert:
- the history label copy uses admissions-oriented wording
- the connection screen copy no longer mentions LangGraph or Agent Chat

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: FAIL until the new copy is wired through both components.

**Step 3: Write minimal implementation**

- Rename thread history UI to admissions consultation history.
- Rework the empty-config screen with project-specific wording.
- Preserve all existing connection behavior and validation.

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/quick-prompts.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/components/thread/history/index.tsx web/src/providers/Stream.tsx web/src/components/thread/quick-prompts.test.ts
git commit -m "feat: align supporting UI with admissions branding"
```

### Task 5: Verify the frontend end-to-end

**Files:**
- Modify: `web/src/components/thread/quick-prompts.test.ts` (only if needed)

**Step 1: Run targeted tests**

Run: `node --test web/src/components/thread/quick-prompts.test.ts web/src/providers/thread-query-config.test.ts`
Expected: PASS

**Step 2: Run lint**

Run: `npm run lint`
Expected: PASS without new warnings introduced by this change

**Step 3: Run production build**

Run: `npm run build`
Expected: PASS and emit a Next.js production bundle

**Step 4: Manual check**

Run: `npm run dev`
Expected: the landing state shows the new hero, quick prompts, removed GitHub link, and branded header on both desktop and mobile layouts

**Step 5: Commit**

```bash
git add web
git commit -m "feat: polish sustech undergraduate admissions frontend"
```
