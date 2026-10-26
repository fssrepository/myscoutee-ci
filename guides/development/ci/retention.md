# Local CI storage retention

`ci/retention.json` owns the policy. The CI project's separate
`maintenance:retention` pipeline runs daily at 03:30 UTC. It is not a stage in
application build, release or deployment pipelines. `scripts/configure.py --apply`
reconciles its schedule and the protected local state-directory variable.

Keep the two newest candidates **per project and existing branch**, plus every candidate
with active jobs, a successful release/deployment, a local publication/deployment
receipt, or a Docker container referring to its working tree. For older owned
candidates, cancel remaining manual actions, delete their Generic Package
Registry candidate package and candidate/KVM image tags (legacy builds only),
and job artifacts, then
remove their native runner working directory. Job logs and Git history remain.
To work on an expired candidate again, create a new pipeline.

Native runners pause accepting new jobs during cleanup and resume afterward;
already-running jobs continue and their candidates are protected. A single
resource group prevents overlapping cleanup runs. No Docker-wide prune is used.
Release versions, Terraform modules/state, installer packages, credentials,
VM disks and persistent application data are outside this deletion scope.

New builds keep candidate files/images in the native runner workspace and Docker
daemon, without uploading registry copies. Registries contain published releases
and infrastructure assets.

New application job artifacts expire after seven days; GitLab's latest-artifact
retention still applies. Registry tag deletion does not immediately reclaim all
unreferenced image layers: registry garbage collection is a separate GitLab
storage operation. The job reports the actual host free-space difference.

For a read-only preview from the configured CI checkout:

```sh
python3 scripts/retention.py
```

To run now, open the CI project's **Build > Pipeline schedules**, then use **Run**
on **MyScoutee candidate retention**. Alternatively, create a web pipeline on
master with `LAB_MAINTENANCE=retention`. That run contains only the maintenance
job. Its state-directory input refers to the existing ignored CI state; no new
credential copy is created.
