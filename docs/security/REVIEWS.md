# Security reviews log

Record of security reviews for new external endpoints, model providers, dependencies with network access, and third-party code that runs on developer machines or in CI. Newest entry first.

**How to add an entry:** copy the template, give it the next `R-NNN` id, link it from the PR that introduces the change, and update [CONTROLS.md](CONTROLS.md) if a control changes. Critical/High residual findings block the sprint release gate until fixed or accepted by the PO (acceptance recorded in the entry).

```markdown
## R-NNN — <subject>
Date: YYYY-MM-DD · Reviewer: <role> · Sprint: SNN · Trigger: <PR / task / story>
Scope: <what was reviewed, versions/commits, hashes>
Evidence mode: observed (code/runtime) | static only | documentation only
### Findings
| # | Finding | Inherent rating | Recommendation | Owner | Due | Residual rating |
### Decision
<approved / approved with conditions / rejected> — <who decided>
```

| Id | Date | Subject | Decision | Open conditions |
| --- | --- | --- | --- | --- |
| R-002 | 2026-10-13 | AI orchestrator skeleton and external model call boundary | Synthetic local checkpoint only; external transport disabled | Provider approval, complete PII guard, durable audit, dependency advisory |
| R-001 | 2026-10-13 | Third-party agent skills, plugin and hooks in `.claude/` | Approved by PO (pre-existing); security conditions recommended | 7 (see below) |

---

## R-001 — Third-party agent skills, LegalQuants plugin and Impeccable hooks

Date: 2026-10-13 · Reviewer: verina-security · Sprint: S0 · Trigger: T0.3 / EN-4; supply-chain item SC-4 in [THREAT_MODEL.md](THREAT_MODEL.md)

**Context.** The PO approved these tools on 2026-10-13. This review does **not** disable anything. It rates the risk and recommends controls so the approval rests on known facts. These tools run on developer machines (and potentially CI), not in the Verina product runtime. They matter because they execute with the developer's privileges, see what agents read and write, and can reach the network.

### Scope

| Item | Source | Pinned at | Where it runs |
| --- | --- | --- | --- |
| Vendored skills in `.claude/skills/` (impeccable, taste-skill family, 15 `lq-*` skills) | See `.claude/skills/PROVENANCE.md` | impeccable `245ad82`, taste-skill `d237dd3`, lq-skills `884cf40` | Loaded as agent instructions; Impeccable also ships executables |
| Impeccable hooks in `.claude/settings.json` | `.claude/skills/impeccable/scripts/impeccable` (sh) / `impeccable.cmd` (Windows) launcher | Launcher `VERSION` file: `0.1.14` | `SessionStart`, `PostToolUse` (matcher `Edit\|Write`), `Stop` |
| Impeccable engine binary | `%USERPROFILE%\.impeccable\bin\0.1.14\impeccable.exe` (downloaded by launcher) | engine-probe reports `impeccable-engine 0.1.14`; SHA-256 `38e09451694973ba664a24e67e1502a6913e6d0e533a0a5ae1e04c5963a804b1` | Every hook invocation |
| LegalQuants plugin `legalquants-transactional` | Marketplace `LegalQuants/lq-plugin-oss` (GitHub) via `extraKnownMarketplaces` + `enabledPlugins` | PROVENANCE records `fa5a668`; **settings.json does not pin a ref** | Claude Code plugin loader on session start |

Aggregate SHA-256 of the 134 vendored files under `.claude/skills/` (sorted `sha256sum` of every file except `PROVENANCE.md`, then hashed): `7e41c604d89c6836a2c4ae6fcc526c3869ae2069c1f3b7253e1ddb19ff7bdb5a` (2026-10-13).

Evidence mode: **static review** of launcher scripts, plugin manifests and hook source at `fa5a668`; string inspection of the engine binary; engine-probe executed. No runtime network capture was taken, so network behaviour below is `observed in code/strings`, not `observed on the wire`.

### Observations

**Impeccable launcher and engine**

1. The launcher resolves a binary in this order: `$IMPECCABLE_BIN` (trusted, no check) → sibling `bin/<os>-<arch>/` (absent in the vendored tree) → `~/.impeccable/bin/impeccable` (probe-checked) → version-pinned cache `~/.impeccable/bin/0.1.14/` → `impeccable` on `PATH` (probe-checked) → **download** from `https://github.com/pbakaus/impeccable/releases/download/engine-v0.1.14/` with a `.sha256` sidecar.
2. The download fails closed if the sidecar is missing or mismatched. But the sidecar comes from the **same origin** as the binary, so it proves integrity in transit, not authenticity. A compromised release or account would ship a matching hash.
3. The engine binary contains references to `https://impeccable.style/api` (including `/api/roll`), a telemetry block, and opt-out switches `IMPECCABLE_NO_TELEMETRY`, `DO_NOT_TRACK`, `IMPECCABLE_NO_UPDATE_CHECK`, `IMPECCABLE_API_URL` and `IMPECCABLE_UPDATE_HOST`. `~/.impeccable/update-check.json` exists and records `latestVersion: 4.5.2`, which shows the engine has already made at least one outbound update check. **What payload goes to `impeccable.style` is `not_observed_not_excluded`.** Design-context files that Impeccable reads (for example a product description written by `impeccable init`) could be part of it.
4. `PostToolUse` on `Edit|Write` runs the engine after **every** file write by any agent, including writes under `private/`. Claude Code passes the tool input (file path and content) to the hook on stdin. So the engine sees confidential planning content and, once code exists, any synthetic fixtures. Hook timeout is 5 s (30 s on `Stop`).
5. The kickoff handoff recorded the smoke test as "version 4.0.0". The engine reports 0.1.14 and upstream reports 4.5.2 as latest. The vendored skill and engine versions need to be recorded separately so drift is visible.
6. `scripts/live-browser*.js` injects into local dev pages and talks only to `localhost`. That is acceptable for local design work, but it must never be loaded in a deployed build.

**LegalQuants plugin (`legalquants-transactional`)**

7. `.claude/settings.json` adds the marketplace from GitHub with **no commit pin**. Claude Code will install whatever is at the default branch on first install or update, not the reviewed `fa5a668`. PROVENANCE.md records the reviewed commit but nothing enforces it.
8. At `fa5a668`, the plugin's Claude manifest (`.claude-plugin/plugin.json`) declares **no hooks** and there is no `hooks/hooks.json`. `banner.py` and `wiki_hook.py` are wired only through the Codex manifest (`.codex-plugin/plugin.json` → `hooks/openai.json`). **In Claude Code these hooks are therefore expected to be inert** (`not_observed_not_excluded`: the plugin is not yet installed on this machine, so this has not been confirmed at runtime). A future upstream commit could add Claude hooks, and finding 7 would pull them in silently.
9. If the hooks run (Codex, or a future manifest), they behave as follows:
   - `banner.py` (SessionStart) reads `~/.lq/`, writes a marker file under the temp directory, runs a local `catalog.py` subprocess, and makes no network calls.
   - `wiki_hook.py` (SessionStart, UserPromptSubmit) reads `~/.wiki/` config and writes `runtime.json`. Only if the user has explicitly enabled wiki automation does it read the **user prompt** and run a local retrieval. It makes no network calls.
   - Both fail open and need Python ≥ 3.12. Python 3.14 is present, so they would run.
10. The plugin ships 178 Python files in skills. They can run when an agent follows a skill. One skill has outbound network code: `skills/regulatory/scripts/fetch_source.py` (`urllib.request`). Several use `subprocess`.

**Vendored skills**

11. Apart from Impeccable's launcher, binary-fetching logic and browser scripts, the vendored skills are Markdown instructions. Agents treat them as trusted instructions, so a malicious edit to a skill file is an instruction-injection path into every agent session. Upstream licences are kept (`LICENSE.upstream`, `lq-LICENSE.upstream`).

### Findings

| # | Finding | Inherent rating | Recommendation | Owner | Due | Residual (if done) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Unpinned plugin marketplace pulls unreviewed upstream code, possibly including hooks (obs. 7, 8) | **High** (L3 × I3 = 9) | Pin the marketplace to the reviewed commit (`ref`/`sha` in the marketplace source, if the installed Claude Code version supports it). Otherwise vendor the reviewed tree into the repo and register it as a local `directory` marketplace. Disable plugin auto-update. Re-review on every bump. | SM (config) / SEC (review) | S1 start | Low |
| 2 | Engine telemetry and remote API calls to `impeccable.style` with unknown payload, triggered on every write, which includes `private/` content (obs. 3, 4) | **High** (L2 × I4 = 8) | Add to `.claude/settings.json` `env`: `IMPECCABLE_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`, `IMPECCABLE_NO_UPDATE_CHECK=1`. This keeps the hooks on and only stops phone-home. Designer to confirm design features still work. Keep `PRODUCT.md` / design context files free of confidential strategy. SEC to run one proxied session to observe actual egress. | SM (config) / UX / SEC | S0 (env vars) / S1 (capture) | Low–Medium |
| 3 | Binary authenticity relies on a same-origin checksum; download fallback can fetch a new binary on any machine without the cache (obs. 1, 2) | Medium (L2 × I3 = 6) | Record the engine SHA-256 (above) in PROVENANCE.md. On new machines, verify the cached binary against that hash before first use, or set `IMPECCABLE_BIN` to a verified copy. Prefer a signed release if upstream offers one. | SEC / SM | S1 | Low |
| 4 | `IMPECCABLE_BIN` and `PATH` candidates can redirect hooks to any executable (obs. 1) | Low (L1 × I3 = 3) | Treat as a local-machine trust issue. Do not set `IMPECCABLE_BIN` in shared config. Document it. | SEC | S1 | Low |
| 5 | Vendored skill files are trusted instructions; an unreviewed edit is instruction injection (obs. 11) | Medium (L2 × I3 = 6) | CODEOWNERS: `verina-security` + SM must approve changes under `.claude/`. Add a CI check that recomputes the aggregate hash and fails if it differs from PROVENANCE.md without a matching PROVENANCE update. | QA / SEC | S1 | Low |
| 6 | Version records inconsistent (obs. 5) | Low (L2 × I1 = 2) | PROVENANCE.md to list, per item: upstream URL, commit, licence, install date, reviewer, file-tree hash, and for Impeccable the engine version + binary SHA-256 + whether telemetry is disabled. | SM | S0 | Low |
| 7 | Hooks and plugin skills run in CI if `.claude/` is loaded there; Impeccable could try to download in CI (obs. 1, 10) | Medium (L2 × I3 = 6) | CI must not run Claude Code with project hooks unless intended. If it does, set `IMPECCABLE_HOOK_DISABLED=1` **in CI only**, which leaves developer hooks unchanged. Deny CI egress except package registries. | QA | S0 | Low |

### Recommended PROVENANCE.md fields (for SM)

```text
- name, upstream URL, commit SHA, licence, installed date, reviewed by (R-id)
- tree hash of the vendored directory (method: sorted per-file sha256, then sha256)
- executables shipped (paths) and network behaviour (hosts) per item
- Impeccable: skill commit, launcher VERSION, engine version, engine binary SHA-256, telemetry env vars set (y/n)
- LegalQuants plugin: marketplace repo, pinned commit, hooks active in Claude Code (y/n), network-capable scripts
```

### Decision

Tools remain **enabled** (PO approval, 2026-10-13). Security conditions 1 and 2 are rated **High**. They are configuration-only changes that keep every tool working. Recommend completing them before Sprint 1 starts. If the PO prefers not to apply them, record a risk acceptance here. Conditions 3–7 are due as listed.

### R-001 — PO decision (2026-10-13)
- Impeccable telemetry / update check: **risk accepted by PO — leave enabled.** Revisit before any real client data is processed in a developer environment.
- LegalQuants marketplace: **risk accepted by PO — track GitHub default branch (no pin).** Compensating control: re-review the plugin's hooks whenever the installed version changes (check `/plugin` version at session start).


## R-002 ? AI orchestrator skeleton and external model call boundary

Date: 2026-10-13 ? Reviewer: verina-security ? Sprint: S0 ? Trigger: SEC-1 / ADR-002 / EN-6

Scope: `apps/api/src/verina/ai/`, `verina/config.py`, `verina/audit/events.py`, AI tests, `.semgrep/verina.yml`, and [ADR-002](../adr/002-ai-orchestrator.md). Working-tree review; no release commit exists. Evidence mode: observed code and in-process mock tests; provider documentation; no live-provider requests or runtime network capture.

### Findings

| # | Finding | Inherent rating | Recommendation / current control | Owner | Due | Residual rating |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Original constructor dispatched externally when a key existed; arbitrary base URL/SDK/HTTP client bypassed endpoint review. No proof of approved retention or processing region. | High | **Fixed for S0:** constructor rejects live/default transports and caller-injected clients before SDK construction; only an exact `httpx2.MockTransport` is permitted. Fresh mock HTTP client disables environment proxies. No setting enables live transport. Before activation: approved endpoint/host enforcement, contract/workspace/model/feature terms and residency evidence. | AI/ENG/SEC/PDPA | S1?S2 before activation | Low for mock-only S0; High activation blocker |
| 2 | Regex-v1 misses names, addresses, local phones, bank/passport data and malformed identity tokens; tenant policy can turn redaction off. `redaction_applied=true` indicates execution, not PII completeness. No final-payload re-scan. | High | Mock-only gate contains external exposure. Add full taxonomy coverage, final-request guard with fail-closed escalation and detector/version/guard evidence; preserve conservative handling of imperfect OCR/checksums. | AI/PDPA | S2 before activation | Low external exposure in mock-only S0; High activation blocker |
| 3 | Installed SDK DEBUG diagnostic serializes request-body options. Existing secret test proved key masking but did not test document leakage. | High | **Fixed for reviewed SDK path:** discard `anthropic._base_client` records; DEBUG capture asserts key and document canaries absent. Repeat canaries on SDK upgrades and audit other diagnostics before activation. | AI/ENG/SEC | S0 fix; S1 baseline | Low in reviewed mock path |
| 4 | Completion audit happens after dispatch. Sink failure withholds output but cannot undo disclosure. Process loss/cancellation can leave no completion record; in-memory events disappear on restart; SDK retries lack separate attempt evidence. | High for live release | Durable start record before dispatch, append attempt/outcome reconciliation including cancellation/unknown outcomes, fail before dispatch if start persistence fails. Never claim all HTTP attempts audited from one logical completion event. | ENG/AI | S1 EN-8 before activation | Low external exposure in mock-only S0; High activation blocker |
| 5 | Current events do not expose source ids, detector version, egress guard result, endpoint or processing region; a combined input hash cannot reconstruct source/route provenance. | Medium | Add explicit non-content provenance fields when durable event schema lands. Keep identifiers opaque; actor/matter values and exception request ids are not automatically anonymous merely because document text is excluded. | ENG/AI | S1?S2 | Medium |
| 6 | SDK import guard is a static pattern check. Code could issue raw HTTP, indirect imports or call client directly; separate document blocks reduce injection confusion but do not certify resistance. | Medium | Keep CI patterns as guardrails; enforce network egress independently. No public model route exists in current `/health` API. Add deterministic tools/status boundaries and adversarial tests as workflows land. | AI/ENG/QA/SEC | S1?S3 | Medium |
| 7 | Full npm audit reports 5 High dependency entries from one dev lint-chain advisory; production-only audit excludes these. | High scanner finding | Unresolved release blocker. Do not treat informational CI status or absence from runtime bundles as PO acceptance. Remediate or record explicit PO disposition before release; avoid blind major toolchain downgrade. | ENG/QA/SEC/PO | S0 gate / before release | High; no acceptance recorded |

### Workspace and egress inventory (local-first skill)

| Local state | Location | Sensitivity | Lifecycle / backup implication | Evidence |
| --- | --- | --- | --- | --- |
| Documents, rendered request, output | Process memory; mock responder captures requests in tests | Synthetic development content only | No document store implemented here; process lifetime; debugger/dump exposure remains possible | `orchestrator.py`, `client.py` |
| Redaction mapping | Process memory | Identifiers if supplied | Pickle/copy rejected; no persistence or automatic secure memory erasure guarantee | `redaction.py` |
| AI audit | `InMemoryAuditSink.events` | Hashes, counts, opaque identifiers | Lost on restart; not tamper-evident | `audit.py` |
| Key/config | Environment or ignored `.env`, `SecretStr` wrapper | Credentials | Wrapper masks representation; it does not encrypt environment, file or process memory | `config.py`, `client.py` |
| Diagnostics | Configured application logging handlers | Summaries | Retention/backup depends on host; SDK request logger filtered | `orchestrator.py`, `client.py`, canary test |

| Destination | Trigger / payload | Credential | Retention | Opt-out / control | Evidence / retrieval date |
| --- | --- | --- | --- | --- | --- |
| Claude Messages endpoint, configurable base URL | Intended model run: system, rendered variables, titles and document text, schema/model/cache settings | Configured provider key | Actual organization/workspace/model contract **unknown**; SG processing **unknown** | **Disabled** in S0 before transport construction; explicit mocks only | Code + [retention docs](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention), checked 2026-10-13 |
| Injected mock callback | Test invocation, serialized request | Synthetic test key | In-process test code | Trusted developer test callback; not an adversarial sandbox | `test_client.py`; observed 2026-10-13 |

Dependency-wide/host-wide hidden egress is `not_observed_not_excluded`; this bounded review does not replace network capture. Development-tool egress remains governed by R-001's recorded PO acceptances; no reapproval requested here.

### Provider evidence

ZDR is enabled by arrangement for a specific organization and is subject to feature/model exceptions. API-key presence cannot prove eligibility, contract terms or region. Prompt caching is documented as ZDR-eligible while holding cache representations in memory for its TTL; do not equate it to absence of transient processing. Sources checked 2026-10-13: [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention), [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [SDK logging](https://github.com/anthropics/anthropic-sdk-python#logging). These are general provider docs, not tenant-specific signed evidence.

### Decision and disclosure

Approved for **synthetic in-process development checkpoint** by security with external model transport disabled. This is not a release certificate or a client-data approval. A mock callback is trusted test code: arbitrary malicious Python can bypass application controls, so the gate is an application default-deny control, not a host sandbox. Current redaction is partial and the audit sink is volatile. Before a lawyer can rely on a confidentiality or privilege disclosure for an actual matter, provider terms, full flow controls and runtime evidence need security/PDPA review. Overall disclosure confidence: **Medium** (code and mock runtime reviewed, real provider/host behavior unverified).

Evidence: client/orchestrator/guard tests **73 passed**, Ruff clean, strict mypy clean (27 sources). All provider serialization uses in-process mock transport. Semgrep rule YAML parsed and regex positive/negative fixtures passed; Semgrep binary unavailable locally and its hosted scan is pending. Full npm audit reproduced five High entries with advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm); no mitigation acceptance inferred.
