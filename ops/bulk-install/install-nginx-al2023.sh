#!/usr/bin/env bash
set -euo pipefail

NGINX_INSTALL_METHOD="${NGINX_INSTALL_METHOD:-repo}"
NGINX_CHANNEL="${NGINX_CHANNEL:-stable}"
NGINX_RPM_DIR="${NGINX_RPM_DIR:-/tmp/nginx-rpms}"

log() {
  printf '[nginx-install] %s\n' "$*"
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root or with sudo." >&2
    exit 1
  fi
}

write_nginx_repo() {
  log "Writing nginx.org repository file"
  cat >/etc/yum.repos.d/nginx.repo <<'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/amzn/2023/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true

[nginx-mainline]
name=nginx mainline repo
baseurl=http://nginx.org/packages/mainline/amzn/2023/$basearch/
gpgcheck=1
enabled=0
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
EOF

  case "${NGINX_CHANNEL}" in
    stable)
      dnf config-manager --set-enabled nginx-stable >/dev/null 2>&1 || true
      dnf config-manager --set-disabled nginx-mainline >/dev/null 2>&1 || true
      ;;
    mainline)
      dnf config-manager --set-disabled nginx-stable >/dev/null 2>&1 || true
      dnf config-manager --set-enabled nginx-mainline >/dev/null 2>&1 || true
      ;;
    *)
      echo "Unsupported NGINX_CHANNEL: ${NGINX_CHANNEL}" >&2
      exit 1
      ;;
  esac
}

install_with_repo() {
  dnf install -y dnf-plugins-core ca-certificates
  write_nginx_repo
  dnf install -y nginx
}

install_with_local_rpm() {
  log "Installing Nginx from local RPMs: ${NGINX_RPM_DIR}"
  if ! compgen -G "${NGINX_RPM_DIR}/*.rpm" >/dev/null; then
    echo "No RPM files found in ${NGINX_RPM_DIR}" >&2
    exit 1
  fi
  dnf localinstall -y "${NGINX_RPM_DIR}"/*.rpm
}

write_default_site_if_missing() {
  mkdir -p /etc/nginx/conf.d

  if [ -f /etc/nginx/conf.d/default.conf ]; then
    log "/etc/nginx/conf.d/default.conf already exists; leaving it unchanged"
    return
  fi

  log "Writing default /etc/nginx/conf.d/default.conf"
  cat >/etc/nginx/conf.d/default.conf <<'EOF'
server {
    listen 80 default_server;
    server_name _;

    access_log /var/log/nginx/access.log main;
    error_log  /var/log/nginx/error.log warn;

    location / {
        default_type text/plain;
        return 200 "nginx ok\n";
    }
}
EOF
}

enable_service() {
  nginx -t
  systemctl enable --now nginx
  systemctl --no-pager --full status nginx
}

main() {
  require_root

  case "${NGINX_INSTALL_METHOD}" in
    repo)
      install_with_repo
      ;;
    local-rpm)
      install_with_local_rpm
      ;;
    *)
      echo "Unsupported NGINX_INSTALL_METHOD: ${NGINX_INSTALL_METHOD}" >&2
      exit 1
      ;;
  esac

  write_default_site_if_missing
  enable_service
  log "Done"
}

main "$@"
