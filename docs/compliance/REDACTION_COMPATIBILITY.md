# Redaction taxonomy and runtime compatibility

Reviewed 13 Oct 2026. Design review only; no live provider or client data used. The 27-category taxonomy is a proposed rule set, not a claim that all categories are implemented.

| Requirement | Evidence in `apps/api/src/verina/ai/redaction.py` | Result / required work |
| --- | --- | --- |
| Full taxonomy coverage | `DEFAULT_RULES` contains NRIC/FIN, email and +65 phones | 24 categories lack default detectors. Names, addresses, bank details, passports and contextual sensitive data require local detection and review |
| Reject NRIC-shaped residual data even if checksum fails | `NRIC_FIN_RULE.validator` is `nric_checksum_valid`; `RegexRedactor.redact` discards failed validator hits | Incompatible with taxonomy's confidence-only checksum policy. Detect and redact candidates despite checksum failure; an independent guard must block unresolved residuals |
| Spaces, partial NRIC and local phones | Default NRIC requires contiguous characters; phone requires +65 | Broader taxonomy patterns are not loaded automatically |
| Stable typed category labels | Runtime uses `NRIC_FIN`, `PHONE_SG`, `EMAIL`; taxonomy uses `NRIC`, `PHONE`, `EMAIL` | Explicit aliases are recorded in JSON as proposals; migration and API/audit compatibility require engineering decisions |
| Actions MASK / DROP / BLOCK / KEEP | Every accepted regex span receives a reversible mapping | Stronger actions need explicit handling; blocked content cannot be treated as ordinary reversible redaction |
| Matter-stable mapping and normalisation | Mapping belongs to one run; only NRIC uppercase normalisation exists | Persisted matter-scoped mappings, alias resolution and phone/email normalisation are target design only |
| Placeholder collision protection | Source literals are reserved before token allocation; a later shared-map collision raises RedactionError before client invocation | Literal/value regressions and a two-document no-client-call test cover the supported boundary. This uses allocation/refusal, not the taxonomy's planned escaping scheme |
| ACL-controlled re-identification | `_reidentify` restores any known placeholder from the supplied map | Caller must enforce matter access and action restrictions; this helper does not establish authorisation |
| Complete final-payload scan | Redactor operates on text; it is not an independent egress guard | Include every serialised field and metadata channel in an independent fail-closed gate |

The current redactor is useful for synthetic skeleton tests. It is insufficient evidence for external processing of client content. A PO exception is not a finding of statutory compliance, and does not replace provider, security or responsible-lawyer requirements.

Taxonomy policy checks: category IDs are unique; tiers and actions resolve; all 37 regex candidates compile; all 27 placeholder types match the placeholder validator; non-reversible categories disallow re-identification. Runtime probes demonstrate the checksum and coverage gaps with synthetic strings; see the PDPA handoff for results.
