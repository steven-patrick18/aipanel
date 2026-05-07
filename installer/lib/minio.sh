#!/usr/bin/env bash
# installer/lib/minio.sh — install MinIO single-node, single-drive.
#
# We install the official MinIO .deb directly (not from apt); the package
# ships a systemd unit at /lib/systemd/system/minio.service that reads
# /etc/default/minio for environment.

set -euo pipefail

MINIO_VERSION="${MINIO_VERSION:-RELEASE.2025-01-20T14-49-07Z}"
MINIO_DEB_URL="${MINIO_DEB_URL:-https://dl.min.io/server/minio/release/linux-amd64/archive/minio_${MINIO_VERSION}_amd64.deb}"
MINIO_BIN="/usr/local/bin/minio"
MINIO_DATA_DIR="${MINIO_DATA_DIR:-/var/lib/aipanel/minio}"
MINIO_ENV_FILE="/etc/default/minio"

# minio_install — fetch and install the .deb if not already present.
minio_install() {
    if command_exists minio; then
        log_debug "MinIO already installed at $(command -v minio)"
        return 0
    fi
    log_info "Downloading MinIO ${MINIO_VERSION}"
    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp}"' RETURN
    curl -fsSL "${MINIO_DEB_URL}" -o "${tmp}/minio.deb"
    DEBIAN_FRONTEND=noninteractive dpkg -i "${tmp}/minio.deb"
}

# minio_setup_dirs — data directory owned by the aipanel user. The MinIO
# package creates a 'minio-user' but we'd rather have everything own-able by
# the aipanel system user; the unit file is overridden in minio_configure.
minio_setup_dirs() {
    ensure_dir "${MINIO_DATA_DIR}" "${AIPANEL_USER}:${AIPANEL_GROUP}" "0750"
}

# minio_configure — write the env file and a systemd drop-in that runs
# MinIO as the aipanel user with our data directory.
#
# Root credentials here are placeholders. The real install will inject a
# generated password from the secrets module (next prompt). For now we
# use the documented defaults so a fresh install at least comes up cleanly.
minio_configure() {
    minio_install
    minio_setup_dirs
    log_info "Writing ${MINIO_ENV_FILE}"
    cat > "${MINIO_ENV_FILE}" <<EOF
# Managed by aipanel installer. Real credentials injected in a later step.
MINIO_ROOT_USER="aipanel"
MINIO_ROOT_PASSWORD="aipanel-change-me"
MINIO_VOLUMES="${MINIO_DATA_DIR}"
MINIO_OPTS="--address :9000 --console-address :9001"
EOF
    chmod 0640 "${MINIO_ENV_FILE}"
    chown "root:${AIPANEL_GROUP}" "${MINIO_ENV_FILE}"

    # systemd drop-in to run as aipanel rather than minio-user.
    local drop_dir=/etc/systemd/system/minio.service.d
    install -d -m 0755 "${drop_dir}"
    cat > "${drop_dir}/10-aipanel.conf" <<EOF
[Service]
User=${AIPANEL_USER}
Group=${AIPANEL_GROUP}
EOF
    systemctl daemon-reload

    # The official unit ships disabled; only enable + start once the env
    # file has been customized.
    log_info "Enabling and starting minio.service"
    systemctl enable minio.service
    systemctl restart minio.service
}
