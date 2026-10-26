# Project and dependency mapping

`ci/projects.json` is the authoritative DAG. `python3 scripts/catalog.py` prints
its topological release order. A release event carries the exact upstream version,
revision and, for images, a verified registry digest. Only a completed manual
publication emits downstream pipelines; a build or local deploy does not.

| Project type | Native owners / outputs | Build policy |
| --- | --- | --- |
| npm | Existing package scripts; locked npm tarball | No separate compilation |
| Angular library | `build`, `prepare:release`; dist tarball | Automatic |
| Frontend | `build:prod`, `build:github`; prod/docs bundles | Automatic |
| Java base | Existing `publishRelease`, `releaseArchive`; staged Maven set | Automatic |
| Java client | Existing `releaseArchive`, distributions; Maven/CLI archives | Automatic |
| Go image | Native Dockerfile and version label | Automatic |
| Nginx image | Native Dockerfile; existing optional image assertions | Automatic |
| Python DEB | Native manual generator and DEB script | Manual |
| Application | Existing packaging CLI; product image policy, client tools | Automatic |
| Source / legacy | Exact candidate source archive | No compilation claim |

`myscoutee-components` releases trigger both frontends. Each frontend triggers only
its own application. Base, packaging, nginx, MCP, microservices, e2e and qa feed
both applications. Registry and payment-simulator feed backend only. The template
never inherits backend-only services. Skills feed the agent's fixture dependency.

Consumer updates are narrow: npm declaration and lock, the existing base TOML
version, frontend gitlink, exact image default/digest owners, or a pinned
microservices source checkout. Unexpected/missing bindings fail explicitly.
Packaging's backend/template/registry test fixtures are not release dependencies;
they are cloned only for the optional test and cannot create a release cycle.

KVM uses separate assembly images from the same candidate source family, because
split services are not byte-identical to the monolith image. `package:kvm` is a
separate manual job; it reuses the already built frontend output, invokes the
existing microservices assembly/image owners, and locks actual image identities.
Deployment imports that lock and rolls out workloads on the already-running VM.
The optional `infra:start` job owns VM preparation and startup.
Private runtime settings are temporarily materialized for that owner and restored
afterward; they are never included in the candidate commit.

Monolith, VMware and Netcup use the same application image inventory. Partial
selection is validated against each product's own `clientTools.services` mapping.
For example the backend's `registry` client service maps to `registry-demo` image
identity. An absent service, such as an unsupported MCP partial install, fails
instead of inventing an update procedure. Data migrations use the native owner
only when explicitly enabled; user data is not replaced by a generic deploy step.

The release tag commit includes `[skip ci]` to avoid re-running existing GitHub
push-triggered build/release workflows when promoting this already built source.
No workflow driven by a separate GitHub `release` event should rebuild these
artifacts. Audit such triggers before adding new repository release workflows.

Publication spans registries and cannot be atomic across providers. A partial
failure is visible; tags/packages are never silently moved or overwritten.
Inspect the receipts and provider state before recovery. Keep one outstanding
candidate per product when using the existing native version-based image tags.

Application capture resolves separately released Registry/simulator images from
the product Compose configuration without reading runtime secret env files.
It pulls their pinned digests and records the original source plus image ID
under the product package alias. It does not rebuild an upstream service merely
because the application candidate version advanced.

## Release branches and container ownership

A candidate stays in the native runner workspace and Docker daemon until the
manual release. The release pushes the same candidate to `release/v<version>`
and its immutable tag on both providers, publishes the files/images, and merges
through a GitLab MR and a GitHub PR. No direct default-branch push is used.
The requests bind the exact published head SHA; conflicts are not force-resolved.
A completed-publication receipt permits merge retry without republishing.

| Project | Container build owner | Manual release output |
| --- | --- | --- |
| myscoutee-nginx | Own Dockerfile | GHCR `myscoutee-nginx:<version>` |
| myscoutee-mcp | Own Dockerfile | GHCR `myscoutee-mcp:<version>` |
| myscoutee-registry | Own Dockerfile | GHCR `myscoutee-registry:<version>` |
| myscoutee-payment-simulator | Own Dockerfile | GHCR `myscoutee-payment-simulator:<version>` |
| myscoutee-backend | Own packaging image policy | GHCR product images with native version/suffix tags |
| myscoutee-template | Own packaging image policy | GHCR template images with native version/suffix tags |
| Both applications, KVM variant | Manual `package:kvm`, shared microservices tools | GHCR `<project>-kvm/<service>:<version>` if packaged before release |
| Both frontends | Own prod/Pages bundle build | Archives; application nginx image embeds prod output |
| myscoutee-microservices | Reusable domain/Helm/infra sources | Source/module package; application owns built domain images |
| myscoutee-sonarqube | Uses upstream images in Compose | Source configuration archive, no custom container build |
| Other catalog projects | npm, Maven, client DEB or source owner | Native packages, no custom production image |

Image releases also populate the local GitLab Container Registry under
`release/<service>:<version>` and `kvm/<service>:<version>`. Ordinary builds and
manual local deployments do not publish candidate images or generic packages.
Infrastructure installer packages and Terraform modules retain their separate
existing preparation/publication behavior. A registry release promotes the
recorded image IDs and verifies them after push/pull; it never rebuilds an image.
Only the build variants actually prepared before the release are published.
A successful source-only SonarQube release does not prove GHCR image publication.
