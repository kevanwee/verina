# Git collaboration for agents

Use one repository and an integrated product. Role authorship provides traceability, not isolated departmental ownership. Prefer small, short-lived feature branches and review the integrated result frequently.

## Shared-checkout rules

1. Assign non-overlapping file scopes. Agents report their exact changed files and validation to the coordinator.
2. Serialize `git add`, commits, branch switches, stash operations and pushes. A shared index cannot safely stage two independent commits concurrently.
3. Inspect the staged path list and diff before committing. Never use `git add .` for a mixed work session. Run the repository and secret guards.
4. Use an explicit automation author, such as `Verina QA Agent <verina-qa@verina.invalid>`. The `.invalid` address identifies local automation, not a real GitHub person. The authenticated user remains the committer/publisher. Do not impersonate a human reviewer or invent a signed approval.
5. Push the scoped feature branch and record the branch, commit SHA and actual hosted check status. Open reviewable PRs; never force-push shared branches or auto-merge around failed controls.
6. After a base commit exists, use separate worktrees for parallel branch development. Preserve local ignored planning files in the coordinating workspace.

An initial repository can be assembled from sequential, role-attributed bootstrap commits before publication. Subsequent role work goes through feature branches. A bootstrap commit does not establish branch protection or CI success; inspect repository settings and hosted results.

## Stash and recovery

A stash is a temporary local parking place, not a remote backup, contribution record or replacement for a commit. It requires a base commit. Avoid whole-tree stashes in shared sessions: they can remove another agent's uncommitted work. Prefer an explicit tracked-path stash after ownership and recovery steps are recorded; never include ignored `private/` data with `--all`. Inspect the stash before applying it and retain it until restoration is verified.

Use scoped commits and pushes to preserve completed work. Never create an empty or destructive stash merely to simulate activity. If no tracked work needs parking, record that no stash was needed.

## Publication boundaries

Repository privacy does not authorize uploading confidential planning, client data, secrets or restricted reference documents. `private/` and source extracts stay local. Runtime secrets belong in a secret manager or ignored environment files. Synthetic canaries must be clearly fake, and any scanner exception must match an exact reviewed false positive rather than exempt whole files.

Source publication, deployment and client-data release are different actions. A private branch can hold reviewed development work while production release remains blocked. Actual branch protection, required checks and deployment environment approvals must be recorded, not assumed.

## Required reviewer and merge authority

Every PR requires review by either the Scrum Master or QA, and either role may merge it after the review. Inspect the actual diff and revision-specific evidence, record the reviewer role, findings and limitations on the PR, and wait for all configured required checks to pass. Recheck material changes after review. A draft must be made ready only when its reviewed scope is ready to integrate.

Agents share the authenticated publisher account. GitHub cannot treat an agent's review of that account's PR as another person's approval. Record the agent-role review honestly rather than inventing a human approver or bot identity. Branch protection enforces the configured CI checks and PR route; the role requirement is enforced through the recorded review and team procedure until distinct reviewer accounts exist. Product acceptance, a legal sign-off and production release are not conferred by merging a source PR.
