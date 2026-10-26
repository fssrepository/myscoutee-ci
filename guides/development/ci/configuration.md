# Configuration ownership

Each repository owns its public `config/ci/` entry. Shared public values live in `.env.example`, `compose.yaml`, `ci/projects.json` and
`examples/variables.json`. `configure.py` reconciles declarations through the
API and supports literal dotenv input (no shell execution/interpolation).
The CI library SHA is derived from the reviewed committed checkout, since a
file cannot embed the SHA of its own commit. Defaults, project destinations and
fixture pins are versioned; per-installation secrets are file inputs.

## Variables

| Variable | Scope/type | Purpose |
| --- | --- | --- |
| `LAB_CI_PATH`, `LAB_CI_REF` | Group, public | Shared CI path and immutable library commit |
| `LAB_GROUP_PATH`, `LAB_SOURCE_BASE` | Group, public | Consumer routing and authenticated source clone base |
| `LAB_APPLICATION`, `LAB_FRONTEND`, `LAB_HEAVY_BUILD` | Project, public | Gates derived from versioned project type |
| `LAB_GITHUB_REPOSITORY` | Project, public | Explicit `owner/repository` destination |
| `LAB_BUILD_CONCURRENCY` | Local public default | Four native runner jobs; reconciled without restart |
| `LAB_DOCKER_BUILD_NETWORK` | Group, public | Standalone Docker build network; local lab defaults to host |
| `LAB_RELEASE_LEVEL` | Pipeline, public | `major`, `minor`, `patch`; default patch |
| `LAB_NPM_REGISTRY`, `LAB_IMAGE_NAMESPACE` | Group, public | GitHub npm and GHCR publication destinations |
| `GITHUB_REPOSITORY_OWNER` | Group, public | Native application image publisher's namespace |
| `LAB_MICROSERVICES_REVISION` | Group, public | Exact support source commit |
| `LAB_FIXTURES` | Group, public JSON | Exact test fixture commits; cloned only by optional tests |
| `LAB_RELEASE_TOKEN` | Group, protected/masked | Local GitLab group bot; generated outside Git |
| `GH_TOKEN` | Group/project, protected/masked | GitHub publication and Pages permission |
| `LAB_NPMRC` | Protected FILE | npm registry credentials/configuration |
| `LAB_GRADLE_PROPERTIES` | Protected FILE | Existing Maven download/build credentials |
| `LAB_DOCKER_CONFIG` | Protected FILE | Docker auth JSON for private pulls and GHCR publication |
| `LAB_SIGNING_KEY` | Protected FILE | Existing Ed25519 signing key; no implicit key creation |
| `LAB_KAS_ADDRESS`, `LAB_KUBE_CONTEXT`, `LAB_KUBE_NAMESPACE` | Public project/kvm | Reachable agent server and dashboard routing |
| `LAB_KUBE_AGENT_TOKEN` | Project/kvm, protected FILE | Generated external agent credential |
| `LAB_KVM_RUNTIME_CONFIG` | Project/kvm, protected FILE | Complete product-owned runtime manifest with this lab's VM settings |
| `LAB_INSTALL_CONFIG` | Project/target, protected FILE | Existing install transport's private host/SSH configuration |
| `LAB_TRUSTED_PUBLIC_KEY` | Project/target, FILE | Independently provisioned verification key |
| `LAB_TRUSTED_KEY_FINGERPRINT` | Project/target | Expected DER public-key SHA256, prefixed `sha256:` |
| `LAB_DEPLOY_FORMAT` | Project/target | `deb` or `partial`; overrides candidate release default |
| `LAB_PARTIAL_SERVICES` | Project/target | Comma-separated service names from its client-tools policy |
| `LAB_PARTIAL_DATA` | Project/pipeline | Opt-in native migration payload packaging/application |
| `LAB_EXISTING_INSTALLATION` | Project/target | Default true: complete native backup before changes |
| `LAB_PREPARE_HOST` | Project/target | Opt-in native Debian host preparation |
| `LAB_VERIFY_URL` | Project/target | Explicit manual deployment verification endpoint |

Protected inputs are available only on protected refs. Release, production target deploy and
Pages jobs are restricted to the protected default branch. VMware deploy/verify
also accept protected `feature/*` branches; `ci/branches.json` grants push/merge
only to trusted lab Maintainers, so protected FILE credentials remain available. Marking a test optional
does not mean it passed: release notes explicitly say whether it ran successfully.

For CE use project environment scopes (`vmware`, `netcup`, `monolith`, `kvm`)
for target variables. Group environment scopes require a paid tier. Add the same
declarations for the template using its own host, policy, images and signing
inputs; never copy backend image identities into the template.

Example public declaration, with its actual credential file path in ignored `.env`:

```json
{"project":"myscoutee-template","environment":"netcup",
 "key":"LAB_INSTALL_CONFIG","from_env":"TEMPLATE_NETCUP_CONFIG_FILE",
 "from_file":true,"variable_type":"file","protected":true}
```

For non-secret values use `"value":"partial"`, optionally with a `from_env`
override. Secret records omit `value` entirely. Keep public target choices in the
versioned declaration; only customer/account-specific details go in local files.
The provided VMware declarations are examples; setting the referenced inputs
activates their configuration, not deployment.

GitHub configuration is opt-in via `configure.py --provider github --apply`.
It uses `gh variable set`/`gh secret set` with stdin; `gh` encrypts secrets through
GitHub's API. Install/authenticate `gh` outside Git. This does not enable the
presentation workflow or dispatch a build/release.

References: [GitLab group variables](https://docs.gitlab.com/api/group_level_variables/),
[project variables](https://docs.gitlab.com/api/project_level_variables/),
[GitHub Actions variables](https://docs.github.com/en/rest/actions/variables),
[Container Registry](https://docs.gitlab.com/administration/packages/container_registry/).

VMware feature testing uses a project/environment-scoped `LAB_SIGNING_KEY`
from `VMWARE_SIGNING_KEY_FILE`. The lab can reuse an existing local QA signing
identity without assigning it as the group-wide production signing key. Its
transport, verification key and key fingerprint remain local file inputs.
The public partial-update defaults select `nginx,profilemanagement`; no target
is contacted or changed by applying these variables.

## Project-owned declarations and local monolith

`configure.py` combines shared `examples/variables.json` with each checkout's
`config/ci/variables.json`. Public defaults and variable names are committed;
`.env`, private file inputs, signing keys and tokens remain ignored or external.
The backend and template keep separate signing keys and environment inputs.

For local monolith deployment, `LAB_MONOLITH_MODE=compose` reuses the product's
existing `server/docker-compose.e2e.yml`, its seed builder and runtime entrypoints.
`config/ci/monolith.json` owns the project name, ports and service/image mapping.
The adapter starts the exact normal-build application image IDs; only the
existing Mongo seed image is assembled during the manual deployment. Named
volumes and container names are isolated from pre-existing developer stacks and
remain available after qualification. Set `LAB_MONOLITH_MODE=ssh` for the
existing remote signed installer instead. No DEB is built implicitly.

Each project publishes its source tag and tested artifacts to its own
`LAB_GITHUB_REPOSITORY`. A frontend release triggers its backend consumer, but
their releases remain separate. Backend DEBs belong to the backend repository;
the former manual placement of a DEB in the public frontend release is not a
CI publication rule. Repository visibility remains unchanged.

The frontend job builds the production and Pages archives. The application
builder embeds that frontend in its nginx image, alongside the other product
images, and stages those images in the local GitLab registry. The application's
manual release publishes the same images to GHCR and its artifacts to its own
GitHub release. `package:deb` is optional and manual; it packages that existing
build with the candidate's `MYSCOUTEE_VERSION`, without another version bump or
recompilation. UI build metadata, image labels and Debian metadata use this same
candidate version. Publishing a frontend archive alone does not publish an
application container or Debian package.

## Release descriptions

Release jobs publish the version/tag and tested artifacts with an empty
GitLab/GitHub description. Markdown release notes are not a prerequisite, and
no automatic changelog is generated. Maintainers may edit the GitHub description
later. Existing `release_notes` paths in project
metadata remain optional documentation locations; publication does not read them.

## Import separately downloaded infrastructure installers

`scripts/import-infra-assets.py` is an operator helper, separate from pipeline
jobs. It uploads selected local files into the microservices project's Generic
Package Registry and verifies GitLab's stored SHA-256. Existing registry files
are skipped. A selected local file that is missing is downloaded from the pinned
URL in the microservices `infra/versions.json`; a checksum mismatch is an error.
The installed libvirt provider is checked against `.terraform.lock.hcl` before
being archived. Credentials come from an ignored token file or `LAB_RELEASE_TOKEN`.

```sh
python3 scripts/import-infra-assets.py \
  --support ../myscoutee-microservices \
  --project myscoutee/myscoutee-microservices \
  --api-url "$CI_API_V4_URL" \
  --token-file "$LAB_TOKEN_FILE" \
  --ubuntu "$DOWNLOADED_UBUNTU_IMAGE" \
  --terraform "$DOWNLOADED_TERRAFORM_ZIP" \
  --k3s "$DOWNLOADED_K3S_BINARY" \
  --k3s-airgap "$DOWNLOADED_K3S_IMAGE_ARCHIVE" \
  --provider-directory "$INSTALLED_LIBVIRT_PROVIDER_DIRECTORY" \
  --guest-packages "$DOWNLOADED_GUEST_DEB_DIRECTORY"
```

Omit artifact options not being imported. Partial imports are allowed; the helper
only writes the complete-set manifest when all required artifacts are present.
This helper does not provision or start a VM or run a deployment.

The optional manual `infra:start` job first prepares missing registry artifacts,
then reconciles and starts the owned VM. A complete registry set skips upstream
fetches; an unchanged running VM is not restarted. This job is not a required
dependency of manual `deploy:kvm`. Deployment checks registry prerequisites and
the running guest, reporting missing prerequisites without starting infrastructure.
Host-side Terraform/provider/Ubuntu
restoration uses pinned registry bytes. The pinned Ubuntu image already includes
curl, CA certificates and Python. Its missing QEMU guest agent and liburing2 DEBs
are also checksum-pinned in `infra/versions.json`, published by preparation and
restored from the registry. Terraform embeds these small public DEBs in the
cloud-init seed; the guest installs them with `dpkg`, without an APT update or
upstream download. The import helper accepts an existing DEB directory; missing
selected DEBs are downloaded once and uploaded. Existing registry files win.
The installer never downgrades a newer package already installed in the guest.

The Terraform module has an independent version in the microservices
`config/ci/project.json` descriptor (`terraform_module.version: 1.5.0`), mirrored
in the shared catalog. It must not inherit an application's planned release
version. Both applications consume this reusable module with their own runtime
parameters and separate Terraform states. The current module stages guest-agent
packages and k3s inputs without upstream guest downloads.

The small Terraform source module is published automatically by the
`myscoutee-microservices` **build** job on the protected default branch, using
`CI_JOB_TOKEN`. Feature pipelines retain a candidate archive without publishing
the stable module version. Identical existing bytes are reused; changed module
contents require a new descriptor version. This is local registry publication,
independent of the manual GitHub release gate. The optional manual infra job
prepares only the larger installer/provider assets.

### VMware private files

Keep `VMWARE_INSTALL_CONFIG_FILE` under the backend's ignored
`config/packaging/client-tools/` directory. Keep `VMWARE_SSH_PRIVATE_KEY_FILE`,
`VMWARE_SSH_KNOWN_HOSTS_FILE`, `VMWARE_CA_CERT_FILE` and release signing files
under its ignored `.local/private/` directory. The CI `.env` contains pointers;
`configure.py --apply` uploads their contents as scoped FILE variables.
Known hosts must come from an independently trusted record. TLS verification
uses `NODE_EXTRA_CA_CERTS`; it is never disabled. Template inputs use the
`TEMPLATE_VMWARE_` prefix and files inside the template repo. Template VMware
uses HTTP 18083 and HTTPS 18445 by default, declared in its `config/ci/variables.json`.
The install input must not hard-code a local `UserKnownHostsFile`: the shared
transport appends the environment-scoped GitLab FILE path. Put the trusted host
record in `TEMPLATE_VMWARE_SSH_KNOWN_HOSTS_FILE` instead.

Required deployment/verification helpers are versioned in the CI and packaging
repositories. Only generated connection inputs, credentials and execution state
belong in ignored local directories.

Release summary titles use the project's `release_name` in
`config/ci/project.json`, mirrored in the shared catalog: for example
`MyScoutee Template` plus version `1.5.0` becomes `MyScoutee Template 1.5.0`.
This display name affects GitHub/GitLab release headings only; package names,
container repositories and Git tags retain their native identities.
