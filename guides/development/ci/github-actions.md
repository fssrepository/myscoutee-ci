# GitHub Actions conversion (MSC-129)

`config/ci/github-actions.yml` in every repository is the complete scheduler
conversion of the GitLab laboratory pipeline. The canonical template lives in
`examples/github-actions.yml`. It is deliberately outside `.github/workflows`:
this task does not install, dispatch, run or separately qualify it. Existing
GitHub workflows and Pages retain their previous settings. Repository-wide
Actions disabling is not part of this setup; only the new conversion is inactive.

## Correspondence

| GitLab | GitHub Actions |
| --- | --- |
| Commit push / dependency pipeline | Push / `repository_dispatch` |
| Prepare, dependencies | Candidate job, separate named steps |
| Automatic `build` (build + local storage) | Candidate steps for all non-DEB recipes |
| Manual admin-client `build` | `workflow_dispatch`, action `build`, existing candidate ID |
| Optional tests | `workflow_dispatch`, action `test` |
| Full DEB / KVM image assembly | Manual `deb` / `kvm` actions |
| Manual release / publish | Manual `release`, then automatic downstream dispatch |
| Consumer release dependency | `myscoutee-dependency-release` event with immutable input metadata |
| VMware / KVM / monolith / Netcup deploy | Manual `deploy`, target selector; no release prerequisite |
| Optional infra preparation and VM startup | One manual `infra_start` action |
| GitLab agent installation/binding (`deploy:agent`) | Manual `cluster` action |
| Optional target verification | Manual `verify` after successful target deployment |
| Manual Pages branch update | Manual `pages`, target `github-pages` |

Both schedulers call `project.py`; GitHub's `github.py` maps context, materializes
secret FILE inputs temporarily and retains candidates by repository/run ID. A
candidate records its source and shared-library SHA; resuming with a different
library fails. One trusted self-hosted `lab-build` runner with persistent storage
is required. Do not route these jobs onto ephemeral hosted runners or unrelated
machines. The candidate ID is printed in the initial run's summary.

This is a scheduler conversion **with the same local GitLab registries**. It
requires the local GitLab project mirrors, group bot and package/container
services. GitHub owns actions and consumer events; the shared publish adapter
records releases on both providers and promotes to GitHub Packages/GHCR. The
local GitLab URL must be reachable from that self-hosted runner. Nothing is
published by merely creating a candidate.

## Explicit installation and configuration

```sh
python3 scripts/install-github-actions.py ../ --project myscoutee-backend
# Review and commit the generated .github/workflows/laboratory.yml yourself.
python3 scripts/configure.py --provider github --all-projects
python3 scripts/configure.py --provider github --all-projects --apply
```

Configuration reads versioned declarations and ignored `.env`/private files.
`LAB_CI_REF` must identify the same reviewed CI commit already available on GitHub;
`LAB_CI_REPOSITORY` defaults to `fssrepository/myscoutee-ci`. Configure
`LAB_CANDIDATE_ROOT` as an absolute private directory on the runner. The saved
`LAB_GITHUB_TOKEN` needs cross-repository contents/actions/event publication and
package permissions. The built-in repository token cannot replace that access.

Project environment declarations are applied to each GitHub environment using
`--env`. Select `kvm` for the `kvm` action, the deployment's target for deploy and
verify, and `github-pages` for Pages. Repository secrets contain shared inputs;
environment secrets hold target-specific FILE contents. Manual dispatch is the
portable gate; reviewer protection is optional and subject to the account plan.
The conversion accepts the default branch and `feature/*` pushes, without
fork/PR jobs. Feature candidates can build and deploy manually to VMware;
release/downstream/Pages are rejected outside the default branch.

Retries never silently rebuild an already completed phase. If publication fails
partway across providers, inspect the partial result and reconcile deliberately;
immutable release tags are never overwritten. A consumer dispatch receipt proves
only dispatch, not downstream pipeline success.

References: [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[repository events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#repository_dispatch).
