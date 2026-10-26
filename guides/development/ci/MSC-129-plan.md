# MSC-129 — reproducible CI/CD laboratory

Project task: [MSC-129](https://github.com/fssrepository/myscoutee-roadmap/issues/168).

One MSC-129 commit per independent repository; intermediate commits created for
this task will be consolidated. Credentials, runtime state and personal target
configuration stay outside Git. No application deployment or public publication
is authorized merely by completing this plan.

1. [x] Start the local Docker GitLab CE, registries and group runners.
   Declare group, projects, variables and pinned images through repeatable scripts.
2. [x] Finish the versioned `config/ci/` entries for all 22 MyScoutee repositories.
   Validate the dependency catalog, shared adapters and each compiled GitLab
   pipeline. Keep expensive builds, optional tests, release, deploy and Pages
   manual. Deployment can consume an unpublished candidate.
3. [x] Complete the GitHub Actions scheduler conversion using the same adapters.
   Include version planning, dependencies, optional tests, candidate packages,
   release/downstream, deployment and Pages. Supply script-driven configuration.
   This conversion is presentation-only: do not execute or separately qualify it.
4. [x] Integrate the existing KVM/k3s cluster with GitLab Kubernetes visibility.
   Reuse the microservices Terraform/libvirt and Helm/deployment owner. Version agent configuration and
   setup scripts; keep tokens/kubeconfig private and cluster changes manual.
5. [x] Reconcile the local GitLab from the final declarations; run lightweight
   CI, Package/Container Registry and manual-gate checks. Do not run expensive
   application builds, real target deployment, external publish or Pages.
   Initial checks passed; repeat against the consolidated library/mirror refs
   during the final handoff.
6. [x] Register/update MSC-129 in the MyScoutee project. Consolidate only this
   task's changes into one commit per repository, preserving existing history,
   release tags and unrelated work. Refresh local mirrors with explicit leases
   where consolidation rewrites our own intermediate commits.
7. [x] Record passed checks and untested boundaries; hand over URLs, ports and
   the local login credential path. GitHub Actions runtime and Kubernetes live
   connection remain unproven until the operator supplies their inputs and runs
   those manual operations.

Proceed in numbered order; additions stay queued until their step is reached.

Results and execution boundaries: [verification](verification.md).

## Follow-up: 1.5.1 qualification

8. [x] Remove import-time CI skipping; configure projects and credentials before
   pushing, then run actual patch candidates from the 1.5.0 baseline.
9. [x] Run normal builds automatically, including dependency-triggered backend
   and frontend builds. Keep tests optional/manual and DEB/KVM assembly, release,
   deploy and Pages manual. Release/deploy must not implicitly build a DEB.
10. [x] Reconcile four concurrent native build jobs from versioned environment
    defaults, preserving runner registration and active jobs.
11. [x] Verify the template from a clean checkout and its own environment example.
    Keep the new GitHub conversion inactive and existing workflows unchanged.
12. [x] Commit the follow-up configuration and record actual pipeline results.

## Infrastructure continuation checkpoint (2026-10-25)

Preserve incremental `[MSC-129]` commits so each subsequent change is reversible.
Do not rewrite these checkpoints while the implementation is still being reviewed.

The agreed behavior is optional, manual infrastructure operations. Each operation
checks the existing state first and does no work when its result is already
available. Installer preparation may reuse local verified files or populate the
GitLab Package Registry; only an explicit manual preparation can download missing
large upstream artifacts. VM startup is a separate optional manual operation.
Deployment remains manual and is not gated on those jobs having run in the same
pipeline. It checks the actual target and reports missing prerequisites in English.
It must not provision infrastructure or download missing installers on the user's
behalf. Keep the existing workflow structure; do not introduce mandatory job edges.

Run application environments sequentially on this developer host. Keep only one
active: stop KVM before starting a monolith lab, and stop one product's monolith
before starting the other. Retain their volumes and private state between runs.
These are alternative deployment targets, not a combined production topology.

Checkpoint status: release notes and Terraform state/provider corrections are
saved. The separate operator import tool is committed and has imported local
Ubuntu, Terraform and libvirt-provider files with registry checksum verification.
Optional infrastructure preparation and startup are wired in source, with no
deployment dependency on those optional jobs. A manual infrastructure run reconciles the Terraform configuration even for a
healthy guest; unchanged resources are not restarted. Registry reuse and
Terraform reconciliation have focused tests. The operator tool
has now imported the complete set: Ubuntu, Terraform, libvirt provider, k3s and
the k3s offline image archive. The explicitly authorized k3s downloads were
checksum-verified; the existing larger local assets were reused.

Both application pipelines passed normal build and package. Their manual
`infra:prepare` jobs (then named `infra:validate`) passed with external HTTP/HTTPS routed to an unavailable
proxy and localhost exempted: the complete registry set was detected and no
upstream preparation ran. Backend VM startup and full deployment qualification
remain in progress. See the current entries in [verification](verification.md).

## Current completion queue (2026-10-26, latest user instructions)

The earlier checkpoint prose records intermediate decisions. This queue reflects
what remains after the release/registry corrections and overrides those old
execution boundaries.

13. [x] Exercise release/version/tag/publication as one manual operation on a
    release branch, followed by GitLab MR and GitHub PR integration. SonarQube
    pipeline 488 / job 2159 passed; source version reached both masters.
14. [x] Exercise DEB packaging once more: backend pipeline 489 / job 2165 passed;
    actual Debian metadata verified. Do not rerun it or deploy to Netcup.
15. [x] Remove trial releases/tags/packages; retain source baseline 1.5.0 and one
    consolidated MSC-129 commit per repository on GitHub and GitLab. Keep new
    GitHub Actions inactive. Remove legacy candidate registry copies; publish
    versioned application packages/images only through release. Preserve infra
    installer inputs.
16. [x] Template monolith: corrected dependency packages at version 1.5.0;
    pipeline 563 build 2201, deploy 2210 and verify 2215 passed. All 14 checks
    passed, including browser runtime readiness. Operator reviewed
    https://localhost:18444 (HTTP 18082 redirects) and accepted the result.
    Monolith stopped with volumes retained before continuing to KVM.
17. [x] Template KVM: pipeline 567 package 2228, infra 2231, deploy 2232,
    verify 2237 and agent retry 2241 passed. All four domain images reused.
    Application ready at http://localhost:18030; GitLab Kubernetes dashboard:
    http://localhost:8929/myscoutee/myscoutee-template/-/environments/7.
    Operator accepted the browser result. The VM and port forwarding are now
    stopped, with data retained; VMware qualification follows.
18. [x] Template VMware: pipeline 571 build 2245, deploy 2253 and verify
    2258 passed after adding the missing partial-update helpers to its own
    client-tools manifest. HTTPS: https://localhost:18445. Verification:
    11 passed, 0 failed, 3 HTTP checks skipped for the custom HTTPS tunnel.
    Runtime ready; template running, backend service and all KVMs stopped.
    Operator accepted the browser result; final documentation completed.
19. [x] Create the operator-access PDF under the backend guides, in a contextual
    manuals folder. Use the existing MyScoutee visual standard: logo, cover,
    opening contents, consistent headings/page numbers. Include GitLab, apps,
    SonarQube and monitoring URLs/ports; explain which ignored configuration
    owns each setting and where the operator finds login credentials. Never
    embed passwords, tokens or private keys. Include the reproducible generator
    and visually verify the PDF. The existing learning PDF about Git workflows
    is a different document and does not satisfy this request.
20. [x] Record the three template outcomes and final PDF location, then refresh
    the consolidated commits and mirrors. Existing GitHub Actions runtime tests
    and Netcup deployment remain explicitly outside the requested qualification.
21. [x] Refresh the roadmap and its heatmap image, fill the MSC-129 issue and
    portfolio Project fields (including actual token/time evidence), then close
    the task after the template reviews, PDF and final repository synchronization.
    Use the existing roadmap Project API helper and saved Project-scoped token;
    do not invent missing usage metrics or close the task before qualification.

## Final closure (2026-10-26)

All three template browser checkpoints are accepted. The eight-page Laboratory
Access Manual is in both backend and template `guides/publication/manuals`;
neither frontend receives a copy. The seven-page CI/CD Manual is in this
repository's same manuals folder. All three describe the included inactive
GitHub Actions conversion. PDF source/generators and the existing brand assets
are versioned; all pages were rendered and visually reviewed. The CI reference
notes moved from `docs/` to `guides/development/ci/`.

Final workspace synchronization covers 25 owned repositories (including both
frontends), plus read-only inspection of nine external Lean checkouts. No owned
feature/backup branch remains. The owner requested deletion of the obsolete
backend/frontend v1.4.2 tags and associated releases; both mirrors and local tags
were reconciled, with no untagged GitHub release left. No application rebuild,
new DEB, Netcup deployment or extra release is part of this closeout.

The roadmap ledger records 309,337,386 tokens, 14.028891 active/allocated hours,
2,490 responses and $411.26 frozen API equivalent through 2026-10-26T14:02:01Z.
Four related root sessions are deduplicated; shared effort counts once.
The refreshed account heatmap is separate, never added to task allocation.
