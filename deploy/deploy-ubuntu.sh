#!/usr/bin/env bash

# In-place deployment for the single Ubuntu homelab host.
# This deliberately trades zero-downtime releases for a much simpler setup.

set -Eeuo pipefail
umask 077

readonly APP_USER="shopping-app"
readonly APP_DIR="/opt/shopping-app"
readonly DATA_DIR="/var/lib/shopping-app"
readonly DATABASE="$DATA_DIR/shopping.sqlite3"
readonly CONFIG_FILE="/etc/shopping-app/app.env"
readonly BACKUP_DIR="/var/backups/shopping-app"
readonly DEPLOY_STATE_FILE="$BACKUP_DIR/deployment-in-progress"
readonly PYTHON_DIR="/opt/uv-python"
readonly UV_BIN="/usr/local/bin/uv"

usage() {
  echo "Usage:"
  echo "  sudo deploy-shopping <40-character-green-main-sha>"
  echo "  sudo deploy-shopping --recover"
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi
if (( EUID != 0 )); then
  echo "Run the deployment with sudo." >&2
  exit 1
fi
if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi
RECOVERY_MODE=0
NEW_SHA=""
if [[ $1 == "--recover" ]]; then
  RECOVERY_MODE=1
elif [[ $1 =~ ^[0-9a-f]{40}$ ]]; then
  NEW_SHA="$1"
else
  usage >&2
  exit 1
fi

app_passwd_entry="$(getent passwd "$APP_USER" || true)"
IFS=: read -r _ _ _ _ _ app_home app_shell <<<"$app_passwd_entry"
if [[ -z $app_passwd_entry || $(id -gn "$APP_USER" 2>/dev/null) != "$APP_USER" ||
  $app_home != "$DATA_DIR" || $app_shell != "/usr/sbin/nologin" ]]; then
  echo "The $APP_USER system identity is missing or has changed." >&2
  exit 1
fi

if [[ ! -d $APP_DIR/.git ]]; then
  echo "$APP_DIR is not installed. Run bootstrap-ubuntu.sh first." >&2
  exit 1
fi
readonly ADMIN_USER="$(stat -c '%U' "$APP_DIR")"
if [[ $ADMIN_USER == "root" || $ADMIN_USER == "$APP_USER" ]]; then
  echo "$APP_DIR must be owned by the normal administrator account." >&2
  exit 1
fi
readonly ADMIN_HOME="$(getent passwd "$ADMIN_USER" | cut -d: -f6)"
if [[ -z $ADMIN_HOME || ! -d $ADMIN_HOME ]]; then
  echo "Cannot determine the administrator home directory." >&2
  exit 1
fi

run_as_admin() {
  runuser -u "$ADMIN_USER" -- env HOME="$ADMIN_HOME" "$@"
}

validate_production_config() {
  [[ $(grep -Ec '^[[:space:]]*SHOPPING_' "$CONFIG_FILE") -eq 5 ]] || return 1
  grep -qxF 'SHOPPING_ENV=production' "$CONFIG_FILE" || return 1
  grep -qxF 'SHOPPING_DATA_DIR=/var/lib/shopping-app' "$CONFIG_FILE" || return 1 # pragma: allowlist secret
  grep -qxF 'SHOPPING_HOST=127.0.0.1' "$CONFIG_FILE" || return 1
  grep -qxF 'SHOPPING_PORT=8000' "$CONFIG_FILE" || return 1
  grep -qxF 'SHOPPING_ALLOW_NON_LOOPBACK=false' "$CONFIG_FILE" || return 1
  if grep -Eq '^SHOPPING_(DATABASE_PATH|RAW_EMAIL_DIR)=' "$CONFIG_FILE"; then
    echo "deploy-shopping supports the standard production paths only." >&2
    return 1
  fi
}

sync_environment() {
  run_as_admin env UV_PYTHON_INSTALL_DIR="$PYTHON_DIR" \
    "$UV_BIN" --directory "$APP_DIR" sync --locked --no-dev &&
    chown -R "$ADMIN_USER:$APP_USER" "$APP_DIR" &&
    chmod -R g+rX,g-w,o-rwx "$APP_DIR" &&
    chmod 2750 "$APP_DIR"
}

install_deploy_helper() {
  local staged_helper
  staged_helper=""
  if ! staged_helper=$(mktemp /usr/local/sbin/.deploy-shopping.XXXXXX); then
    echo "Could not stage the deployment helper." >&2
    return 1
  fi
  if ! install -o root -g root -m 0755 "$APP_DIR/deploy/deploy-ubuntu.sh" "$staged_helper" ||
    ! mv "$staged_helper" /usr/local/sbin/deploy-shopping ||
    ! sync -f /usr/local/sbin; then
    rm -f "$staged_helper"
    echo "Could not atomically install the deployment helper." >&2
    return 1
  fi
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

if (( ! RECOVERY_MODE )); then
  initial_status=""
  if ! initial_status=$(run_as_admin git -C "$APP_DIR" status --porcelain); then
    echo "Cannot inspect $APP_DIR before deployment." >&2
    exit 1
  fi
  if [[ -n $initial_status ]]; then
    echo "$APP_DIR contains local changes; refusing to overwrite them." >&2
    exit 1
  fi
fi
if [[ ! -r $CONFIG_FILE ]] || ! validate_production_config; then
  echo "$CONFIG_FILE does not match the supported production layout." >&2
  exit 1
fi

exec 9>/run/lock/shopping-deploy.lock
if ! flock -n 9; then
  echo "Another deployment is already running." >&2
  exit 1
fi

OLD_SHA=""
DEPLOYED_AT="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH=""
UNIT_BACKUP_DIR=""

rollback() {
  local original_status="${1:-1}"
  local failure_status="$original_status"
  local rollback_ok=1
  if (( failure_status == 0 )); then
    failure_status=1
  fi
  trap - ERR INT TERM
  set +e
  if (( RECOVERY_MODE )); then
    echo "Recovering commit $OLD_SHA and its verified database backup..." >&2
  else
    echo "Deployment failed; restoring commit $OLD_SHA and its database backup..." >&2
  fi

  if ! systemctl stop shopping-migrate.service shopping-web.service; then
    echo "Could not stop every application writer; automatic restore is unsafe." >&2
    rollback_ok=0
  fi
  for writer_unit in shopping-migrate.service shopping-web.service; do
    writer_state="$(
      systemctl show "$writer_unit" --property=ActiveState --value 2>/dev/null || true
    )"
    if [[ $writer_state != "inactive" && $writer_state != "failed" ]]; then
      echo "$writer_unit is still $writer_state; leaving the database untouched." >&2
      rollback_ok=0
    fi
  done

  if (( ! rollback_ok )); then
    echo "The verified backup is retained at: ${BACKUP_PATH:-not yet created}" >&2
    echo "Follow the interrupted-deployment recovery steps before retrying." >&2
    exit "$failure_status"
  fi

  rm -f "$APP_DIR/.git/index.lock"
  if ! run_as_admin git -C "$APP_DIR" checkout --detach --force "$OLD_SHA"; then
    echo "Could not restore the previous source revision." >&2
    rollback_ok=0
  elif ! run_as_admin git -C "$APP_DIR" clean -fd; then
    echo "Could not remove files left by the interrupted checkout." >&2
    rollback_ok=0
  elif ! sync_environment; then
    echo "Could not restore the previous locked environment." >&2
    rollback_ok=0
  fi

  if [[ -n $UNIT_BACKUP_DIR ]]; then
    if [[ ! -d $UNIT_BACKUP_DIR ]]; then
      echo "The previous systemd-unit backup is missing." >&2
      rollback_ok=0
    elif ! install -o root -g root -m 0644 "$UNIT_BACKUP_DIR/shopping-migrate.service" \
      /etc/systemd/system/shopping-migrate.service ||
      ! install -o root -g root -m 0644 "$UNIT_BACKUP_DIR/shopping-web.service" \
        /etc/systemd/system/shopping-web.service ||
      ! cmp --silent "$UNIT_BACKUP_DIR/shopping-migrate.service" \
        /etc/systemd/system/shopping-migrate.service ||
      ! cmp --silent "$UNIT_BACKUP_DIR/shopping-web.service" \
        /etc/systemd/system/shopping-web.service ||
      ! systemctl daemon-reload; then
      echo "Could not restore the previous systemd units." >&2
      rollback_ok=0
    fi
  fi

  if [[ -n $BACKUP_PATH && ! -f $BACKUP_PATH ]]; then
    echo "The verified database backup is missing: $BACKUP_PATH" >&2
    rollback_ok=0
  elif [[ -n $BACKUP_PATH ]]; then
    local database_restore_ok=1
    local failed_dir
    local restore_candidate
    failed_dir=""
    restore_candidate=""
    if ! restore_candidate=$(mktemp "$DATA_DIR/.shopping-restore.XXXXXX"); then
      echo "Could not stage the database restore; the live database was not moved." >&2
      rollback_ok=0
    elif ! cp "$BACKUP_PATH" "$restore_candidate" ||
      ! cmp --silent "$BACKUP_PATH" "$restore_candidate" ||
      ! chown "$APP_USER:$APP_USER" "$restore_candidate" ||
      ! chmod 0600 "$restore_candidate"; then
      echo "Could not verify the staged database restore; the live database was not moved." >&2
      rm -f "$restore_candidate"
      rollback_ok=0
    elif ! failed_dir=$(mktemp -d "$DATA_DIR/.failed-deployment-$DEPLOYED_AT.XXXXXX"); then
      echo "Could not create the diagnostic directory; the live database was not moved." >&2
      rm -f "$restore_candidate"
      rollback_ok=0
    else
      chmod 0700 "$failed_dir"
      for database_file in "$DATABASE" "$DATABASE-wal" "$DATABASE-shm"; do
        if [[ -e $database_file ]] && ! mv "$database_file" "$failed_dir/"; then
          echo "Could not retain $database_file for diagnosis." >&2
          database_restore_ok=0
          rollback_ok=0
          break
        fi
      done
      if (( database_restore_ok )); then
        if ! mv "$restore_candidate" "$DATABASE" ||
          ! cmp --silent "$BACKUP_PATH" "$DATABASE"; then
          echo "Could not install the verified database backup." >&2
          rollback_ok=0
        fi
      fi
    fi
  fi

  restored_sha="$(run_as_admin git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || true)"
  restored_status="$(
    run_as_admin git -C "$APP_DIR" status --porcelain 2>/dev/null || echo inspection-failed
  )"
  if [[ $restored_sha != "$OLD_SHA" || -n $restored_status ]]; then
    echo "The checkout does not match the previous commit after rollback." >&2
    rollback_ok=0
  fi

  if (( ! rollback_ok )); then
    echo "Automatic rollback needs manual recovery. Do not run another deployment." >&2
    echo "The verified backup is retained at: ${BACKUP_PATH:-not yet created}" >&2
    exit "$failure_status"
  fi

  if ! systemctl reset-failed shopping-migrate.service shopping-web.service ||
    ! sync -f "$DATA_DIR" ||
    ! systemctl start shopping-migrate.service ||
    ! systemctl start shopping-web.service; then
    echo "The previous version could not be restarted. Inspect both systemd journals." >&2
    exit "$failure_status"
  fi
  if wait_until_ready; then
    if ! install_deploy_helper; then
      echo "The old application is healthy, but its deployment helper was not restored." >&2
      exit "$failure_status"
    fi
    rm -f "$DEPLOY_STATE_FILE"
    sync -f "$BACKUP_DIR"
    echo "Rollback completed. The failed database files were retained for diagnosis." >&2
    exit "$original_status"
  else
    echo "Rollback also needs attention. Check the systemd journals." >&2
    exit "$failure_status"
  fi
}

if (( RECOVERY_MODE )); then
  if [[ ! -f $DEPLOY_STATE_FILE || -L $DEPLOY_STATE_FILE ||
    $(stat -c '%U:%a' "$DEPLOY_STATE_FILE" 2>/dev/null || true) != "root:600" ]]; then
    echo "No valid interrupted-deployment record was found." >&2
    exit 1
  fi

  state_line_count=0
  while IFS='=' read -r state_key state_value; do
    ((state_line_count += 1))
    case "$state_key" in
      OLD_SHA) OLD_SHA="$state_value" ;;
      BACKUP_PATH) BACKUP_PATH="$state_value" ;;
      UNIT_BACKUP_DIR) UNIT_BACKUP_DIR="$state_value" ;;
      *)
        echo "The interrupted-deployment record contains an unknown field." >&2
        exit 1
        ;;
    esac
  done <"$DEPLOY_STATE_FILE"

  if (( state_line_count != 3 )) || [[ ! $OLD_SHA =~ ^[0-9a-f]{40}$ ]] ||
    [[ ! $BACKUP_PATH =~ ^/var/backups/shopping-app/shopping-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}-[A-Za-z0-9]+\.sqlite3$ ]] ||
    [[ ! $UNIT_BACKUP_DIR =~ ^/var/backups/shopping-app/units-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\.[A-Za-z0-9]+$ ]] ||
    [[ ! -f $BACKUP_PATH || -L $BACKUP_PATH || ! -s $BACKUP_PATH ]] ||
    [[ ! -d $UNIT_BACKUP_DIR || -L $UNIT_BACKUP_DIR ]]; then
    echo "The interrupted-deployment record or its backups are invalid." >&2
    exit 1
  fi

  rollback 0
fi

if [[ -e $DEPLOY_STATE_FILE ]]; then
  echo "A previous deployment was interrupted." >&2
  echo "Run: sudo deploy-shopping --recover" >&2
  exit 1
fi

migration_state="$(
  systemctl show shopping-migrate.service --property=ActiveState --value 2>/dev/null || true
)"
if [[ $migration_state != "inactive" && $migration_state != "failed" ]]; then
  echo "The migration service is $migration_state; wait for it to finish before deploying." >&2
  exit 1
fi

if [[ ! -f $DATABASE || -L $DATABASE || ! -s $DATABASE ]]; then
  echo "$DATABASE is missing, empty, or not a regular database file." >&2
  echo "Refusing to create a replacement during an ongoing deployment." >&2
  exit 1
fi

run_as_admin git -C "$APP_DIR" fetch --prune origin main
run_as_admin git -C "$APP_DIR" cat-file -e "$NEW_SHA^{commit}"
if ! run_as_admin git -C "$APP_DIR" merge-base --is-ancestor "$NEW_SHA" origin/main; then
  echo "The requested commit is not on origin/main." >&2
  exit 1
fi

OLD_SHA="$(run_as_admin git -C "$APP_DIR" rev-parse HEAD)"
if [[ $NEW_SHA == "$OLD_SHA" ]]; then
  if systemctl is-active --quiet shopping-web.service && wait_until_ready; then
    install_deploy_helper
    echo "Commit $NEW_SHA is already deployed and healthy."
    exit 0
  fi
  echo "Commit $NEW_SHA is checked out but unhealthy; attempting an in-place repair." >&2
fi

trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

install -d -o root -g root -m 0700 "$BACKUP_DIR"
unit_backup_candidate=""
if ! unit_backup_candidate=$(
  mktemp -d "$BACKUP_DIR/units-$DEPLOYED_AT-${OLD_SHA:0:12}.XXXXXX"
); then
  echo "Could not create the systemd-unit backup directory." >&2
  false
fi
chmod 0700 "$unit_backup_candidate"
cp /etc/systemd/system/shopping-migrate.service "$unit_backup_candidate/"
cp /etc/systemd/system/shopping-web.service "$unit_backup_candidate/"
chmod 0600 "$unit_backup_candidate"/*
UNIT_BACKUP_DIR="$unit_backup_candidate"

echo "Stopping application writers for an in-place deployment..."
systemctl stop shopping-web.service shopping-migrate.service

migration_state="$(
  systemctl show shopping-migrate.service --property=ActiveState --value 2>/dev/null || true
)"
if [[ $migration_state != "inactive" && $migration_state != "failed" ]]; then
  echo "The migration service is still $migration_state; refusing to back up the database." >&2
  false
fi

temporary_backup=""
if ! temporary_backup=$(mktemp "$DATA_DIR/.shopping-backup.XXXXXX"); then
  echo "Could not create the temporary SQLite backup file." >&2
  false
fi
chown "$APP_USER:$APP_USER" "$temporary_backup"
chmod 0600 "$temporary_backup"
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" \
  "$APP_DIR/deploy/sqlite_backup.py" "$DATABASE" "$temporary_backup"

backup_candidate=""
if ! backup_candidate=$(
  mktemp "$BACKUP_DIR/.pending-$DEPLOYED_AT-${OLD_SHA:0:12}.XXXXXX"
); then
  echo "Could not stage the root-only SQLite backup." >&2
  false
fi
cp "$temporary_backup" "$backup_candidate"
cmp --silent "$temporary_backup" "$backup_candidate"
chown root:root "$backup_candidate"
chmod 0600 "$backup_candidate"
backup_suffix="${backup_candidate##*.}"
backup_final="$BACKUP_DIR/shopping-$DEPLOYED_AT-${OLD_SHA:0:12}-$backup_suffix.sqlite3"
mv "$backup_candidate" "$backup_final"
BACKUP_PATH="$backup_final"

state_candidate=""
if ! state_candidate=$(mktemp "$BACKUP_DIR/.deployment-state.XXXXXX"); then
  echo "Could not record the recoverable deployment state." >&2
  false
fi
{
  printf 'OLD_SHA=%s\n' "$OLD_SHA"
  printf 'BACKUP_PATH=%s\n' "$BACKUP_PATH"
  printf 'UNIT_BACKUP_DIR=%s\n' "$UNIT_BACKUP_DIR"
} >"$state_candidate"
chmod 0600 "$state_candidate"
mv "$state_candidate" "$DEPLOY_STATE_FILE"
sync -f "$BACKUP_DIR"
rm -f "$temporary_backup"

run_as_admin git -C "$APP_DIR" checkout --detach "$NEW_SHA"
sync_environment
post_sync_status=""
if ! post_sync_status=$(run_as_admin git -C "$APP_DIR" status --porcelain); then
  echo "Cannot inspect the repository after installing dependencies." >&2
  false
fi
if [[ -n $post_sync_status ]]; then
  echo "The locked installation changed repository files; refusing deployment." >&2
  false
fi
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/shopping-migrate.service" \
  /etc/systemd/system/shopping-migrate.service
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/shopping-web.service" \
  /etc/systemd/system/shopping-web.service
systemctl daemon-reload
systemctl reset-failed shopping-migrate.service >/dev/null 2>&1 || true
systemctl start shopping-migrate.service
systemctl reset-failed shopping-web.service
systemctl start shopping-web.service

if ! wait_until_ready; then
  echo "The updated application did not become ready." >&2
  false
fi

# Keep the installed helper aligned with the successfully deployed commit.
install_deploy_helper

trap - ERR INT TERM
rm -f "$DEPLOY_STATE_FILE"
sync -f "$BACKUP_DIR"
echo "Deployed $NEW_SHA successfully."
if [[ -n $BACKUP_PATH ]]; then
  echo "Pre-deployment database backup: $BACKUP_PATH"
fi
