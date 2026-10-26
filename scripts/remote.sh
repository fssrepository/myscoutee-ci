#!/usr/bin/env bash
# Use the product-owned SSH transport with environment-scoped GitLab FILE inputs.
prepare_remote_transport() {
  : "${LAB_INSTALL_CONFIG:?Environment-scoped install configuration is required}"
  config="$state/install-$target.env"
  install -m 0600 "$LAB_INSTALL_CONFIG" "$config"
  source "$config"
  if [[ -n "${LAB_SSH_PRIVATE_KEY:-}" ]]; then
    chmod 0600 "$LAB_SSH_PRIVATE_KEY"
    printf '\nREMOTE_KEY_FILE=%q\n' "$LAB_SSH_PRIVATE_KEY" >> "$config"
  fi
  if [[ -n "${LAB_SSH_KNOWN_HOSTS:-}" ]]; then
    [[ "$LAB_SSH_KNOWN_HOSTS" != *[[:space:]]* ]] || { echo 'Known-hosts FILE path must not contain whitespace.' >&2; return 1; }
    printf '\nREMOTE_SSH_OPTIONS=%q\n' "${REMOTE_SSH_OPTIONS:-} -o UserKnownHostsFile=$LAB_SSH_KNOWN_HOSTS" >> "$config"
  fi
  if [[ -n "${LAB_FORWARD_PORTS:-}" ]]; then
    printf '\nLOCAL_FORWARD_PORTS=%q\n' "$LAB_FORWARD_PORTS" >> "$config"
  fi
  source "$config"
  source "$packaging/client-tools/remote-transport.sh"
  trap 'remote_transport_cleanup; rm -f -- "$config"' EXIT
  [[ "${REMOTE_HOST_KEY_CHECKING:-}" == yes ]] || { echo 'Set REMOTE_HOST_KEY_CHECKING=yes and provision known_hosts.' >&2; return 1; }
  remote_transport_setup "$config"
}
