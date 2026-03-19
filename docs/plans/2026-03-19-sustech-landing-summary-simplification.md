# SUSTech Landing Summary Simplification Design

## Goal

Reduce the empty landing state to a lightweight row with a logo and one-line guidance, while keeping the quick prompt cards and composer unchanged.

## Scope

- Remove the large title, long description, badges, and consultation-direction panel from the landing hero.
- Keep a compact `logo + hint` row above the quick prompt cards.
- Do not change chat behavior, prompt cards, or the in-chat header.

## Acceptance

- The landing page no longer shows the large admissions introduction block.
- A single lightweight hint remains visible above the quick prompt cards.
- Quick prompt cards still render and work as before.
