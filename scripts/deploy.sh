#!/usr/bin/env bash
# Executed only by an explicitly pressed environment deployment job.
set -euo pipefail
umask 077
state="$(realpath -- "${1:?Pipeline state directory required}")"
root="$(dirname -- "$state")"
cd "$root"
target="${LAB_TARGET:?Select kvm, vmware, monolith or netcup}"
case "$target" in kvm|vmware|monolith|netcup) ;; *) exit 2;; esac
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$state/plan.json")"
delivery="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["delivery"])' "$state/plan.json")"
delivery="${LAB_DEPLOY_FORMAT:-$delivery}"
packaging="$root/config/packaging/node_modules/@fssrepository/myscoutee-packaging"
package="$(jq -er .packageName config/packaging/release-project.json)"
dist="$state/dist"
if [[ "$target" == kvm ]]; then
  : "${LAB_MICROSERVICES_SOURCE:?Select the pinned microservices checkout}"
  [[ -f "$dist/kvm-images.lock.json" ]] || { echo 'This candidate has no KVM image set; run its manual build first.' >&2; exit 1; }
  cmp "$dist/kvm-images.lock.json" config/microservices/deploy/images.lock.json
  # Check actual readiness; optional infrastructure jobs need not have run in
  # this pipeline. Never start/provision a guest from application deployment.
  python3 "$LAB_MICROSERVICES_SOURCE/tools/vm.py" ready
  python3 "$LAB_MICROSERVICES_SOURCE/tools/workloads.py" up
  python3 "$LAB_MICROSERVICES_SOURCE/tools/workloads.py" status
  python3 "$LAB_MICROSERVICES_SOURCE/tools/workloads.py" forward
else
  : "${LAB_TRUSTED_PUBLIC_KEY:?Environment-scoped trusted public key FILE required}"
  : "${LAB_TRUSTED_KEY_FINGERPRINT:?Pin the independent public key fingerprint}"
  source "$(dirname -- "${BASH_SOURCE[0]}")/remote.sh"
  prepare_remote_transport
  # The product installer owns config parsing and transport. Append immutable
  # release verification inputs; no credentials appear in command arguments.
  printf '\nRELEASE_PUBLIC_KEY_PATH=%q\nRELEASE_PUBLIC_KEY_FINGERPRINT=%q\nALLOW_UNSIGNED_LOCAL_PACKAGE=false\n' \
    "$LAB_TRUSTED_PUBLIC_KEY" "$LAB_TRUSTED_KEY_FINGERPRINT" >> "$config"
  source "$config"
  if [[ "${LAB_PREPARE_HOST:-false}" == true ]]; then
    remote_transport_scp "$packaging/client-tools/prepare-debian13-minimal.sh" /tmp/myscoutee-prepare-host.sh
    remote_transport_run_root bash /tmp/myscoutee-prepare-host.sh
  fi
  if [[ "${LAB_EXISTING_INSTALLATION:-true}" == true ]]; then
    remote_transport_run_root env MYSCOUTEE_BACKUP_REQUIRE_COMPLETE=true \
      "/opt/$package/packaging/scripts/backup-production.sh"
  elif [[ "$delivery" != deb ]]; then
    echo 'A fresh host requires a major/full DEB installation before partial updates.' >&2
    exit 1
  fi
  if [[ "$delivery" == deb ]]; then
    printf 'RELEASE_MANIFEST_PATH=%q\n' "$dist/$package-release_$version.json" >> "$config"
    CONFIG_FILE="$config" npm --prefix config/packaging run client -- install "$dist/${package}_${version}_amd64.deb"
  else
    # Partial rollout retains the installed Debian version. Verify the sealed
    # candidate before sending it to the authenticated target.
    actual="sha256:$(openssl pkey -pubin -in "$LAB_TRUSTED_PUBLIC_KEY" -outform DER | sha256sum | cut -d ' ' -f1)"
    [[ "$actual" == "$LAB_TRUSTED_KEY_FINGERPRINT" ]] || { echo 'Public key fingerprint mismatch.' >&2; exit 1; }
    openssl pkeyutl -verify -pubin -inkey "$LAB_TRUSTED_PUBLIC_KEY" -rawin \
      -in "$dist/partial-SHA256SUMS" -sigfile "$dist/partial-SHA256SUMS.sig"
    (cd "$dist" && sha256sum --check --strict partial-SHA256SUMS)
    remote="/tmp/$package-partial-$version-${CI_PIPELINE_ID:?}"
    [[ "$remote" =~ ^/tmp/[a-zA-Z0-9._-]+$ ]] || exit 1
    remote_transport_run mkdir -m 700 "$remote"
    for file in "$dist/$package-client-tools_$version.tar.gz" "$dist/partial-images.tar"; do
      remote_transport_scp "$file" "$remote/$(basename -- "$file")"
    done
    remote_transport_run tar -xzf "$remote/$package-client-tools_$version.tar.gz" -C "$remote"
    remote_transport_run_root docker load -i "$remote/partial-images.tar"
    remote_transport_run rm -- "$remote/partial-images.tar"
    if [[ "${LAB_PARTIAL_DATA:-false}" == true ]]; then
      # Product data migrations are separately supplied by the existing owner.
      remote_transport_scp "$dist/partial-data.tar.gz" "$remote/partial-data.tar.gz"
      remote_transport_run tar -xzf "$remote/partial-data.tar.gz" -C "$remote"
      remote_transport_run_root "/opt/$package/packaging/scripts/myscoutee-compose.sh" stop profilemanagement
      remote_transport_run_root bash "$remote/partial-data/apply-partial-release-data.sh" "$remote/partial-data"
    fi
    IFS=',' read -r -a services <<< "${LAB_PARTIAL_SERVICES:?Select product-supported services}"
    for service in "${services[@]}"; do
      reference="$(jq -er --arg service "$service" '.images[] | select(.service == $service) | .reference' "$dist/partial-images.json")"
      # Docker's classic and containerd stores can expose different IDs for the
      # same exported image. Resolve the tag restored from the verified archive.
      image="$(remote_transport_run_root docker image inspect --format '{{.Id}}' "$reference")"
      remote_transport_run_root env "MYSCOUTEE_TEMP_IMAGE_STOPPED_API=${LAB_PARTIAL_DATA:-false}" \
        bash "$remote/install-temporary-image.sh" install-local "$service" "$image"
    done
    remote_transport_run_root "/opt/$package/packaging/scripts/qualify-deployment.sh" check --leave-running-on-failure
    remote_transport_run rm -r -- "$remote"
  fi
fi
python3 - "$state" "$target" "$version" <<'PY'
import json,pathlib,sys
state=pathlib.Path(sys.argv[1])
receipt={'target':sys.argv[2], 'version':sys.argv[3], 'installed':True}
if receipt['target']=='kvm':
    runtime=json.loads((state.parent/'config/microservices/deploy/runtime.json').read_text())
    receipt['url']='http://127.0.0.1:'+str(runtime['localPort'])
(state/('deployed-'+sys.argv[2]+'.json')).write_text(json.dumps(receipt)+'\n')
PY
