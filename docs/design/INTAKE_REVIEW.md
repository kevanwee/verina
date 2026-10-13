# Intake walkthrough review

Candidate surface: `/workbench/intake`, plus its entry link in `/workbench`.
Local source review: 13 October 2026. Hosted revision evidence and independent final review must be attached to the pull request; these local results do not assert merge, release or product acceptance.

## Design direction and scope

The walkthrough preserves the incumbent cool-paper/graphite/indigo system, fixed interface type scale, native controls, restrained result feedback and clear source/status language. It is an Operate surface for explaining intake and conflict-check states. Taste's own instructions exclude multi-step product UI; its applicable dependency, focus, theme and motion checks are retained without importing landing-page choreography. Minimalist and redesign guidance inform restrained spacing and targeted repair, while the existing product identity and work-surface rules take precedence.

Impeccable product/design context, Operate guidance, craft floor, critique and audit references were read. The deterministic scan returned no findings for the intake route. Native Claude hooks were not executed in Codex. This author's review is a provisional single-context assessment, not the required isolated dual-agent critique or a WCAG conformance certificate. Product/design context remains inherited; no replacement identity or invented user research was introduced.

## Corrections

- Prominent invented-input-only warning and memory/reset disclosure; autofill switched off for editable prototype controls. The role selector explicitly demonstrates visibility and is not authentication.
- Waiver validation matches the nonblank, 2,000-code-point maximum rule. No invented minimum or legal-sufficiency assessment is applied. Overlong reasons have focused, recoverable errors.
- Audit wording describes a simulated record; requester wording states readiness for legal review rather than claiming a lawyer has performed it.
- Keyboard regression uses a finite Tab bound. Reset restores fixtures and focus; reload discards entered state.
- Adding an intake navigation link exposed a 320 px workbench overflow. Phone navigation now wraps; the phone header is static so focus targets are not covered.

## Local verification

Clean `npm ci` succeeds, including declared `@gsap/react` and pinned `@testing-library/user-event` dependencies. Web tests pass: 47 across five files. Lint, route type-check and production build pass; intake is statically prerendered. Production dependency audit reports zero vulnerabilities. The full development audit still reports five High entries in the inherited lint dependency chain; these remain visible to the repository's security/release review.

Headless Microsoft Edge production-build checks cover 1440, 390 and 320 px widths in both light and dark themes. Draft, waived and requester states have zero observed automated accessibility violations. Both workbench and intake have no page overflow at these widths. Keyboard intake/waiver, skip link, focused results, reset focus, 200% root text scaling and switching to reduced motion are exercised. Normal-motion Lenis is active; switching preference destroys smoothing. Scoped GSAP state feedback is visible without motion.

Fresh browser contexts observe same-origin GET requests only, no input marker in requests, no cookies, no local/session storage entries and no IndexedDB databases after the walkthrough. Reset and reload restore the synthetic sample. These observations describe this implementation; they are not guarantees about browser extensions, autofill behavior or downstream hosting infrastructure.

Manual screen-reader testing, physical-device touch, additional browser engines, field performance measurements and independent final design/security review remain outstanding. Server integration, actual tenant/role enforcement, retained audit data, uploads and legal review are outside this prototype's scope.

## Independent review follow-up

Separate design critique and technical QA inspected the candidate source and synthetic
browser evidence. The critique found that editable party input could be mistaken for a
real register search against fixed fixtures. The display now says preset synthetic
matches, states that edits do not change them, and labels the sample-party relationship.
Manual accessibility and real service integration remain open; exact-head CI and source
review are required before merge.
