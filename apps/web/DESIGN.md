---
name: Verina
description: A calm editorial workbench with claims beside their evidence
colors:
  primary: "#2c3f9e"
  primary-dark: "#a6b4ff"
  neutral-bg: "#f6f7f9"
  neutral-bg-dark: "#111419"
  surface: "#fcfcfd"
  surface-dark: "#181c23"
  ink: "#1b1f27"
  ink-dark: "#e5e8ed"
typography:
  display:
    fontFamily: "Literata, Georgia, serif"
    fontSize: "clamp(2.9rem, 4.7vw, 4.5rem)"
    fontWeight: 450
    lineHeight: 1.11
    letterSpacing: "-0.04em"
  body:
    fontFamily: "Atkinson Hyperlegible Next, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  sm: "4px"
  focus: "2px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "32px"
  xl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    height: "48px"
---

## Overview

This records the existing cool-paper/graphite/indigo system, expanded for the landing surface. The marketing page persuades through a real interactive ledger preview; the workbench supports close reading. Neither uses invented adoption metrics or testimonials. CSS is normative: `app/globals.css`, route modules and ledger components.

## Colors

One indigo accent marks actions and lawyer attestation. Status hues always carry meaning and have explicit text and shape companions. Light and dark follow system preference across the entire page; individual sections never invert. `docs/design/DESIGN_SYSTEM.md` records the full token and contrast tables.

## Typography

Atkinson Hyperlegible Next carries interface text. Literata distinguishes source quotes and supplies the landing display voice. Both are self-hosted through Next fonts. Marketing headings use a fluid scale; reading and work-surface typography stays in fixed rem units. Body measures stay narrow enough for close reading.

## Layout

The landing page pairs the proposition with a real source/claim composition, followed by audience context, an ordered review sequence, status explanations and a demo invitation. It collapses into a single reading order below 1024px. Containers use fluid side padding; the workbench retains its task-focused layout.

## Elevation & Depth

Depth comes from surface steps and hairlines. No shadows, gradients, decorative textures or simulated operating-system chrome. The preview border identifies a real interaction region.

## Shapes

Small four-pixel corners support precise document surfaces. Status stamp shapes remain stable; a dashed border specifically means unsupported evidence. No pill buttons.

## Components

`LedgerPreview` selects preset synthetic examples using native buttons and explicit pressed states. The assertion, status and source update together. `StatusStamp` adds a spoken category prefix and distinct Phosphor bold icons. The export control remains focusable so its reason can be read. Buttons and demo navigation have touch targets of at least 44px in height.

`SmoothScroll` owns the only Lenis instance, driven by the GSAP ticker with ScrollTrigger synchronization. Landing supporting actions and the prototype note use the existing `Reveal` client leaf and media-query gate. The headline, explanatory paragraph, proof and stamps stay immediately visible. Workbench content has no page entrance choreography. Content stays visible without JavaScript or under reduced motion; changing the motion preference destroys smoothing.

## Do's and Don'ts

- Keep the source beside the assertion and label synthetic/preset examples plainly.
- Use semantic headings, visible focus, native controls and short action labels.
- Preserve the review gate explanation when showing a cleared individual assertion.
- Do not claim production verification, privacy certification, live exports or customer adoption from prototype fixtures.
- Do not add external fonts, analytics, forms or client data to this landing page.
