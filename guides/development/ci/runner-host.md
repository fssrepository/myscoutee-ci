# Dedicated native runner account

The native `lab-build` runner, Terraform and KVM operations run as one system
account, `myscoutee-ci`. The operator keeps their personal account. No separate
account is introduced for each infrastructure step.

## One-time host setup

First provision the local GitLab and its native runner registration using the
existing setup scripts. Then prepare the ignored local host configuration:

```sh
mkdir -p .local/private
cp examples/runner-host.env.example .local/private/runner-host.env
chmod 600 .local/private/runner-host.env
# Edit the operator name, existing tool installations and application state paths.
python3 scripts/runner-host.py
sudo python3 scripts/runner-host.py --apply
```

Only the example is committed. `.local/` is excluded by `.gitignore`.
The parser accepts literal dotenv values and JSON path lists, never shell
expansion. Local paths remain in the correct repository; no credential values
belong in the example. Existing GitLab FILE variables provide build credentials.

The helper creates a locked system account with no login shell, retains the
existing group runner registration and four-job concurrency, pauses new jobs,
and refuses to migrate while any native job is running. It stops the previous
personal user service before starting the dedicated system service. Repeating
the helper reconciles only its own account and recorded service; an unrelated
existing account or modified service is preserved with an error.

Only the declared runner home, runner state and application KVM state directories
change ownership and remain private to the execution account. Their default
ACLs are removed so new secrets obey `umask 077`; directories use mode 0700 and
private keys use mode 0600. Administrative inspection uses `sudo -u myscoutee-ci`
rather than broadening those permissions. The runner receives
traversal permission on parent directories and read/execute permission on the
listed tool installations, not access to the operator's whole home. Candidate
symlinks are not followed during migration. Existing VM disks and Terraform
resources are neither recreated nor started by this helper.

## Permissions and operation

The account joins the existing `docker` and `libvirt` groups needed by these
trusted builds. Docker daemon access is effectively host-administrator access;
a separate account does not sandbox untrusted pipeline code. Keep this runner
limited to the trusted lab repositories.

The microservices host owner installs the exact sudoers command for starting
`virtlogd.socket`, `virtlockd.socket` and `libvirtd.socket`. Reassigning that
recorded policy removes its previous personal-user grant. No general sudo rule
or sudo-group membership is added. Jobs use `sudo -n`; missing authorization
fails immediately rather than prompting or waiting.

The service is started explicitly, not enabled at host boot:

```sh
systemctl status myscoutee-ci-build-runner.service
sudo systemctl start myscoutee-ci-build-runner.service
sudo systemctl stop myscoutee-ci-build-runner.service
```

Administrative setup/start can ask for the operator's password. CI jobs do not.
After editing concurrency or tool paths, run the helper again with `--apply`
when the runner is idle. If migration fails, it leaves the runner paused for
review; correct the error and repeat the helper. The recorded original pause
state is restored only after the dedicated service starts successfully.

Terraform owns VM resources. Creating a host account and granting the initial
libvirt access must happen before Terraform can use that host, so this bootstrap
belongs in the versioned host helper.
