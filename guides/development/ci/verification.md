# MSC-129 verification and handoff

## Passed on the local lab

- All 22 repository `config/ci/pipeline.yml` entries accepted by the running
  GitLab compiler, including the pinned shared include.
- Backend/template and both frontend manual gates checked from the compiled
  pipeline. Target deployment depends on the candidate package, not release.
- 17 focused adapter/configuration/version tests passed. The native Git archive
  integration also ran on the shell group runner; the Docker validation image
  skips that integration when Git is absent.
- CI commit pipeline [106](http://localhost:8929/myscoutee/ci/-/pipelines/106)
  passed both validation jobs.
- Source candidate pipeline [128](http://localhost:8929/myscoutee/myscoutee-roadmap/-/pipelines/128)
  passed prepare, dependencies, lightweight build and package; release remained
  manual. Its candidate files were uploaded to the local Generic Package Registry.
- A tiny scratch image passed local Container Registry push/pull with unchanged
  image identity. No external container publication was performed.
- Both group runners are online. Backend/template GitLab agent registration is
  idempotent; tokens are external and protected FILE variables.
- Public inventory/credential-pattern checks and shell syntax passed; all
  generated repository entries match the central catalog/template.

The final documentation/provisioning amendment is validated by the latest CI
pipeline on [the CI project](http://localhost:8929/myscoutee/ci/-/pipelines).
MSC-129 has one commit per independent Git repository. The Project issue records
exact final commit identities; history/tags predating this task are preserved.
The MSC-129 branch commits are synchronized to GitHub and the local GitLab
mirrors. No release tags were pushed. Existing frontend CodeQL may run on a
branch push; the new Actions conversion stays inactive under `config/ci/`.

## Deliberately not executed

No heavy application/DEB/KVM build, optional full application suite, real target
deployment, GitHub package/container release or Pages publication was run.
GitHub Actions files are an inactive scheduler conversion, not a runtime-qualified
workflow. Kubernetes agents are registered, but their in-cluster installation and
live dashboard connection were not run. Terraform state/VM lifecycle was not
changed by these checks. Those actions retain explicit manual gates and require
the operator's private inputs.

## Current continuation: 2026-10-25

This section supersedes the initial execution limits above. The user authorized
real local KVM/monolith qualification and the 1.5.1 release; Netcup deployment
remains excluded. Incremental `[MSC-129]` checkpoints are retained.

- All 22 workspace repositories, including nested frontend checkouts, were
  pushed to both GitHub and GitLab. Remote master hashes matched local master
  for all 22, and all worktrees were clean at the audit.
- Backend [pipeline 268](http://localhost:8929/myscoutee/myscoutee-backend/-/pipelines/268)
  and template [pipeline 269](http://localhost:8929/myscoutee/myscoutee-template/-/pipelines/269)
  passed automatic build and package for 1.5.1 candidates. Candidate packaging
  published only to the local GitLab registries.
- Backend [job 1009](http://localhost:8929/myscoutee/myscoutee-backend/-/jobs/1009)
  and template [job 1029](http://localhost:8929/myscoutee/myscoutee-template/-/jobs/1029)
  passed manual infrastructure preparation with HTTP/HTTPS proxy variables set
  to an unavailable localhost proxy and the local GitLab exempted. Both found
  the complete Package Registry asset set and skipped preparation.
- The independent Terraform module `labkvm/libvirt` 1.5.2 is published; this does
  not change the application candidate version, which remains 1.5.1.
- CI [pipeline 270](http://localhost:8929/myscoutee/ci/-/pipelines/270)
  passed container checks and native Git integration checks. Git-dependent
  release-note, archive and candidate tests run on the native runner.

KVM startup, application deployment, live agent connection and public 1.5.1
release are not yet qualified by this checkpoint. Registry reuse does not imply
that guest OS package installation is fully offline.

The separate scheduled [maintenance pipeline 273](http://localhost:8929/myscoutee/ci/-/pipelines/273)
passed, removing 90 superseded owned candidate sets and freeing 26,141,323,264
bytes (24.3 GiB) on the host. The active backend pipeline 268 was retained and
the native runner resumed accepting work. The daily schedule is active at
03:30 UTC; its [versioned policy](retention.md) is independent of application
pipelines. CI validation pipeline 272 also passed all checks for this change.

## Access

- GitLab: http://localhost:8929
- Group: http://localhost:8929/myscoutee
- CI: http://localhost:8929/myscoutee/ci
- Agents: http://localhost:8929/myscoutee/ci/-/clusters
- Git SSH: `localhost:2224`; local Container Registry: `localhost:5050`.
- Login: `root`. Read the password locally with
  `cat .local/state/root-password` (from the CI checkout).

See [the numbered plan](MSC-129-plan.md), [configuration](configuration.md),
[GitHub Actions](github-actions.md) and [Kubernetes/Terraform](kubernetes.md).

## Follow-up: historical Dependabot failure

The backend's October 23 Gradle Dependabot run failed at manifest discovery:
`dependency_file_not_found`, `No files found in /`. Its old configuration selected
`/` instead of `/server` and was removed by MSC-127 on October 24. Both backend
and template now contain a corrected, inactive `config/ci/dependabot.yml` example.
The directory, Gradle settings, included profile project, wrapper and version
catalog were checked in both repositories. This does not re-enable hosted
Dependabot or claim a successful hosted update run.

## Dedicated runner and automatic module publication

- The versioned `scripts/runner-host.py` helper created the `myscoutee-ci`
  execution account from ignored `.local/private/runner-host.env`. The native
  system service runs as that account, retains runner registration #2 and four
  concurrent jobs, and is not enabled at boot. Its personal-user predecessor
  is stopped. The old personal-user socket-start grant was replaced.
- The helper was repeated successfully; declared backend/template KVM state and
  runner state are owned by `myscoutee-ci` with mode 0700. No VM was restarted.
  Migration removes inherited ACLs so private keys retain mode 0600.
- [CI pipeline 278](http://localhost:8929/myscoutee/ci/-/pipelines/278)
  passed both Docker and native validation with the dedicated runner.
- The automatic microservices [package job 1067](http://localhost:8929/myscoutee/myscoutee-microservices/-/jobs/1067)
  in pipeline 279 reached module publication with `CI_JOB_TOKEN` and verified
  that the existing 1.5.2 module contained identical bytes. No duplicate module
  or artificial version was created. The original 1.5.1/1.5.2 uploads were local
  operator imports, so their original UI publication labels remain unchanged.
  A new-version upload from a job is not yet evidenced by this reuse check.
- The VM guest's Ubuntu package download stall remains separate from host
  authorization; full KVM deployment and the application release are pending.

### Registry-backed Ubuntu guest packages

- Added pinned QEMU guest agent and liburing2 DEBs (412,062 bytes total) to
  `infra/versions.json` and to the operator import helper's `--guest-packages`
  option. Both were imported and their GitLab file SHA-256 values verified.
- The complete new installer set was seeded from the existing local large files
  with external HTTP/HTTPS proxy access blocked. A repeat DEB import reused the
  published files. Partial-set preparation also checks individual registry files.
- Shared guest installer safety tests and optional infra tests passed from both
  backend and template roots. CI tests: 38 passed. Terraform init/validate/fmt
  passed with the locked local provider mirror and blocked external proxy.
- Terraform module 1.5.3 embeds verified guest DEBs in cloud-init and disables
  the old online APT bootstrap. Application release target remains 1.5.1.
  The automatic [package job 1079](http://localhost:8929/myscoutee/myscoutee-microservices/-/jobs/1079)
  published module 1.5.3 and verified downloaded bytes. Package 119 records
  pipeline 283 as its publisher. Actual guest startup still awaits qualification.
- Repeated the DEB import with a nonexistent local source directory and blocked
  external proxy: the complete registry set was reused without any download.
- Scheduled retention pipeline 281 / job 1072 passed under the dedicated CI user.

### Dedicated-runner application and registry qualification

- Backend pipeline 284 exposed a Maven credential forwarding defect: `/bin/sh`
  drops dotted `ORG_GRADLE_PROJECT_gpr.*` names. The adapter now also supplies
  the existing consumer aliases `GITHUB_ACTOR` / `GITHUB_TOKEN` from the same
  private FILE input. A real shell test covers backend and template consumers.
- [Backend pipeline 286](http://localhost:8929/myscoutee/myscoutee-backend/-/pipelines/286)
  passed normal production build 1106 and package 1108 under the dedicated user.
- [Manual infra preparation 1117](http://localhost:8929/myscoutee/myscoutee-backend/-/jobs/1117)
  passed with a blocked external proxy: the new complete registry set was
  detected, and preparation/download/upload were skipped.
- The temporary Wi-Fi-priority route was removed after downloads and build;
  original USB/Wi-Fi routes and priorities are restored. Temporary operator
  copies of the large installers were removed; registry and runner caches remain.
- Startup job 1118 successfully started host sockets without a password and
  restored/verified the pinned module and all host/guest assets from the registry.
  It then exposed an unnecessary direct `/dev/kvm` check for the management user.
  The shared preflight now queries x86_64 KVM capability through libvirt, which
  owns the QEMU process. Two focused capability tests passed from both backend
  and template roots; no extra account group or host permission was added.

### KVM memory reconciliation and connected dashboard (2026-10-26)

- Backend pipeline 358 retained the existing 1.5.1 candidate: normal build 1574,
  package 1576 and KVM image assembly 1578 passed. All eight domain assemblies
  reused their verified images; no domain JAR rebuild was required.
- Deployment 1581 and public verification 1588 passed, including canonical
  landing catalog records and their image assets. Cluster job 1587 verified a
  live agent connection and configured the existing `kvm` environment dashboard.
  Open [the Kubernetes environment](http://localhost:8929/myscoutee/myscoutee-backend/-/environments/3).
- The previous CI overlay incorrectly reduced backend RAM from 8192 to 5120 MiB.
  Backend `2a1fe441d` and template `d58e0f6` removed their CI RAM overrides;
  each product keeps its own native allocation (8192 / 6144 MiB respectively).
- Microservices `a353665` removed the arbitrary 4–10 GiB range and additional
  2-GiB host-free-memory gate. Manual infrastructure startup now reconciles
  Terraform even when Kubernetes is responding. Deployment remains independent
  of these optional manual jobs and does not provision infrastructure.
- CI `cbbc561` lets infrastructure jobs run after dependency preparation without
  an application build/package. GitHub conversion uses the same prerequisites;
  its runtime remains untested and the new workflows remain inactive.
- Infrastructure job 1616 refused a cloud-init ISO replacement caused solely by
  removal of the existing empty `packages: []` field. Microservices `62c9f91`
  retained that field; automatic module package job 1628 published module 1.5.6.
- [Terraform job 1645](http://localhost:8929/myscoutee/myscoutee-backend/-/jobs/1645)
  then passed: **0 added, 1 changed, 0 destroyed**, changing only domain memory
  from 5120 to 8192 MiB. The authoritative GitLab Terraform state records
  `memory: 8192`, `memory_unit: MiB`; VM UUID and disks are retained.
  This reconciled the earlier direct operator memory adjustment through the
  committed Terraform workflow. No application build ran in pipeline 364.
- Repeated infrastructure job 1651 passed with **0 added, 0 changed, 0 destroyed**;
  the declared 8192-MiB allocation remained unchanged and no domain restart was needed.
- After Terraform reconciliation, deployment retry 1652 and public verification
  1653 passed using the same pipeline-358 images. The backend agent reports one
  active GitLab connection; the existing environment dashboard remains bound.
- Focused infrastructure tests: 5 passed from each product root. Runtime config
  tests: 10 passed from each root. CI adapter/configuration suite: 48 passed.
- These results do not claim completion of monolith, VMware, public release or
  Netcup qualification. Netcup deployment remains excluded by the operator.


## Monolith readiness and pipeline scheduling (2026-10-26)

- Backend master `462737638`, template master `746d9cb`: both pin the published
  nginx 1.5.1 digest and packaging 1.5.1. GitLab released these dependencies in
  pipelines 402 and 401, respectively; their optional test jobs passed first.
- Nginx regression coverage reproduces the original shared-credential mode 0400
  under umask 077 and verifies readable, non-writable mode 0444 for the API UID.
  Existing credential contents are preserved. Public image assets and synthetic
  test fixtures have explicit readable permissions.
- Backend pipeline 408: build 1835, monolith deployment 1844 and verification
  1849 passed. Verification now reports **14 passed, 0 failed, 0 skipped**,
  including the runtime-status endpoint and embedded HTML readiness snapshot,
  public translations, landing data, anonymous operator denial, and HTTP/TLS policy.
  Entry: https://localhost:18443; http://localhost:18081 redirects to that port.
  Persistent Mongo/configuration volumes were retained. KVM remains stopped.
- Template pipeline 409 build 1853 passed with its own images and locks. Its
  runtime was not started alongside the backend monolith. KVM and VMware have
  not yet been requalified with these new dependency versions.
- CI `16157fa` adds a per-project build resource group and new-commit cancellation
  for automatic prepare/dependency/build jobs. Manual heavy builds, release and
  deployment remain non-interruptible. All 23 project entries passed GitLab lint;
  active candidates retain their initial CI-library revision.
- Packaging release and nginx release each emitted their own consumer event.
  The subsequent canonical dependency commit superseded backend pipelines 403/406
  and template pipelines 405/407; those incomplete candidates were canceled.
  Different dependency events on one source commit are not equivalent inputs.
- Earlier CI jobs 1655, 1657 and 1659 were the small `validate:git` checks for three
  distinct CI source pushes (2945cdda, ee0e9e0d, 3ac3bfcd), not three app builds.
- This qualifies the monolith deployment checks, not a complete interactive
  application campaign or publication of the main application's 1.5.1 release.


## VMware partial update (2026-10-26)

- Backend `348f8ed26`, template `343502a`: production API/nginx build labels
  identify the service, candidate version and explicitly supported 1.5.0 host
  package. Both Compose configurations were checked; template runtime was not started.
- CI library `d80d8b9`, backend pipeline 447: build 1979, VMware deploy 1987 and
  external verification 1992 passed. Deployment uses the signed, uncompressed
  archive of existing named images and the product's partial-update installer.
  The installed Debian package remains 1.5.0; the application reports 1.5.1.
- Host qualification passed container health, Mongo compatibility/CRUD smoke,
  required and demo seed checks, backend/content checks and Hungarian i18n.
  Public verification: **11 passed, 0 failed, 3 skipped**. HTTP listener/redirect
  checks are skipped because HTTPS is forwarded on a noncanonical local port.
  TLS trust, assets, runtime readiness, translations, landing data and anonymous
  operator denial passed. Entry: https://localhost:8443, also set on the GitLab
  `vmware` environment. The tunnel remained reachable after the verify job ended.
- VMware cleanup removed 54 unreferenced dangling images after checking running
  containers and retained rollback state, freeing 4.36 GiB. Data, backups and
  referenced rollback images were retained; 5.1 GiB remained free after deployment.
- SSH, known-hosts, CA and signing inputs live in the backend's ignored private
  files, reconciled into scoped GitLab FILE variables. The extra FILE-input
  transport test passed; the adapter suite's 20 tests passed after transport fixes.
- Host monolith and KVM remain stopped. No Netcup deployment or main-application
  GitHub release was performed in this VMware qualification.

## Release and DEB checks after history consolidation (2026-10-26)

- All 22 catalog repositories have one MSC-129 commit on `master`, pushed to
  GitHub and GitLab. Source version files
  remain at their pre-release versions; candidate version changes are made by CI.
- SonarQube pipeline 482, release job 2148 passed. GitHub and GitLab `v1.5.1`
  resolve to `db896bc84ab18b8a745adb964f7ffc1fce10664f`. Both GitHub assets were
  downloaded and matched the GitLab package SHA-256 values. The source archive
  contains VERSION 1.5.1 while master retains VERSION 1.5.0. The description is empty.
- Backend pipeline 450, `package:deb` job 2008 passed using its existing build.
  The resulting package metadata is `myscoutee`, `1.5.1`, `amd64`. This is a
  packaging check, not a new install or public backend release.
- Retention pipeline 483, job 2150 passed; available disk space increased from
  approximately 17 GiB to 37 GiB before packaging completed.
- Removed the backend-to-public-frontend release redirect. The adapter's 21
  focused tests pass, including backend and template publication to their own
  repository even when the obsolete redirect variable remains in an environment.
  GitHub Actions stays an inactive conversion using the same adapter.
- The frontend v1.5.1 release and tag were withdrawn from both providers at the
  user's request. Its versioned GitLab generic package was removed as well;
  other releases remain. New hashed frontend output is now included in source
  snapshots, with ignore rules retained. Native Git tests cover both frontends.
- Candidate 450's frontend `app-version.json`, nginx OCI version label and DEB
  metadata all contain 1.5.1. Packaging reused the built images without compiling
  again. The application release/GHCR promotion gate was not played.

## Final release-branch and registry qualification (2026-10-26)

This supersedes the earlier source-tag-only release check above.

- CI validation pipeline 487 passed. The shared adapter now publishes on
  `release/v<version>` and integrates through provider merge APIs, without a
  direct master push. A publication receipt allows merge-only retry.
- SonarQube pipeline 488, release job 2159 passed. GitLab MR 1 and GitHub PR 1
  both merged; both masters then contained VERSION 1.5.1, and both release
  branches were removed. The same job created the tag, GitLab package and
  GitHub Release with the source archive and build-input receipt.
- Backend pipeline 489, build 2163 and manual `package:deb` 2165 passed.
  `dpkg-deb` independently confirmed Package `myscoutee`, Version `1.5.1`,
  Architecture `amd64`. No application deployment or public backend release
  was performed. No additional DEB rerun is required.
- Ordinary candidates now stay in the pipeline workspace and local Docker
  daemon. Removed 15 legacy candidate packages and 16 obsolete container
  repositories (124 tags) from GitLab. Infrastructure inputs are preserved.
- The five MSC-129 trial releases (packaging, nginx, QA, microservices and
  SonarQube) and their v1.5.1 tags are withdrawn after qualification, along with
  their GitLab generic packages and test npm/GHCR versions. The previously
  withdrawn frontend trial remains withdrawn. Pre-existing releases are retained.
- Source and consumer version references return to 1.5.0. Every catalog master
  retains one consolidated MSC-129 commit, on both providers. The newly added
  GitHub Actions conversion remains inactive under `config/ci/`.
- 54 shared CI tests and five native assembly-cache tests pass. Tests cover
  release head mismatch/conflict, merge retry without republication, both
  application repositories, existing optional DEB signing/upload destinations,
  and the four independent image projects promoting recorded image identities.
  Live GHCR publication of every application/KVM variant was not repeated.

## Template monolith checkpoint (2026-10-26)

- Template pipeline 517: own build 2183, deploy:monolith 2192 and
  verify:monolith 2197 passed. The verifier reported 13 passed, zero failed,
  zero skipped: transport/redirects, frontend assets/routing/PWA/precache,
  backend health/public configuration/i18n/documents and operator boundary.
- Browser endpoint: https://localhost:18444; HTTP http://localhost:18082
  redirects to HTTPS. Configuration owner: template config/ci/monolith.json.
  The isolated candidate reports 1.5.1; master source stays 1.5.0.
- Compared MSC-129 backend/template changes: shared Mongo import, seed-image
  permissions, nginx/MinIO/MCP Dockerfiles, image labels and Helm configuration
  fixes are reflected in both. CI adapters are shared; project-specific ports,
  namespaces, image identities and services remain independent. The backend-only
  current-monolith performance script changed its private output directory; the
  template has no equivalent script and retains its own test runners.
- Operator browser review found an offline notification. The 13-check result
  did not exercise browser readiness: this candidate consumed the old packaging
  and nginx dependencies. This checkpoint is NOT qualified. Do not start KVM or
  VMware before the monolith defect is resolved and the operator continues.

## Dependency correction at the existing version (2026-10-26)

The operator explicitly requires replacement of the existing 1.5.0 packages,
not a version bump or CI source override. The shared nginx credential fix and
packaging browser-readiness check already exist in source; no application code
change is needed. The backend must not be rebuilt or retested for this correction.

- Replaced the packaging npm 1.5.0 archive on GitHub Packages, its GitHub Release
  asset/checksum, and GitLab Generic Packages. Regenerated consumer lockfiles at
  the unchanged exact version, including Registry's packaging consumer.
- Published corrected nginx as 1.5.0 on GHCR and GitLab Container Registry. Both
  products pin digest `sha256:9ab49ea949afaee5164e828b699c102dca38a2766d7573c4f342984e8da74774`
  consistently in dev/prod Compose, dev/E2E/prod Dockerfiles, packaging and KVM.
  Its credential regression checks pass for new and existing credentials.
- Removed the two mistakenly restored trial package versions again. Removed the
  unpublished trial release-note placeholders across the catalog. No source-pin
  override or additional dependency mechanism was added to CI.
- Publication and dependency metadata checks do not establish that the already
  running template container has changed. Its runtime handoff remains pending.

## Template monolith accepted (2026-10-26)

- Pipeline 563 consumed the corrected packaging/nginx 1.5.0 dependencies.
  Build 2201, deploy 2210 and verify 2215 succeeded: 14 passed, zero failed,
  zero skipped, including backend/runtime-readiness.
- Independent `/api/runtime-status` inspection returned `ready: true` and
  `known: true`. The operator accepted the browser result at
  https://localhost:18444 and requested continuation to template KVM.
- Stopped only the template monolith Compose project, retaining its volumes.
  The backend was neither rebuilt nor retested. No public release was created.
  Source baseline remains 1.5.0; the isolated qualification candidate is 1.5.1.

- Initial template KVM package job 2204 passed. Infra job 2207 reused all large
  assets from the GitLab registry, but correctly rejected a stale Terraform
  module. The module's existing version setting is now explicitly 1.5.0,
  independent of an application qualification candidate's planned version.

## Template KVM browser checkpoint (2026-10-26)

- Microservices pipeline 566 / build 2219 published `labkvm/libvirt` 1.5.0
  using the job identity and verified downloaded module bytes. Source/catalog
  explicitly pin this module version independently of application candidates.
- Template pipeline 567 build 2225 and package:kvm 2228 passed. Identity,
  communication, media and help all reported `reuse` in the assembly plan.
- Infra job 2231 reused the complete registry installer set, disabled upstream
  bootstrap downloads and started only `myscoutee-template-ci` (6 GiB, its own
  configuration). k3s readiness passed; cloud-init reported completed with
  warnings. Its state and guest 192.168.176.10 are independent of the backend.
- Deploy 2232 streamed 12 missing images into the fresh guest containerd store;
  all image identities matched the lock. Helm deployment and port forwarding
  passed. Verify 2237 passed all configured public checks. Independent runtime
  inspection returned `ready: true`, `known: true`.
- Concurrent verify/agent jobs exposed a temporary-runtime-file race in agent
  job 2236. The shared `.verify` now uses the same candidate resource group as
  deployment/agent jobs; GitLab CI lint passed. The inactive GitHub conversion
  already serializes operations on the same candidate via workflow concurrency.
  Sequential agent retry 2241 passed and confirmed GitLab's live connection.
- Browser URL: http://localhost:18030. Kubernetes overview:
  http://localhost:8929/myscoutee/myscoutee-template/-/environments/7.
  Operator review is pending. Monolith is stopped with data retained; backend
  environments remain stopped and no backend rebuild/retest was performed.
- Freed unused Docker build cache (older than 24 hours, then older than one
  hour) before provisioning. Existing images and application volumes were kept.

## Template VMware preparation (2026-10-26)

The operator accepted the KVM browser result. The template CI VM shut down
gracefully and its port forwarding closed; data was retained. The operator
started VMware. Both products were installed there at 1.5.0; backend autostart
occupied template container names. Backend was stopped and template's existing
service started, with all seven containers healthy.

Template VMware inputs live in its ignored `config/packaging/client-tools/`
and `.local/private/vmware/` directories. Its versioned defaults select HTTP
18083 / HTTPS 18445. Required remote, forwarding and update helpers are tracked
in the shared CI/packaging repositories; no private helper is needed to deploy.
The GitLab transport uses scoped known-hosts FILE input, not an operator-specific
path embedded in SSH options. An initial SSH check rejected that path before
mutation. Deploy retry 2242 then backed up the template and verified/transferred
the images, but found that its client-tools manifest omitted the existing partial
update helpers. Added both helpers, matching backend's existing manifest. No
backend rebuild/retest or additional DEB packaging is required for this fix.

## Template VMware browser checkpoint (2026-10-26)

- Pipeline 571 build 2245 packaged the versioned template client-tools manifest,
  including both partial-update helpers already supplied by the shared packaging
  package and backend manifest. No ad-hoc remote helper copy was used.
- Deploy 2253 passed through the existing backup, signature/checksum verification,
  image transfer, per-service partial update and internal qualification flow.
  Existing installed Debian package remains 1.5.0; the unpublished application
  qualification image version is 1.5.1. No release or DEB job was run.
- Verify 2258 established the SSH forwards and validated TLS with the template's
  own saved certificate. Eleven checks passed, zero failed; three HTTP checks
  were skipped because the verifier receives only the custom HTTPS URL.
  Independent HTTPS `/api/runtime-status` returned `ready: true`, `known: true`.
- Browser: https://localhost:18445. HTTP tunnel 18083 reaches the guest's normal
  redirect to https://localhost/ (443), not the custom tunnel port; use the HTTPS
  URL for browser review. The standard remote verifier's HTTP checks are not
  claimed as passed.
- The operator's VMware guest 192.168.153.129 now runs only the template product.
  Backend service and all local KVM guests are stopped; application data is
  retained. The template remains running for operator review.
- Port defaults, client-tools manifest and operating documentation are committed
  in the consolidated MSC-129 changes. Private SSH/signing/certificate/install
  inputs are ignored in the template repository and reconciled as scoped GitLab
  variables by the existing configuration script.

## Final operator acceptance and documentation (2026-10-26)

The owner accepted template VMware after monolith and KVM, completing the three
requested browser checkpoints. VMware remains available at https://localhost:18445;
its verify result is 11 passed / 0 failed / 3 HTTP checks skipped. The template
monolith and KVM guests are stopped with data retained. Earlier descriptions
that await this final review are superseded by this acceptance.

The backend and template each contain `guides/publication/manuals/`
`MyScoutee_Laboratory_Access_Manual_EN.pdf` (8 pages). The CI repository contains
`MyScoutee_CICD_Manual_EN.pdf` in the same contextual directory (7 pages).
All are branded, include opening contents and page numbers, and were visually
checked after rendering. The existing HTML manual renderer supports a per-manual
frontend-publication override; both access manuals set it to false. The CI
manual has a standalone committed ReportLab generator and logo. GitHub Actions
conversion availability, inactivity and untested runtime are stated in all three.

Only documentation/configuration-path reconciliation and repository/accounting
closure followed the accepted deployments. No runtime rebuilding or restarting
was performed. Final GitHub workspace audit and Project-field read-back are
recorded in the roadmap closure.
