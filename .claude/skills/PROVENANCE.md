# Third-party skills provenance (installed 2026-10-13)
- taste-skill @ d237dd3 (https://github.com/Leonxlnx/taste-skill.git)
- impeccable @ 245ad82 (https://github.com/pbakaus/impeccable.git)
- lq-skills @ 884cf40 (https://github.com/LegalQuants/lq-skills.git)
- lq-plugin-oss @ fa5a668 (https://github.com/LegalQuants/lq-plugin-oss.git)

## Corrections and notes (2026-10-13, after security review R-001)
- Impeccable: skill launcher reports `4.0.0`; the engine binary it fetches reports `0.1.14` (SHA-256 recorded in docs/security/REVIEWS.md R-001). The engine has telemetry and update-check code paths calling https://impeccable.style/api.
- LegalQuants plugin is installed via the `legalquants-skills` marketplace from GitHub default branch; reviewed commit is `fa5a668`. Pinning pending PO decision.
