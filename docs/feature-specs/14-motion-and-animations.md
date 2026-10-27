# 14 – Motion & Animations

## Goal
Make the site feel responsive and alive (processing feedback, success moments, smooth tab and card transitions) without adding libraries, weakening the CSP, or hurting accessibility.

## Files
- `app/static/motion.css`: all new animation, loaded by the dashboard, login, Clerk sign-in and identity-documents pages (`?v=1` is the cache-buster; bump it when the file changes).
- `app/static/motion.js`: optional dashboard extras. It only observes the DOM and never calls the app's own functions; if it fails to load or throws, the page is unchanged.
- `app/templates/clerk_login.html`: spinner while loading/verifying, check mark and short pause before the redirect.

## What the user sees
| Where | Effect |
|-------|--------|
| Tabs | Panels ease in when a tab opens |
| KPI cards | Staggered pop-in, cursor spotlight, bump + count-up when a number changes |
| Buttons | Lift on hover, press on click, click ripple |
| Drop zone | Lifts on hover, pulsing ring on drag-over, glowing **scan line** while processing |
| Steps | Pulsing ring on the active step, check on completed steps, sweeping progress bar while processing |
| Status line | Pop on update, shake on error, animated check + confetti burst on success |
| Toasts | Spring in, countdown bar, fade out (errors also shake) |
| Result | Masked image wipes in over the original |
| Login | Staggered fields and logo pop (skipped after a failed attempt, where the card shakes instead) |
| Clerk sign-in | Spinner → green check → redirect |
| Identity documents | Staggered panels and document cards |

## Rules the code follows
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` zeroes all animation/transition durations and hides decorative layers (scan line, sweep, confetti, ripple, toast timer). `motion.js` also checks the setting before animating.
- **CSP:** only `'self'` files; no inline handlers, no `eval`, no `innerHTML`.
- **Entrance animations use `backwards` fill**, so they never pin a transform and hover effects keep working.
- **Never override existing animations.** Selectors that are generic (`.wrap`, `.panel`) are scoped to the page that needs them (`body[data-page="identity"]`). An unscoped `.wrap > .panel` rule once replaced the dashboard's own `.fade-up` animation and left every panel at opacity 0 (an invisible dashboard). A regression test now guards this.
- The `.kpis` summary panel is hidden by the existing dashboard design; its animations only play if that panel is shown.

## How it was verified
- Unit tests in `tests/test_motion_assets.py` (assets served, linked from every page, reduced-motion block, all keyframes defined, selector scoping).
- A real Edge run against a sandboxed server (temp data folders): login entrance, wrong-password shake, dashboard, upload with real OCR (scan line, step states, success check, confetti, before/after wipe), Results tab, and reduced-motion emulation. There were no console or CSP errors, and the reduced-motion run reported near-zero durations.

## Edge cases
- Uses `:has()` and `color-mix()`; on a very old browser the scan line and progress sweep simply don't appear.
- Count-up only applies to values that start with a number (`12`, `340 ms`), never to text like `AADHAAR`.
- Confetti and ripples are removed from the DOM when finished.

## Acceptance criteria
- With the system "reduce motion" setting on, nothing moves.
- The dashboard is fully visible after load with and without `motion.css`.
- No console or CSP errors on any page.
