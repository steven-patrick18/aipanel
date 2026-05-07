#!/usr/bin/env bash
# installer/lib/pjsip.sh — build PJSIP 2.14 from source + Python (pjsua2) bindings.
#
# Idempotent. The C library build is gated on a marker file because it takes
# ~5 minutes; rebuilding the SWIG-generated Python module into the SIP venv
# is cheap and always re-run (so a wiped venv recovers cleanly).
#
# Public entrypoint: pjsip_install <venv-path>

set -euo pipefail

PJSIP_VERSION="${PJSIP_VERSION:-2.14}"
PJSIP_SRC_DIR="${PJSIP_SRC_DIR:-/opt/aipanel/build/pjproject}"
PJSIP_GIT_URL="${PJSIP_GIT_URL:-https://github.com/pjsip/pjproject.git}"
PJSIP_PREFIX="${PJSIP_PREFIX:-/usr/local}"
PJSIP_MARKER="${PJSIP_PREFIX}/share/aipanel/pjsip-${PJSIP_VERSION}.installed"

# Build deps that are not in DEPS_APT_BASE.
PJSIP_BUILD_DEPS=(
    swig
    pkg-config
    libasound2-dev
    libssl-dev
    libsrtp2-dev
    libopus-dev
    libspeex-dev
    libspeexdsp-dev
    uuid-dev
    python3.11-dev
)

# pjsip_c_library_present — true when the shared lib is installed and the
# version marker matches. Both checks needed: the marker alone could survive
# an uninstall.
pjsip_c_library_present() {
    [[ -f "${PJSIP_MARKER}" ]] || return 1
    ldconfig -p 2>/dev/null | grep -q 'libpjsua2\.so' || return 1
    return 0
}

pjsip_install_build_deps() {
    log_info "Installing PJSIP build dependencies"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${PJSIP_BUILD_DEPS[@]}"
}

pjsip_clone_or_update() {
    install -d -m 0755 "$(dirname "${PJSIP_SRC_DIR}")"
    if [[ -d "${PJSIP_SRC_DIR}/.git" ]]; then
        log_info "Updating PJSIP checkout at ${PJSIP_SRC_DIR}"
        git -C "${PJSIP_SRC_DIR}" fetch --tags --depth=1 origin "${PJSIP_VERSION}"
        git -C "${PJSIP_SRC_DIR}" checkout -f "${PJSIP_VERSION}"
    else
        log_info "Cloning pjproject ${PJSIP_VERSION}"
        git clone --depth 1 --branch "${PJSIP_VERSION}" \
            "${PJSIP_GIT_URL}" "${PJSIP_SRC_DIR}"
    fi
}

pjsip_build_c_library() {
    log_info "Configuring + building PJSIP C library (this takes ~5 minutes)"
    (
        cd "${PJSIP_SRC_DIR}"
        # -fPIC is required because the SWIG bindings link the .a archives
        # into a shared module. --enable-shared also produces .so files used
        # by the bindings at runtime.
        ./configure \
            --prefix="${PJSIP_PREFIX}" \
            --enable-shared \
            --disable-video \
            --disable-libwebrtc \
            CFLAGS="-fPIC -O2 -DNDEBUG"
        make dep
        make
        make install
    )
    ldconfig

    install -d -m 0755 "$(dirname "${PJSIP_MARKER}")"
    : > "${PJSIP_MARKER}"
    log_info "PJSIP C library installed to ${PJSIP_PREFIX}"
}

# pjsip_build_python_bindings <venv-path>
#   Rebuilds the SWIG-generated pjsua2 Python module against the venv's
#   Python interpreter, then installs it into the venv.
pjsip_build_python_bindings() {
    local venv="${1:?usage: pjsip_build_python_bindings <venv>}"
    [[ -x "${venv}/bin/python" ]] || die "Venv missing: ${venv}"
    [[ -d "${PJSIP_SRC_DIR}/pjsip-apps/src/swig/python" ]] \
        || die "PJSIP source not found at ${PJSIP_SRC_DIR}"

    log_info "Building pjsua2 Python bindings into ${venv}"

    # The SWIG Makefile reads PYTHON_PATH and runs setup.py against it.
    # Forcing --no-build-isolation avoids pip building a separate env that
    # would re-link against a different Python.
    (
        cd "${PJSIP_SRC_DIR}/pjsip-apps/src/swig/python"
        # Clean any stale artifacts from a prior build against a different venv.
        make clean >/dev/null 2>&1 || true
        # The Makefile's `python` target generates the bindings; then setup.py
        # builds + installs into our venv.
        PYTHON="${venv}/bin/python" make python
        "${venv}/bin/pip" install --no-build-isolation --upgrade .
    )

    # Smoke test: the import itself does some dynamic linker work.
    if ! "${venv}/bin/python" -c 'import pjsua2; print(pjsua2.Endpoint)' >/dev/null 2>&1; then
        die "pjsua2 import failed after install. Check ldconfig and venv Python version."
    fi
    log_info "pjsua2 import OK in ${venv}"
}

# pjsip_install <venv-path>
#   Public entrypoint. Installs build deps if needed, builds the C library
#   on first run, always rebuilds the Python bindings into the given venv.
pjsip_install() {
    local venv="${1:?usage: pjsip_install <venv-path>}"

    if pjsip_c_library_present; then
        log_info "PJSIP ${PJSIP_VERSION} already installed; skipping C build"
    else
        pjsip_install_build_deps
        pjsip_clone_or_update
        pjsip_build_c_library
    fi

    # Python bindings always rebuilt: cheap, and required if the venv was
    # destroyed or the venv's Python was upgraded.
    [[ -d "${PJSIP_SRC_DIR}" ]] || pjsip_clone_or_update
    pjsip_install_build_deps   # swig/python-dev needed; idempotent
    pjsip_build_python_bindings "${venv}"
}
