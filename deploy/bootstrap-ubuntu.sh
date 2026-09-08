#!/usr/bin/env bash

# One-time setup for the single Ubuntu homelab host.
# Run from an administrator account with: sudo bash bootstrap-ubuntu.sh <green-sha>

set -Eeuo pipefail
umask 027

readonly APP_USER="shopping-app"
readonly APP_DIR="/opt/shopping-app"
readonly DATA_DIR="/var/lib/shopping-app"
readonly CONFIG_DIR="/etc/shopping-app"
readonly BACKUP_DIR="/var/backups/shopping-app"
readonly PYTHON_DIR="/opt/uv-python"
readonly UV_BIN="/usr/local/bin/uv"
readonly UV_VERSION="0.12.3"
readonly REPO_URL="https://github.com/jichong-tay/jdsg-knowledge-graph-shopping.git"

usage() {
  echo "Usage: sudo bash deploy/bootstrap-ubuntu.sh <40-character-green-main-sha>"
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi
if (( EUID != 0 )); then
  echo "Run this one-time setup with sudo." >&2
  exit 1
fi
if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
  usage >&2
  exit 1
fi
readonly RELEASE_SHA="$1"

readonly ADMIN_USER="${SUDO_USER:-}"
if [[ -z $ADMIN_USER || $ADMIN_USER == "root" ]]; then
  echo "Run with sudo from the normal administrator login, not from a root login." >&2
  exit 1
fi
readonly ADMIN_HOME="$(getent passwd "$ADMIN_USER" | cut -d: -f6)"
if [[ -z $ADMIN_HOME || ! -d $ADMIN_HOME ]]; then
  echo "Cannot determine the administrator home directory." >&2
  exit 1
fi
if [[ -e $DATA_DIR/shopping.sqlite3 || -L $DATA_DIR/shopping.sqlite3 ]] ||
  systemctl is-active --quiet shopping-web.service 2>/dev/null; then
  echo "A database or running installation already exists. Bootstrap never upgrades it." >&2
  echo "Use deploy-shopping, or inspect the partial installation before recovery." >&2
  exit 1
fi

run_as_admin() {
  runuser -u "$ADMIN_USER" -- env HOME="$ADMIN_HOME" "$@"
}

validate_production_config() {
  python3 "$APP_DIR/deploy/validate_config.py" "$CONFIG_DIR/app.env"
}

wait_until_ready() {
  local attempt
  for attempt in {1..20}; do
    if curl --fail --silent --show-error --connect-timeout 1 --max-time 7 \
      http://127.0.0.1:8000/api/health | jq -e '.ready == true' >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "Installing Ubuntu prerequisites..."
apt-get update
apt-get install -y ca-certificates curl git jq sqlite3 util-linux

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
app_passwd_entry="$(getent passwd "$APP_USER")"
IFS=: read -r _ _ _ _ _ app_home app_shell <<<"$app_passwd_entry"
if [[ $(id -gn "$APP_USER") != "$APP_USER" || $app_home != "$DATA_DIR" ||
  $app_shell != "/usr/sbin/nologin" ]]; then
  echo "The existing $APP_USER account does not match the required system identity." >&2
  exit 1
fi

install -d -o "$APP_USER" -g "$APP_USER" -m 0700 "$DATA_DIR"
install -d -o root -g "$APP_USER" -m 0750 "$CONFIG_DIR"
install -d -o root -g root -m 0700 "$BACKUP_DIR"
install -d -o "$ADMIN_USER" -g "$APP_USER" -m 2750 "$APP_DIR"

installed_uv_version=""
if [[ -x $UV_BIN ]]; then
  installed_uv_version="$($UV_BIN --version | awk '{print $2}')"
fi
if [[ $installed_uv_version != "$UV_VERSION" ]]; then
  echo "Installing uv $UV_VERSION..."
  uv_installer=$(mktemp /tmp/shopping-uv-install.XXXXXX)
  trap 'rm -f "${uv_installer:-}"' EXIT
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" -o "$uv_installer"
  env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$uv_installer"
  rm -f "$uv_installer"
  trap - EXIT
fi

install -d -o root -g root -m 0755 "$PYTHON_DIR"
env UV_PYTHON_INSTALL_DIR="$PYTHON_DIR" "$UV_BIN" python install 3.14
chmod -R a+rX "$PYTHON_DIR"

if [[ -d $APP_DIR/.git ]]; then
  checkout_owner="$(stat -c '%U' "$APP_DIR")"
  checkout_origin="$(run_as_admin git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
  checkout_status="$(run_as_admin git -C "$APP_DIR" status --porcelain 2>/dev/null || true)"
  if [[ $checkout_owner != "$ADMIN_USER" || $checkout_origin != "$REPO_URL" ||
    -n $checkout_status ]]; then
    echo "$APP_DIR is not a clean partial bootstrap checkout; refusing to reuse it." >&2
    exit 1
  fi
  echo "Resuming the clean partial bootstrap checkout..."
else
  existing_entry="$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit)"
  if [[ -n $existing_entry ]]; then
    echo "$APP_DIR exists but is not an application checkout or empty directory." >&2
    exit 1
  fi
  run_as_admin git clone "$REPO_URL" "$APP_DIR"
fi

checkout_status=""
if ! checkout_status=$(run_as_admin git -C "$APP_DIR" status --porcelain); then
  echo "Cannot inspect $APP_DIR before setup." >&2
  exit 1
fi
if [[ -n $checkout_status ]]; then
  echo "$APP_DIR contains local changes; refusing to overwrite them." >&2
  exit 1
fi

run_as_admin git -C "$APP_DIR" fetch --prune origin main
run_as_admin git -C "$APP_DIR" cat-file -e "$RELEASE_SHA^{commit}"
if ! run_as_admin git -C "$APP_DIR" merge-base --is-ancestor "$RELEASE_SHA" origin/main; then
  echo "The requested commit is not on origin/main." >&2
  exit 1
fi
run_as_admin git -C "$APP_DIR" checkout --detach "$RELEASE_SHA"

echo "Installing the locked production dependencies..."
run_as_admin env UV_PYTHON_INSTALL_DIR="$PYTHON_DIR" \
  "$UV_BIN" --directory "$APP_DIR" sync --locked --no-dev
chown -R "$ADMIN_USER:$APP_USER" "$APP_DIR"
chmod -R g+rX,g-w,o-rwx "$APP_DIR"
chmod 2750 "$APP_DIR"
post_sync_status=""
if ! post_sync_status=$(run_as_admin git -C "$APP_DIR" status --porcelain); then
  echo "Cannot inspect $APP_DIR after installing dependencies." >&2
  exit 1
fi
if [[ -n $post_sync_status ]]; then
  echo "The locked installation changed repository files; refusing host installation." >&2
  exit 1
fi

if [[ ! -f $CONFIG_DIR/app.env ]]; then
  install -o root -g "$APP_USER" -m 0640 "$APP_DIR/deploy/shopping.env.example" \
    "$CONFIG_DIR/app.env"
fi
if ! validate_production_config; then
  echo "$CONFIG_DIR/app.env does not match the supported production layout." >&2
  exit 1
fi
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/shopping-migrate.service" \
  /etc/systemd/system/shopping-migrate.service
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/shopping-web.service" \
  /etc/systemd/system/shopping-web.service
install -o root -g root -m 0755 "$APP_DIR/deploy/deploy-ubuntu.sh" \
  /usr/local/sbin/deploy-shopping

systemctl daemon-reload
systemctl reset-failed shopping-migrate.service shopping-web.service >/dev/null 2>&1 || true

# Build the first database at a temporary path. A failed first migration therefore
# leaves no authoritative database and bootstrap can be safely retried.
bootstrap_database=""
bootstrap_lock=""
cleanup_bootstrap_database() {
  if [[ -n $bootstrap_database ]]; then
    rm -f -- "$bootstrap_database" "$bootstrap_lock"
  fi
}
trap cleanup_bootstrap_database EXIT
bootstrap_database="$(mktemp "$DATA_DIR/.shopping-bootstrap.XXXXXX")"
bootstrap_lock="$DATA_DIR/.${bootstrap_database##*/}.migrate.lock"
chown "$APP_USER:$APP_USER" "$bootstrap_database"
chmod 0600 "$bootstrap_database"
runuser -u "$APP_USER" -- env -i \
  HOME="$DATA_DIR" \
  PATH=/usr/bin:/bin \
  SHOPPING_ENV=production \
  SHOPPING_DATA_DIR="$DATA_DIR" \
  SHOPPING_HOST=127.0.0.1 \
  SHOPPING_PORT=8000 \
  SHOPPING_ALLOW_NON_LOOPBACK=false \
  "$APP_DIR/.venv/bin/shopping" migrate --database "$bootstrap_database"
mv "$bootstrap_database" "$DATA_DIR/shopping.sqlite3"
bootstrap_database=""
rm -f -- "$bootstrap_lock"
sync -f "$DATA_DIR"
trap - EXIT

# Exercise the installed one-shot unit as a no-op schema verification.
systemctl start shopping-migrate.service
systemctl enable --now shopping-web.service

if ! wait_until_ready; then
  echo "The app did not become ready. Inspect: journalctl -u shopping-web -n 100" >&2
  exit 1
fi

echo
echo "Ubuntu setup is complete at commit $RELEASE_SHA."
echo "The app is listening only on http://127.0.0.1:8000."
echo "To make it available inside your tailnet, run:"
echo "  sudo tailscale serve --bg http://127.0.0.1:8000"
echo "Later deployments use: sudo deploy-shopping <green-main-sha>"
