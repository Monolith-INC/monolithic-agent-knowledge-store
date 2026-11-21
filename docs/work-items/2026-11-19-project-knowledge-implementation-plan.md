# Project Knowledge implementation and qualification plan

Status: Revised after acceptance of the [plan challenge](2026-11-19-project-knowledge-plan-challenge.md). This plan sequences work and defines the evidence required to release the [Project Knowledge design](2026-11-19-project-knowledge-design.md).

## Linear delivery

[AGE-143 · Complete the Project Knowledge lifecycle in UPF](https://linear.app/agentical-monolithics/issue/AGE-143/complete-the-project-knowledge-lifecycle-in-upf) groups delivery into three active stories. The phases below explain the work inside those stories. [Upstream PR #10](https://github.com/Monolith-INC/monolithic-code-review-toolkit/pull/10) has merged and passed Linux, macOS, and native Windows CI. Adopt an upstream release that includes it.

| Story | Scope | Depends on |
| --- | --- | --- |
| [AGE-142](https://linear.app/agentical-monolithics/issue/AGE-142/ship-the-standalone-project-knowledge-store) | Upstream engine, standalone query tool, setup, migration, and fact history | Upstream release containing PR #10 |
| [AGE-147](https://linear.app/agentical-monolithics/issue/AGE-147/wire-project-knowledge-into-agents-and-keep-it-current) | Knowledge-first hooks, live host checks, default-branch refresh, and capture | AGE-142 |
| [AGE-149](https://linear.app/agentical-monolithics/issue/AGE-149/sync-project-docs-and-ship-the-project-knowledge-rollout) | Docs ingestion and publication, consumer cutover, and release | AGE-142 to start. AGE-147 evidence is required for release. |

AGE-144, AGE-145, and AGE-146 were folded into AGE-142. AGE-148 was folded into AGE-147. AGE-150 was folded into AGE-149. Linear retains the originals as duplicates.

## 0. Check the release dependencies first

Each check has independent evidence and can proceed in parallel when implementation is authorized.

| Question | Check and output | What it decides |
| --- | --- | --- |
| Can UPF use the upstream engine unchanged? | Check [vendor provenance](../../runtimes/project-knowledge/vendor/review-knowledge/provenance.json). Qualify a revision with portable locking, visible or machine-local lock placement, and a current fact view before ranking and fetching. Run current and historical reads, version conflicts and interruption recovery on Linux, macOS and native Windows. Record the commit, Python versions and CI job URLs. | Whether UPF can consume one upstream release without a fork or duplicate ranker. The pinned engine's hidden lock placement and obsolete hits were reproduced in the plan challenge. |
| Which host paths can enforce an active query? | In disposable fixtures on the target Claude Code, Codex and Cursor clients, record versions, hook trust, session orientation, message injection, covered reads and actions, direct project answers without tools, and subagent handoffs. Include ordinary chat, mixed shell actions, stale task context, timeouts and no-hit results. Measure intervention rate and added time, then set and verify a deadline on representative fixtures. | The per-client, per-action matrix distinguishes context delivery, query observation, enforceable order and instructions-only coverage. Test relevance and grounded use separately. Confirm Cursor's per-message context before claiming it. |
| Can a default-branch update reach the next agent? | Qualify merges and direct pushes on a test repository with no agent active. Recover the pending work from a fresh environment after the producer exits, curate it, then replay it. Test duplicate, canceled, expired, out-of-order and off-branch events and an update with no affected sources. | Whether the provider handoff and local reconciliation are durable enough without a separate service. A pending record is evidence of delivery. Completion requires the later curation run. |

The current [Windows CI job](../../.github/workflows/ci.yml#L47) runs platform, launcher and vendor checks. Extend it to execute the actual store CLI and parallel writer tests. Its existing result cannot qualify native Windows query or write behavior. Desktop hook tests need an actual host session and are separate from CI engine tests.

## 1. Deliver the standalone store and the visible setup

- Reuse store selection and input validation from [the runtime configuration](../../runtimes/project-knowledge/src/upf_knowledge/config.py). Extend the boundary to resolve the path inside the project, reject hidden path segments and escaping links or junctions, and use the single visible locator in the design. Recheck the resolved path at the write boundary. Reject an existing non-store target. Adapt legacy paths as migration inputs. Before switching, verify that legacy writers have stopped or are isolated.
- Start with the existing [setup skill](../../plugins/project-knowledge/skills/setup-project-knowledge/SKILL.md) and [discovery skill](../../plugins/project-knowledge/skills/discover-project-knowledge/SKILL.md). Offer the root default, custom visible paths, and Git tracking with a local-only option. Populate the five tiers from sources and ship the manifest, query tool, engine, glossary and query skill together. On upgrade, verify copied unit hashes and history before selecting the visible store. Leave old data available for recovery.
- Package one tested CLI and engine. Each store carries a standalone copy. Hooks and installation use the trusted release copy against the selected store. Keep the five-tier layout and compatibility for legacy Markdown and TSV units. Add the CLI guidance to [knowledge documentation](../knowledge/README.md).

Done when a clean Git project, a project without Git, a custom path, and an interrupted legacy migration all pass the setup cases. On a clean fixture, the store-side CLI works with supplied Python and no UPF installation or knowledge server. Include visible paths with spaces, existing destinations, forbidden path segments, and a migration attempted with a legacy writer still running.

## 2. Make revisions and curation safe before moving writers

- Add the logical fact and revision rules once above the upstream engine. A correction preserves the original text, marks it obsolete or deprecated, and places its replacement immediately after it. Filter to the current view before ranking, bounded fetch and injection. Explicit history shows what changed. Preserve evidence for each revision and verify branch-specific findings on the target branch before publishing them.
- Keep engine-level whole-file writes behind the domain validation boundary. Use version preconditions and a managed lock covering each mutation, catalog and flow log. Test that alternate spellings of one physical store resolve to one lock identity. Ordinary operations cannot delete. An exceptional proposal binds direct user approval to the target, revision and scope. Purging Git history or external copies is a separate scope.
- Test same-unit and different-unit competing writers. The first case must show a version conflict and preserved history. The second must show both committed units in the resulting catalog. Replay after an interruption must converge without duplicating a revision. In tracked stores, compare a proposed change against its baseline. Detect dropped history or two successors that both claim to be current, including a clean text merge, before accepting the new active state.

Done when setup, interactive curation, and later refresh and ingestion can use the same contract. Raw changes made with an external editor or an older tool remain outside the managed writer. They must be detected before the next managed operation writes over them.

## 3. Wire agent use and freshness

- Map the shared retrieval rule into the [Claude](../../packages/adapter-claude/src/index.ts), [Codex](../../packages/adapter-codex/src/index.ts) and [Cursor](../../packages/adapter-cursor/src/index.ts) adapters. Keep time- and size-bounded injection separate from the query the agent actually runs. Use a tool outcome attributable to the current task, project and agent. A query mentioned in text, an automatic lookup, or a catalog listing alone cannot satisfy the gate. Quote retrieved content as evidence. Verify that untrusted or outdated text cannot change hook control, routing or write permissions.
- Give a blocked tool call an actionable query instruction. Let the query attempt through, and continue with focused source reads when the store is empty, stale, inaccessible, or returns no relevant information. Cover direct answers wherever the response boundary can be verified. Delay extra injections for edits, plans and handoffs until live evidence shows a gap.
- Run refresh from a default-branch event, an observed change since the last completed revision, or a manual request. Qualify a provider handoff of bounded source-change metadata and a local fallback when it is missing or has expired. Compare file and directory references, renames, missing sources and external references. Scope the work to the observed project and revision. Keep pending and completed state distinct, reconcile before advancing the completed checkpoint, and make no-source-change runs no-ops without follow-up commits. Persist identified session notes before exit and finish them after resume when shutdown cannot steer the agent.

Done when live traces show distinct injection and active retrieval, an actionable explanation before a covered tool and a bounded fallback. Test whether the results grounded a subsequent action or answer. For hosted refresh, show event detection, a surviving handoff and a later agent completing it. Catch-up must leave unrelated facts alone and keep unverified facts out of automatic publication.

## 4. Deliver the two documentation flows

- Use document markers to map a stable region to stable fact IDs. `publish-docs` verifies ownership and produces a checked patch bound to the mapping, destination version and active fact revisions. Recheck all three at apply time. Region markers grant no new write permissions. `ingest-docs` quotes people-owned text and skips generated spans. A changed fingerprint detects an outside edit. Preserve the text without assuming who wrote it and freeze changed routing or ambiguous ownership.
- Record intent and completion using the same flow log and recovery contract in both directions. Test failure after intent and after the target write, and a source revision, marker or destination change before retry. Qualify direct automatic writes only on isolated destinations or with protection against unrelated editors between check and replace. Test that private text, local transcript paths and raw errors are excluded from tracked records under the project's sharing rules.

Done when an existing document can round-trip through both commands without generated text being reingested. A person can change one published fact without losing that text, and a restart after interruption produces one traceable flow rather than duplicate writes.

## 5. Cut over consumers and qualify release bundles

- Inventory setup, discovery, review, harness and any other callers of the old server before removing provisioning. The current [CLI tooling](../../packages/cli/src/tooling-runtime.ts) writes a legacy review root, and the [release installer](../../scripts/install-release.mjs) can provision private Python. Replace those paths in the knowledge feature with the shared locator and user-provided Python. Verify the headless discovery route and private-Python fallback no longer select the retired runtime. Change upstream consumers through their supported interfaces. Switch a project's active store only when its managed writers can use the new contract, or report which old writer must be disabled before continuing.
- Rehearse a fresh install and an upgrade using real release bundles. Keep the recovery copy and verify its history. A completed upgrade should give each migrated consumer the same active store, and removal should touch only registrations the installer owns. Make a missing interpreter actionable. Refresh must work without a tracker or Git when the project uses neither.
- Run focused checks while working. Before push, run the repository's clean-clone install with frozen lockfile, typecheck, build, tests, payload verification and hook tests once. Collect native Windows query and write results and the host coverage matrix separately. The [design's acceptance cases](2026-11-19-project-knowledge-design.md#builder-and-failure-case-checks) are the release checklist.

Release only after the upstream revision is pinned and tested, the default-branch event path has worked end to end, and the documented host claims match the live matrix. If a required surface remains unavailable, record the exact gap and bring the affected product requirement back for a decision before treating that surface as supported.
