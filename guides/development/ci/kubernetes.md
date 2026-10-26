# KVM, Terraform and GitLab Kubernetes (MSC-129)

The existing `myscoutee-microservices` repository owns Terraform/libvirt, VM
lifecycle, k3s bootstrap, image import and Helm application rollout. The CI adapter
calls those owners; it does not introduce another Terraform state or deployment
engine. `infra/terraform/main.tf` and its provider lock remain canonical.

CI KVM operations select `LAB_TERRAFORM_BACKEND=gitlab` and the environment's
`LAB_TERRAFORM_STATE_NAME`. The owner uses GitLab's HTTP backend with POST/DELETE
locking; job credentials stay in environment variables. **Operate → Terraform
states** displays the actual authoritative state, its versions and lock, rather
than a reporting copy. Native operations retain their local backend by default.
An existing local state is rejected when selecting GitLab until an operator
explicitly migrates it; no silent resource adoption or state migration occurs.
Backend/template declarations live in their own `config/ci/variables.json`.

Backend and template share the published `labkvm/libvirt` source module, not a
VM or state. Each owns `config/microservices/deploy/runtime.json` plus its
`config/ci/kvm.json` overrides (VM name, network, memory and ports). Identical
state names such as `kvm` are scoped to different GitLab projects. Module version
is declared by the microservices project, independently of the application version.

## Manual order

The pipeline graph separates `package` (including `package:kvm`), optional
`prepare:deploy` (`infra:start`), `deploy` (including `deploy:agent`),
and `verify` (`verify:kvm`). Image assembly and infrastructure preparation
are independent. Explicit `needs` allow infrastructure preparation after
`dependencies`, without waiting for an application build. The order in which
manual jobs are clicked does not add dependencies between them.

1. Build/package the application candidate, then press `package:kvm` to assemble
   its split-service images and immutable lock. Settings come from the application's
   versioned configuration; `LAB_KVM_RUNTIME_CONFIG` is an optional protected
   FILE input for explicit environment overrides.
2. Optionally press `infra:start`. It checks the Package Registry first; missing
   pinned installers are downloaded and published there. It restores the verified
   inputs and calls the existing `vm.py start` to check ownership, plan/apply
   infrastructure, wait for k3s and save the private kubeconfig. A ready guest
   still goes through Terraform reconciliation so configuration changes are
   applied; an unchanged domain is not restarted. This one optional manual job
   does not require an application build and is not a deployment prerequisite.
3. Press `deploy:kvm`. It checks registry prerequisites and the running guest,
   then `workloads.py up` imports the locked images and performs the existing
   Helm rollout. It does not provision or start infrastructure. Missing
   prerequisites produce an error pointing to the optional infra:start job.
   No public release is required.
4. Optionally press `deploy:agent` after KVM deployment. It uses the owner's
   SSH transport, kubeconfig and pinned Helm launcher to install the GitLab
   agent. It does not start a VM or redeploy application workloads.
5. Open the application's **Operate → Environments → kvm → Kubernetes overview**.
   Agent status is also visible in the CI project's **Operate → Kubernetes
   clusters**. Registration alone does not prove an active cluster connection.

Terraform state, provider data, cloud-init inputs, SSH identity and kubeconfig
stay in the owner's existing external state directory. No VM is enabled at host
boot. No destroy, stop or state migration is added to a CI pipeline. Terraform
plan/apply is deliberately kept inside the owner's guarded manual startup;
there is no second unchecked `terraform apply` command.

## Versioned registration and permissions

`ci/kubernetes.json` declares separate backend/template agents and a checksummed
Helm chart, matching the local GitLab major/minor. `.gitlab/agents/*/config.yaml`
authorizes only the corresponding application and CI project. If the public
GitLab group/project paths change, update these files and `ci/projects.json`
together before committing/importing them; GitLab agent YAML does not expand
shell variables.

`setup.py` runs `kubernetes.py provision`: idempotent agent registration and token
creation through the GitLab API. Tokens are stored with mode 0600 under external
state `kubernetes/` and uploaded as protected, environment-scoped FILE variables.
`deploy:agent` also creates or reconciles the declared `kvm` environment's agent
and Kubernetes namespace, including environments created before the agent
connected. It waits up to three minutes for GitLab to report an active agent
connection, then uses the same GraphQL mutation as the UI to associate the shared
agent. The REST binding endpoint accepts only agents owned by the application
project, so it cannot associate the agent hosted in the shared CI project.
For an already installed agent, apply only this configuration with
`python3 scripts/kubernetes.py dashboard --project myscoutee/myscoutee-backend`.
It prints the environment's dashboard URL;
no agent, namespace or Kubernetes server address needs to be entered in the UI.
Open **Operate → Environments → kvm → Kubernetes overview** in the application
project. The CI project's agent page reports connection status; it is not the
workload dashboard. An installed/Ready agent pod alone does not prove that it can
reach GitLab: the bridge listener below must also be enabled.
Provisioning does not connect to Kubernetes. A missing token file causes explicit token
creation, never silent revocation of an existing token.

Cluster installation passes the token through SSH stdin to a Kubernetes Secret;
it is absent from process arguments, Helm values and Git. Helm uses
`config.secretName`. The agent receives the built-in `view` role in the product
namespace, not cluster-admin. The dashboard therefore observes workloads; native
Helm deployment keeps its existing owner identity. GitLab CE supports the agent
and dashboard; paid user/job impersonation is not required for this lab.

## Guest-to-host networking

The default GitLab binds only to host loopback. `localhost` inside k3s refers to
the guest/pod and cannot reach that listener. After the owner has created the
selected KVM bridge, explicitly enable the optional versioned Compose overlay in
ignored `.env`:

```dotenv
COMPOSE_FILE=compose.yaml:compose.kvm.yaml
GITLAB_KVM_BIND_ADDRESS=192.168.173.1
BACKEND_KAS_ADDRESS=ws://192.168.173.1:8929/-/kubernetes-agent/
```

These are example lab bridge values; select the address from your own runtime
configuration. Reconcile Compose with `bash scripts/lab.sh up`, then apply
variables with `python3 scripts/configure.py --apply`. The overlay adds one
specific bridge listener while retaining loopback. Never use a public interface
for this HTTP lab. For separate backend/template bridges, use a reachable
operator-managed KAS endpoint per cluster and declare both addresses; production
access needs a trusted TLS endpoint. The overlay must be disabled before removing
its bridge. KAS itself is already bundled and enabled in the local GitLab.

The environment dashboard's namespace must match its runtime manifest. Defaults
are versioned per application in `config/ci`; change those together if using a
different lab namespace. There is no automatic discovery of personal hosts.

CI inherits the product's VM memory from `config/microservices/deploy/runtime.json`
(backend 8 GiB, template 6 GiB). The CI lab overlay changes addresses and state
paths, not that allocation. The full backend exhausted a 5-GiB override during
rollout, making both SSH and the Kubernetes API unresponsive. Keep application
environments sequential on this host. An infrastructure update keeps existing
volumes and uses the owner's graceful shutdown before Terraform updates a running
domain; shutdown failure stops the operation rather than forcing power loss.
There is no extra CI RAM allocation, arbitrary 4–10 GiB range, or additional
2-GiB free-memory gate. Terraform uses the product's configured MiB value.

GitHub conversion has matching manual `infra` and `cluster` actions; select the
`kvm` environment. Configure its agent token from the external token file via
`configure.py --provider github`; no secrets are copied into the repository.

References: [agent installation](https://docs.gitlab.com/user/clusters/agent/install/),
[agent API](https://docs.gitlab.com/api/cluster_agents/),
[user access](https://docs.gitlab.com/user/clusters/agent/user_access/),
[Kubernetes dashboard](https://docs.gitlab.com/ci/environments/kubernetes_dashboard/).
