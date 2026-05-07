#!/usr/bin/env bash
# installer/lib/deps.sh — install OS-level packages via apt.
#
# Idempotent: apt-get install -y is a no-op for already-installed packages.

set -euo pipefail

# Base packages always installed. Service-specific packages (postgresql-15
# from the PGDG repo, nodejs 20 from NodeSource) are handled in their own
# modules and called from here.
DEPS_APT_BASE=(
    build-essential
    ca-certificates
    curl
    gettext-base       # provides envsubst, used by installer/lib/config.sh
    git
    gnupg
    jq
    lsb-release
    nginx
    redis-server
    software-properties-common
    ufw
)

# Python toolchain — Ubuntu 22.04 ships 3.10 in main; 3.11 comes from
# deadsnakes. We add the PPA in deps_setup_python_repo if needed.
DEPS_APT_PYTHON=(
    python3.11
    python3.11-venv
    python3.11-dev
    python3-pip
)

deps_apt_update() {
    log_info "Updating apt package index"
    DEBIAN_FRONTEND=noninteractive apt-get update -y
}

# deps_setup_python_repo — adds the deadsnakes PPA on Ubuntu so we can install
# python3.11. No-op if the PPA is already present.
deps_setup_python_repo() {
    if [[ "${AIPANEL_OS_ID:-}" != "ubuntu" ]]; then
        return 0
    fi
    if grep -rqs '^deb .*deadsnakes' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
        log_debug "deadsnakes PPA already configured"
        return 0
    fi
    log_info "Adding deadsnakes PPA for python3.11"
    DEBIAN_FRONTEND=noninteractive add-apt-repository -y ppa:deadsnakes/ppa
    DEBIAN_FRONTEND=noninteractive apt-get update -y
}

# deps_setup_postgres_repo — PGDG repo for postgresql-15 on Ubuntu 22.04
# (jammy ships pg-14 in main). Idempotent.
deps_setup_postgres_repo() {
    if [[ "${AIPANEL_OS_ID:-}" != "ubuntu" ]]; then
        return 0
    fi
    local list=/etc/apt/sources.list.d/pgdg.list
    local key=/usr/share/keyrings/postgresql-archive-keyring.gpg
    if [[ -f "${list}" ]] && [[ -f "${key}" ]]; then
        log_debug "PGDG repo already configured"
        return 0
    fi
    log_info "Adding PGDG repository for PostgreSQL 15"
    install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o "${key}"
    local codename
    codename="$(lsb_release -cs)"
    cat > "${list}" <<EOF
deb [signed-by=${key}] https://apt.postgresql.org/pub/repos/apt ${codename}-pgdg main
EOF
    DEBIAN_FRONTEND=noninteractive apt-get update -y
}

# deps_setup_nodejs_repo — NodeSource repo for Node 20.x. Idempotent.
deps_setup_nodejs_repo() {
    if [[ "${AIPANEL_OS_ID:-}" != "ubuntu" ]]; then
        return 0
    fi
    local list=/etc/apt/sources.list.d/nodesource.list
    local key=/usr/share/keyrings/nodesource.gpg
    if [[ -f "${list}" ]] && [[ -f "${key}" ]]; then
        log_debug "NodeSource repo already configured"
        return 0
    fi
    log_info "Adding NodeSource repository for Node 20.x"
    install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o "${key}"
    cat > "${list}" <<EOF
deb [signed-by=${key}] https://deb.nodesource.com/node_20.x nodistro main
EOF
    DEBIAN_FRONTEND=noninteractive apt-get update -y
}

# deps_install_base — install the always-needed packages.
deps_install_base() {
    log_info "Installing base packages: ${DEPS_APT_BASE[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${DEPS_APT_BASE[@]}"
}

# deps_install_python — install python3.11 toolchain.
deps_install_python() {
    log_info "Installing Python toolchain: ${DEPS_APT_PYTHON[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${DEPS_APT_PYTHON[@]}"
}

# deps_install_postgres — postgresql-15 server + client.
deps_install_postgres() {
    log_info "Installing PostgreSQL 15 server"
    DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-15 postgresql-client-15
}

# deps_install_nodejs — Node.js 20.x. (npm ships in the same package.)
deps_install_nodejs() {
    log_info "Installing Node.js 20"
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
}

# deps_install_all — orchestrate every step in order. Repo setup first so
# the apt index is up-to-date before any install, then group installs.
deps_install_all() {
    deps_apt_update
    deps_setup_python_repo
    deps_setup_postgres_repo
    deps_setup_nodejs_repo
    deps_install_base
    deps_install_python
    deps_install_postgres
    deps_install_nodejs
}
