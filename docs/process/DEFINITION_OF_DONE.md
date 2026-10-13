# Definition of Done

Version 1 · Shared quality commitment · 13 October 2026

All Developers apply this definition to the integrated Increment. Item-specific acceptance criteria describe behavior; this definition describes quality. An implementation may be ready for review without being Done. A local prototype or draft assessment is not a usable client-data product simply because its tests pass.

| Requirement | Inspectable evidence |
| --- | --- |
| User outcome and acceptance criteria met | Happy, negative and boundary scenarios as applicable; criterion-to-test or recorded demonstration mapping |
| Integrated behavior works | Meaningful automated tests and applicable production build; required lint, format and type checks pass |
| Hosted checks pass for the delivered revision | Required CI run and jobs tied to commit SHA; unavailable/skipped checks are explicit, not counted as passed |
| Appropriate reviews completed | Design/accessibility, security and privacy review findings and their disposition; named human review where legal judgment is required |
| Confidentiality and safety controls hold | Synthetic fixtures; no private/source/secret material tracked; model boundary and disabled-live-route tests; no unresolved applicable Critical/High finding or failed gate |
| Documentation reflects behavior | ADR for consequential decision; diagrams, user-facing claims and traceability updated; implemented versus proposed state clear |
| Change is reviewable and recoverable | Scoped diff, agent attribution, compatible dependencies, rollback/recovery notes appropriate to risk |
| Handoff and plan are current | Revision-specific evidence, open limitations, owners and next action; private sprint board and latest checkpoint updated |

Tests must derive expected results independently from requirements. A high coverage percentage, mocks agreeing with themselves or a code author's assurance cannot establish correctness. UI accessibility combines automated checks with keyboard and relevant assistive-technology review; an automated scan alone does not establish full WCAG conformance.

Hosted execution of reference architecture documents can use docs checks where appropriate; documentation does not need meaningless behavioral tests. Draft legal assessments require source provenance and explicit verification limits, and remain drafts until the responsible human reviews the legal judgments.

Do not dilute Done to accommodate missing CI or failed gates. Record work as Ready for review or Unfinished, disclose why, and return unfinished items to the backlog at Sprint end. The Product Owner may record a permitted release-risk decision under project policy; that decision must be explicit and cannot turn an unexecuted test into a passed test or establish statutory compliance.

PO feedback/acceptance is recorded separately from technical quality. Release authorization and deployment are separate from meeting Done. A Sprint Review does not substitute for either. Future increments can proceed while an earlier release remains blocked, provided the Sprint Goal and controls are respected.
