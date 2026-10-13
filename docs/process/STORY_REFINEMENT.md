# Story refinement and confirmation

Refine upcoming work with the Product Owner and relevant specialists. Developers size it; the Product Owner orders it. Use independent, negotiable, valuable, estimable, small and testable stories as a conversation aid. These attributes guide judgment, not a compulsory extra Scrum gate.

## Story card

```markdown
ID and short title:
As a [abstract user role], I want [action], so that [valuable outcome].
Conversation: actual clarification, open assumption, source/decision owner.
Acceptance criteria:
- Given [relevant state], when [action], then [observable result].
- Negative scenario and expected safe behavior.
- Important boundary, permissions or accessibility scenario.
Scope and exclusions:
Dependencies and risks:
Developer estimate and uncertainty:
Evidence plan (criterion -> test/demo):
```

Write the user's outcome before implementation tasks. Keep a technical enabler explicitly labelled when it is not a user story. Avoid inferring acceptance from an AI-written card. Prototypes help clarify a conversation but do not replace it.

Split by a usable outcome, such as viewing a local synthetic example before editing a real document, rather than by “frontend this Sprint, backend next Sprint.” Keep source provenance and access controls inside relevant slices. Do not split a safety control away from a feature that requires it.

For each criterion, review which plausible wrong implementation the test would reject. Include authorized and unauthorized cases, empty/malformed inputs and relevant boundaries. Separate requirement-level black-box evidence from implementation-level unit tests. Use deterministic doubles for speed, and verify real integration contracts where the chosen release scope requires them. Never use real client documents as fixtures.

## Refinement check

- The user value, decision boundaries and conversation gaps are visible.
- Criteria are observable and independent of the generated implementation.
- The slice can reach Done within the Sprint; estimates reflect uncertainty.
- Permission, privacy, error handling and accessibility requirements accompany the feature.
- The chosen tests and demonstration can detect meaningful failures.
