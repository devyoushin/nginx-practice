#!/usr/bin/env bash
set -euo pipefail

INVENTORY=""
USER_NAME="${USER:-ec2-user}"
SCRIPT=""
SSH_OPTS="${SSH_OPTS:-}"

usage() {
  cat <<'EOF'
Usage:
  ssh-fanout.sh --inventory <file> --user <ssh-user> --script <script>

Environment:
  SSH_OPTS   Extra ssh options, for example: -i ~/.ssh/prod.pem
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --inventory)
      INVENTORY="$2"
      shift 2
      ;;
    --user)
      USER_NAME="$2"
      shift 2
      ;;
    --script)
      SCRIPT="$2"
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

if [ -z "${INVENTORY}" ] || [ -z "${SCRIPT}" ]; then
  usage
  exit 1
fi

if [ ! -f "${INVENTORY}" ]; then
  echo "Inventory not found: ${INVENTORY}" >&2
  exit 1
fi

if [ ! -f "${SCRIPT}" ]; then
  echo "Script not found: ${SCRIPT}" >&2
  exit 1
fi

while IFS= read -r host; do
  case "${host}" in
    ""|\#*) continue ;;
  esac

  echo "==> ${host}"
  scp ${SSH_OPTS} "${SCRIPT}" "${USER_NAME}@${host}:/tmp/$(basename "${SCRIPT}")"
  ssh ${SSH_OPTS} "${USER_NAME}@${host}" "sudo bash /tmp/$(basename "${SCRIPT}")"
done < "${INVENTORY}"
