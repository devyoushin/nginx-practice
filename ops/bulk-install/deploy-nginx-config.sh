#!/usr/bin/env bash
set -euo pipefail

INVENTORY=""
CONFIG_ROOT=""
USER_NAME="${USER:-ec2-user}"
SSH_OPTS="${SSH_OPTS:-}"

usage() {
  cat <<'EOF'
Usage:
  deploy-nginx-config.sh --inventory <file> --config-root <dir> --user <ssh-user>

Inventory format:
  <host> <group> <node_id>

Config overlay order:
  common/ -> groups/<group>/ -> hosts/<node_id>/

Environment:
  SSH_OPTS   Extra ssh/scp options, for example: -i ~/.ssh/prod.pem
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --inventory)
      INVENTORY="$2"
      shift 2
      ;;
    --config-root)
      CONFIG_ROOT="$2"
      shift 2
      ;;
    --user)
      USER_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "${INVENTORY}" ] || [ -z "${CONFIG_ROOT}" ]; then
  usage
  exit 1
fi

if [ ! -f "${INVENTORY}" ]; then
  echo "Inventory not found: ${INVENTORY}" >&2
  exit 1
fi

if [ ! -d "${CONFIG_ROOT}" ]; then
  echo "Config root not found: ${CONFIG_ROOT}" >&2
  exit 1
fi

copy_overlay() {
  local src="$1"
  local dst="$2"

  if [ -d "${src}" ]; then
    cp -a "${src}/." "${dst}/"
  fi
}

while read -r host group node_id _rest; do
  case "${host:-}" in
    ""|\#*) continue ;;
  esac

  group="${group:-default}"
  node_id="${node_id:-${host}}"

  echo "==> ${host} group=${group} node_id=${node_id}"

  work_dir="$(mktemp -d)"
  trap 'rm -rf "${work_dir}"' EXIT

  mkdir -p "${work_dir}/config"
  copy_overlay "${CONFIG_ROOT}/common" "${work_dir}/config"
  copy_overlay "${CONFIG_ROOT}/groups/${group}" "${work_dir}/config"
  copy_overlay "${CONFIG_ROOT}/hosts/${node_id}" "${work_dir}/config"

  if [ ! -f "${work_dir}/config/nginx.conf" ]; then
    echo "Missing nginx.conf for ${host}" >&2
    exit 1
  fi

  tar -C "${work_dir}/config" -czf "${work_dir}/nginx-config.tgz" .
  scp ${SSH_OPTS} "${work_dir}/nginx-config.tgz" "${USER_NAME}@${host}:/tmp/nginx-config.tgz"
  ssh ${SSH_OPTS} "${USER_NAME}@${host}" 'set -euo pipefail
    sudo rm -rf /tmp/nginx-config-next
    sudo mkdir -p /tmp/nginx-config-next
    sudo tar -xzf /tmp/nginx-config.tgz -C /tmp/nginx-config-next
    sudo nginx -t -p /tmp/nginx-config-next/ -c nginx.conf
    if [ -d /etc/nginx ]; then
      sudo cp -a /etc/nginx "/etc/nginx.backup.$(date +%Y%m%d%H%M%S)"
    fi
    sudo mkdir -p /etc/nginx
    sudo cp -a /tmp/nginx-config-next/. /etc/nginx/
    sudo nginx -t
    sudo systemctl reload-or-restart nginx
  '

  rm -rf "${work_dir}"
  trap - EXIT
done < "${INVENTORY}"
