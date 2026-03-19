# SUSTech Landing Summary Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the large landing introduction block with a single lightweight logo-and-hint row.

**Architecture:** Move the landing hint copy into a tiny tested helper so the simplified hero stays explicit. Update the landing hero component to render only that compact row plus the existing quick prompt cards.

**Tech Stack:** Next.js 15, React 19, TypeScript, node:test

---

### Task 1: Add tested landing hint copy

**Files:**
- Create: `web/src/components/thread/landing-hint.ts`
- Create: `web/src/components/thread/landing-hint.test.ts`

**Step 1: Write the failing test**

Assert that the landing hint exports a non-empty single-line message for the empty-chat state.

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/landing-hint.test.ts`
Expected: FAIL because `landing-hint.ts` does not exist.

**Step 3: Write minimal implementation**

Export a constant string for the compact landing hint.

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/landing-hint.test.ts`
Expected: PASS

### Task 2: Simplify the landing hero

**Files:**
- Modify: `web/src/components/thread/index.tsx`

**Step 1: Replace the detailed hero block**

Render only:
- logo
- one-line hint
- existing quick prompt cards

**Step 2: Verify the page still builds**

Run:
- `node --test web/src/components/thread/landing-hint.test.ts`
- `npm run build`

Expected:
- tests pass
- build passes
