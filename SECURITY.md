# Security policy

Verina processes confidential and legally privileged material, so we take security reports seriously.

## Reporting a vulnerability

- **Do not open a public issue, pull request or discussion** for a suspected vulnerability.
- Report it privately through GitHub's **"Report a vulnerability"** (private security advisory) on this repository. If that is not available, contact the maintainers privately.
- Include: affected component or file, steps to reproduce, impact, and any proof-of-concept. **Never include real client documents or personal data.** Use synthetic examples only.

What to expect:

| Step | Target |
| --- | --- |
| Acknowledgement | within 3 business days |
| Initial assessment and severity (Critical / High / Medium / Low) | within 7 business days |
| Fix or mitigation plan for Critical / High | before the next release gate |

Please give us a reasonable time to fix the issue before any public disclosure. We will credit reporters who want to be credited.

## Scope

In scope: this repository's code, configuration, CI workflows, and the third-party skills and hooks vendored under `.claude/`.

Out of scope: social engineering, physical attacks, denial-of-service volume testing, and third-party services (report those to the vendor).

## Supported versions

Pre-release. Only the `main` branch is supported.

## Security documentation

- [Threat model](docs/security/THREAT_MODEL.md)
- [Data flows and egress inventory](docs/security/DATA_FLOW.md)
- [Controls matrix](docs/security/CONTROLS.md)
- [Security reviews log](docs/security/REVIEWS.md)

## Handling secrets

No secrets in the repository. Use `.env.example` for variable names only. A pre-commit hook (`.githooks/pre-commit`) and CI secret scanning enforce this. If you commit a secret by mistake, treat it as compromised: rotate it first, then remove it.
