# Verina design system (v0)

Status: v0 with landing-page extension. Owner: designer. Code: `apps/web`.
Token source of truth: `apps/web/app/globals.css`. If this document and the CSS disagree, the CSS wins
and this document is the bug.

## 1. Principles

1. **The page should read like a filed document.** Verina sits next to contracts, statutes and
   judgments, so it borrows the calm of a well-set legal page: cool paper ground, graphite text,
   hairline rules, one accent. It does not look like a SaaS dashboard.
2. **Every status is stated, not implied.** A ledger status is always readable three ways: a text
   label, an icon shape and a colour. Remove any one and the status still reads.
3. **Claim beside proof.** An assertion always sits next to its source quote (or an explicit "no
   source found" note). The source is set in a reading serif, so it is visibly different from
   Verina's own words.
4. **The accent belongs to the human act.** Indelible-ink blue is reserved for things a lawyer
   does: attest, take the primary action, focus. It is never decoration.
5. **Nothing disappears, it cancels.** Superseded or withdrawn text is struck through and kept,
   never silently removed. The audit trail is visible in the interface too. (Rule for the ledger
   build in Sprint 1; not yet exercised by the v0 shell.)
6. **Calm under pressure.** No decorative motion on work surfaces. Motion only explains a change of
   state, and always has a reduced-motion fallback.

The visual direction ("registry filing stamp") is recorded in the Impeccable surface brief
`apps/web/.impeccable/surfaces/app-page-tsx.md`; product context is in `apps/web/PRODUCT.md`.

## 2. Typography

| Role | Family | Why |
| --- | --- | --- |
| UI, headings, labels, data | **Atkinson Hyperlegible Next** (variable, 200 to 800) | Drawn by the Braille Institute so confusable glyphs differ: `I l 1`, `O 0`, `rn m`. Legal references are full of them (`cl 11.1(l)`, `s 10(1)`, `[2019] SGCA 1`), and a misread clause number is a real error. Works as one workhorse family for the whole product UI. |
| Quoted legal text (clauses, statute sections, judgments) | **Literata** (variable, optical size 7 to 72) | A text serif designed for long on-screen reading. Setting sources in a serif marks them as quoted material, separate from Verina's own sentences. |

Both are loaded with `next/font/google` in `app/layout.tsx` (self-hosted at build time, no runtime
request to Google, `display: swap`). Numerals are tabular in the UI and old-style proportional in
quoted text.

**Scale** (fixed rem, ratio about 1.2; product UI does not use fluid type):

| Token | Size | Use |
| --- | --- | --- |
| `--text-xs` | 12px | Stamp dates, entry ids, footnotes |
| `--text-sm` | 14px | Labels, meta, notes, buttons |
| `--text-base` | 16px | UI body, assertions |
| `--text-read` | 17px | Quoted legal text (Literata, line-height 1.6) |
| `--text-lg` | 20px | Section headings, wordmark |
| `--text-xl` | 24px | Page statement |
| `--text-2xl` | 32px | Reserved for page titles |

Line heights: `--leading-tight` 1.2 (headings), `--leading-ui` 1.45, `--leading-read` 1.6.
Weights: 400, 500, 650. Reading measure: `--measure-read` 66ch.

## 3. Space, radius, layers

- Spacing: 4px base. `--space-1` 4px, `-2` 8px, `-3` 12px, `-4` 16px, `-5` 20px, `-6` 24px, `-8` 32px,
  `-10` 40px, `-12` 48px, `-16` 64px. More space above a heading than below it.
- Radius: one system. `--radius` 4px on every container, control and stamp; `--radius-tight` 2px
  only for focus outlines on tight controls. No pills, no large rounded cards.
- Rules: `--rule-width` 1px hairlines; stamps use `--stamp-border-width` 1.5px.
- No drop shadows. Elevation is a 1px rule and a surface step (`--color-bg` to `--color-surface`).
- Z-index: `--z-header` 10 (sticky top bar). The skip link sits one above it. Nothing else layers.

## 4. Colour

Restrained strategy: cool neutrals plus one accent, plus status hues that only ever carry meaning.
Light and dark are both first-class. Theme follows `prefers-color-scheme`; `<html data-theme="light">`
or `data-theme="dark"` forces one.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--color-bg` | `#f6f7f9` | `#111419` | Page ground |
| `--color-surface` | `#fcfcfd` | `#181c23` | Raised work surface |
| `--color-surface-sunk` | `#eef0f3` | `#0c0e12` | Source quote wells, locked controls |
| `--color-ink` | `#1b1f27` | `#e5e8ed` | Body text |
| `--color-ink-muted` | `#505968` | `#a2aab6` | Secondary text |
| `--color-rule` | `#dde1e6` | `#2a303a` | Decorative hairlines (not a control boundary) |
| `--color-rule-strong` | `#7d8693` | `#6f7886` | Control and region boundaries |
| `--color-accent` | `#2c3f9e` | `#a6b4ff` | Indelible-ink blue: primary action, attestation, focus, links |
| `--color-accent-hover` | `#22327f` | `#c2cbff` | Hover on accent |
| `--color-on-accent` | `#fcfcfd` | `#111419` | Text on accent fill |
| `--color-selection` | `#d4daf6` | `#2c3670` | Text selection |

### Measured contrast (WCAG 2.x relative luminance, computed from the hex values above)

| Pair | Light | Dark | Requirement |
| --- | --- | --- | --- |
| Ink on bg / surface / sunk | 15.40 / 16.10 / 14.46 | 15.02 / 13.91 / 15.73 | 4.5 (text) |
| Muted on bg / surface / sunk | 6.60 / 6.90 / 6.19 | 7.88 / 7.29 / 8.24 | 4.5 |
| Accent on bg / surface | 8.47 / 8.86 | 9.31 / 8.62 | 4.5 (links), 3 (focus ring) |
| On-accent on accent / hover | 8.86 / 11.19 | 9.31 / 11.67 | 4.5 |
| Rule-strong on surface / sunk | 3.59 / 3.23 | 3.83 / 4.33 | 3 (non-text, 1.4.11) |
| Ink on selection | 11.92 | 9.15 | 4.5 |

All pairs meet WCAG 2.2 AA; most meet AAA (7:1).

## 5. Ledger statuses and risk tiers

Status is never colour alone. Each status has a label, a distinct icon shape (Phosphor icons,
bold weight, `aria-hidden`), a colour, and a spoken prefix for screen readers.

| Status | Meaning | Icon (shape cue) | Extra cue | Export | Light fg / tint | Dark fg / tint |
| --- | --- | --- | --- | --- | --- | --- |
| **Verified** | The source says what the assertion says | `SealCheck`: closed seal with a tick | solid border | Clears | `#1b6638` / `#e8f3ec` | `#7dd19a` / `#14271c` |
| **Unsupported** | No source was found | `CircleDashed`: broken outline | dashed border | Blocks | `#7f5200` / `#faf0d9` | `#e7b45a` / `#2a2213` |
| **Contradicted** | The source says something different | `XCircle`: cross | solid border | Blocks | `#a8242a` / `#faeaea` | `#ff9592` / `#311a1b` |
| **Attested** | A named lawyer takes responsibility, with a reason | `PenNib`: pen | lawyer's initials and date in the imprint | Clears | accent / accent tint | accent / accent tint |

Measured contrast of status text (fg) on its tint / on surface / on bg:

| Status | Light | Dark |
| --- | --- | --- |
| Verified | 6.15 / 6.82 / 6.52 | 8.57 / 9.32 / 10.07 |
| Unsupported | 5.96 / 6.59 / 6.30 | 8.28 / 9.01 / 9.73 |
| Contradicted | 6.11 / 6.94 / 6.64 | 7.70 / 8.11 / 8.76 |
| Attested | 7.78 / 8.86 / 8.47 | 7.92 / 8.62 / 9.31 |

The same fg colour draws the stamp border, so borders exceed the 3:1 non-text minimum too.

**Risk tiers** (matter level) reuse the three status hues; the shape and the word carry the meaning.

| Tier | Meaning | Icon (filled) | Tokens |
| --- | --- | --- | --- |
| **Green** | Standard terms, fast sign-off | `Circle` | `--tier-green`, `--tier-green-tint` |
| **Yellow** | Deviations from playbook, counsel review | `Triangle` (caution) | `--tier-yellow`, `--tier-yellow-tint` |
| **Red** | Material risk, full legal review | `Octagon` (stop) | `--tier-red`, `--tier-red-tint` |

Tier contrast equals the matching status row above (5.96 to 8.57).

### Components (v0)

- `StatusStamp` (`app/components/ledger/StatusStamp.tsx`): the "registry stamp". Bordered,
  upright, uppercase label with icon and an imprint line that always names the actor and date:
  "Verina, 13 Oct 2026" for a machine check, "N. Lim, 13 Oct 2026" for a lawyer's attestation.
  Screen readers hear "Ledger status: Verified, by Verina, 13 Oct 2026".
- Notes under an entry name their author ("Verina: ...", "Reason (N. Lim): ...").
- Ordering: entries that block export (Unsupported, Contradicted) are listed first; the export
  gate names them as links.
- `RiskTierBadge`: tier shape, label, tint. Spoken as "Risk tier: Yellow".
- `LedgerEntry`: an `<article>` named by its assertion (`aria-labelledby`). Fixed-width status
  column (11rem), so a status change restyles only that cell and the row never reflows. Source as
  `<figure>` with `<blockquote>` and `<figcaption>` citation; a missing source is a dashed
  "searched, nothing found" note, never an empty space.
- Locked action: "Export to client" uses `aria-disabled="true"` (still focusable), a lock icon,
  a sunk ground and a solid strong-rule border, and `aria-describedby` pointing at the reason the
  gate is closed. A disabled control that cannot say why is not allowed. (A dashed border means
  "Unsupported" and nothing else.)

## 6. Motion

Tokens (`lib/motion.ts` mirrors the CSS custom properties):

| Token | Value | Use |
| --- | --- | --- |
| `duration.fast` / `--duration-fast` | 120ms | Hover, press, focus feedback |
| `duration.base` / `--duration-base` | 200ms | A status change, a row expanding |
| `duration.slow` / `--duration-slow` | 300ms | **Ceiling for anything on a work surface** |
| `stagger` | 40ms | Sequenced reveals |
| `ease.out` / `--ease-out` | `power3.out` / `cubic-bezier(0.22, 1, 0.36, 1)` | Arriving, settling |
| `ease.inOut` / `--ease-in-out` | `power2.inOut` / `cubic-bezier(0.65, 0, 0.35, 1)` | Moving between positions |

Rules:

1. Motion explains a change of state (arrival, a status applied, feedback). Never ornament; no
   loops, parallax or scroll-jacking on work surfaces (grid, ledger, redline).
2. Animate `transform` and `opacity` only. No `transition: all`, no `window` scroll listeners.
3. Content is visible in the server HTML. GSAP animates *from* a hidden state, so no-JS, reduced
   motion and background tabs all get the static page.
4. Every animation is gated by `gsap.matchMedia().add("(prefers-reduced-motion: no-preference)")`
   or the `useReducedMotion()` hook. Under `reduce`, Lenis is not created and nothing animates;
   CSS transitions also collapse to 0.01ms globally.
5. Use `useGSAP` (from `@gsap/react`) for all GSAP work in React so it is reverted on unmount.

The one authored moment in v0: the workspace arrives in reading order (8px rise, 300ms, 40ms
stagger), then each ledger stamp lands last (scale 1.08 to 1, 200ms), like a stamp applied to a
filed document (`app/components/Reveal.tsx`).

## 7. Accessibility rules (WCAG 2.2 AA, product requirement)

- Contrast: every pair above is measured; new colours must be added to the tables with ratios.
- Non-colour cues: statuses and tiers always carry a label and a shape (1.4.1 Use of Color).
- Keyboard: skip link to `#main`; visible 2px accent focus ring with 2px offset on everything
  focusable; nothing focusable is hidden; locked controls stay focusable and explain themselves.
- Targets: buttons are at least 40px tall and nav links 44px (2.5.8 minimum is 24px).
- Structure: one `h1` (product), `h2` per region, `h3` per item; landmarks `header`, `nav`
  (labelled "Workspace"), `main`, `footer`; ledger entries are `article`s named by their assertion.
- Screen readers: icons are `aria-hidden`; statuses get a visually hidden prefix
  ("Ledger status:", "Risk tier:") so the spoken output carries the category, not just a word.
- Motion: see section 6. Reduced motion removes smooth scrolling as well as reveals.
- Anchors clear the sticky header (`scroll-margin-top`, and the Lenis anchor offset).
- Language: `lang="en-SG"`.

## 8. How Lenis and GSAP are wired

```
app/layout.tsx
  <SmoothScroll>                       app/providers/SmoothScroll.tsx ("use client")
    {children}
lib/motion.ts                          tokens, useReducedMotion(), registers ScrollTrigger + useGSAP once
app/components/Reveal.tsx              useGSAP + gsap.matchMedia reveal (client leaf)
```

- **One Lenis instance** at the app root (`SmoothScroll`), created in `useEffect` only when
  `useReducedMotion()` is false. It is destroyed (and recreated) if the OS setting changes, and on
  unmount.
- **GSAP drives the frame loop**: `autoRaf: false`, then
  `gsap.ticker.add((time) => lenis.raf(time * 1000))` and `gsap.ticker.lagSmoothing(0)`. Cleanup
  removes the ticker callback and restores GSAP's default lag smoothing (`500, 33`).
- **ScrollTrigger stays in sync** with `lenis.on("scroll", ScrollTrigger.update)`.
- **Anchors**: `anchors: { offset: -72 }` so in-page links land below the sticky header.
- **Recommended CSS**: `import "lenis/dist/lenis.css"` in the provider (handles `html.lenis`
  height, `data-lenis-prevent` overscroll, iframes during smooth scroll).
- **Plugins** are registered once in `lib/motion.ts` (`gsap.registerPlugin(ScrollTrigger, useGSAP)`,
  browser only). Import `gsap`, `ScrollTrigger` and `useGSAP` from `@/lib/motion`, not directly.
- **Nested scroll areas** (future: document viewer, redline pane) must carry `data-lenis-prevent`
  so they scroll natively.
- **Tests**: jsdom has no `matchMedia`; `vitest.setup.ts` stubs it to report reduced motion, so
  components render their static state in tests.

Packages: `lenis` 1.3.x, `gsap` 3.15.x, `@gsap/react` 2.1.x, `@phosphor-icons/react` 2.1.x
(icon library; imported from `@phosphor-icons/react/dist/ssr` in server components).

## 9. Landing-page extension

`/` is the product introduction; `/workbench` is the preserved synthetic read-only ledger demonstration. The landing page uses the existing palette, typography, radius and status components. A fluid Literata display heading introduces a real interactive preview instead of a simulated screenshot or invented metric. Detailed flow: `docs/design/flows/LANDING.md`. Portable design context: `apps/web/DESIGN.md`.

The preview selects supported, contradicted and missing-source examples from the existing fixtures. It labels statuses as preset, keeps the whole matter's gate closed even when the selected assertion is verified, and accepts no document input. Native buttons expose pressed state and update the assertion/source/status region with a polite announcement.

Landing arrival is the sole entrance moment. The workbench no longer uses page entrance choreography. Navigation and actions have at least 44px target height. The marketing headline is the single h1 on `/`; the demo h1 identifies the read-only workspace.

Technical and design evidence, including limitations, is recorded in `docs/design/LANDING_REVIEW.md` and the private role handoff. A passing automated accessibility scan is not full WCAG certification.

## 10. Not yet decided

- Logo and wordmark treatment (v0 uses the word "Verina" set in the UI face).
- A visible theme switch (the `data-theme` hook exists; no control yet).
- Density modes for the risk grid and redline views (Sprint 1+).
