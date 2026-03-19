# SUSTech Landing Header Removal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the top brand header from the empty landing state while keeping the in-chat header unchanged.

**Architecture:** Keep the existing landing cards and chat composer intact, and only change the shell render condition around the top header. Add a tiny tested helper for the header visibility rule so this behavior stays explicit and easy to evolve.

**Tech Stack:** Next.js 15, React 19, TypeScript, node:test

---

### Task 1: Define the header visibility rule

**Files:**
- Create: `web/src/components/thread/top-bar-visibility.ts`
- Create: `web/src/components/thread/top-bar-visibility.test.ts`

**Step 1: Write the failing test**

Add a `node:test` file that asserts:
- the top bar is hidden before a chat starts
- the top bar is shown after a chat starts

**Step 2: Run test to verify it fails**

Run: `node --test web/src/components/thread/top-bar-visibility.test.ts`
Expected: FAIL because `top-bar-visibility.ts` does not exist yet.

**Step 3: Write minimal implementation**

Export a helper:

```ts
export function shouldShowTopBar(chatStarted: boolean): boolean {
  return chatStarted;
}
```

**Step 4: Run test to verify it passes**

Run: `node --test web/src/components/thread/top-bar-visibility.test.ts`
Expected: PASS

### Task 2: Wire the thread shell to the visibility rule

**Files:**
- Modify: `web/src/components/thread/index.tsx`

**Step 1: Use the helper in the thread shell**

Render the top header only when `shouldShowTopBar(chatStarted)` is true.

**Step 2: Verify unchanged sections stay in place**

Keep:
- landing cards
- chat composer
- in-chat header

**Step 3: Run verification**

Run:
- `node --test web/src/components/thread/top-bar-visibility.test.ts`
- `npm run build`

Expected:
- tests pass
- build passes
