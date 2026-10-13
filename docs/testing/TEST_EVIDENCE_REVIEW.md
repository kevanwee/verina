# Reviewing test evidence

Owner: QA · 2026-10-13

Every acceptance criterion needs an observable outcome and a test oracle independent of the implementation. Coverage measures executed code; it cannot establish that the expected behaviour is correct.

## Review checklist

1. Identify the requirement, actor, preconditions, inputs, action and expected result. Keep values that change behaviour visible in the test.
2. Cover the successful path, domain-rule negatives, dependency failures and boundaries immediately below, at and above each meaningful threshold.
3. Check cross-cutting expectations such as tenant authorization, accessibility and error handling once at the shared boundary, then add story-specific cases when behaviour differs.
4. Ask which plausible defect each assertion would detect. A test that mocks the behaviour being tested provides no evidence for that behaviour.
5. Keep clock, identifiers and state controlled. A test must not require another test's leftovers or external-service availability.
6. Review generated code and generated tests for a shared misunderstanding. QA independently derives at least the critical negative and boundary cases from the acceptance criteria.
7. Record suite, commit, environment and limitations. A fake-provider pass establishes the local interaction contract; it cannot establish provider availability, legal correctness, database durability or real authorization.

## Choosing the test boundary

| Level | Keep real | Substitute | Additional evidence needed |
| --- | --- | --- | --- |
| Unit | Behaviour under test | Significant collaborators | Verify assertions detect required state changes and rejected operations |
| Integration | Route, domain logic, persistence adapter and schema | External provider boundary | Use the selected production database engine when dialect, constraints or concurrency matter |
| Browser journey | Running application and browser | External identity/model/reference services | Critical user outcomes, keyboard and motion preferences; production services remain untested |
| Provider contract | Adapter and documented wire schema | Provider response fixtures | Validate field names, status codes and units against versioned primary documentation before live provider use |

Mock the name at the point where the application looks it up, or inject the dependency explicitly. Use a mock to assert an interaction only where the interaction is itself required; use outcome assertions for the user's observable behaviour.

## Current default-suite controls

AI tests inject `FakeModelClient`, fixed clocks and an in-memory audit sink; adapter tests use explicit `httpx2.MockTransport`. Default provider transport rejects live requests. These controls are not a global socket sandbox: other code could still perform network calls. Default-suite enforcement of network boundaries is a planned QA control, and external access must remain documented and explicitly authorized.

When failures occur, fix the behaviour or the legitimate test assumption. Do not silently weaken assertions, delete failures, retry until green or allow a generated test healer to change the requirement. A quarantined test requires an issue reference, owner and visible gate impact.
