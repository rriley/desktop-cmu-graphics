#!/usr/bin/env bash
# Build manylinux_2_34 cmu_graphics_helpers wheels for Linux x86_64 and aarch64.
#
# For local builds and testing. CI builds the published Linux wheels natively
# on x86_64 and ARM runners (see .github/actions/linux-helpers-wheel); this
# script makes the same kind of wheels on an x86_64 machine without waiting
# for CI.
#
# Both builds run in one container, on an x86_64 host, without qemu or an ARM
# machine. The container is the official manylinux_2_34_x86_64 image plus:
#   - the x86_64 FreeType, fontconfig, ALSA and libudev headers, for the
#     native x86_64 build;
#   - an aarch64 sysroot of AlmaLinux 9 packages, the distribution the
#     manylinux_2_34_aarch64 image is built on, so the aarch64 wheel is built
#     against glibc 2.34 and the same libraries as CI's. clang and lld compile
#     and link for aarch64 against it.
# For each wheel, maturin checks it against the manylinux_2_34 policy and
# bundles the libraries the policy doesn't allow, just as auditwheel does in
# CI. The x86_64 wheel is also installed and imported as a smoke test; the
# aarch64 one can't be imported on the host.
#
# The wheels work on any Linux with glibc 2.34+ (Debian 12+, Ubuntu 22.04+),
# e.g. dArkOS on the R36S.
#
# Usage:
#   build/helpers/build_linux_wheels.sh [-a ARCH] [-o OUTPUT_DIR] [-r] [-u] [-c]
#
#   -a  x86_64, aarch64, or all (default: all)
#   -o  Directory to write the wheels to (default: wheels-local in the repo root)
#   -r  Rebuild the toolchain image (re-downloads its packages)
#   -u  Update the Rust toolchain to the latest stable
#   -c  Clean build: delete the cached build directory first
#
# Requires Docker on an x86_64 host. The repo is mounted read-only and the
# crate is built from a copy, so the working tree isn't touched apart from the
# output directory.
#
# Only the first run downloads much. Later runs reuse:
#   - a local Docker image with the toolchain, libraries and aarch64 sysroot
#     (cmu-helpers-linux-build), which is rebuilt only when the recipe below
#     changes, or with -r;
#   - Docker volumes with the Rust toolchain and Cargo's downloads, which are
#     updated only with -u;
#   - a Docker volume with Cargo's build directory, so dependencies (and
#     Skia's prebuilt binaries) aren't downloaded and built again. Cargo keeps
#     each architecture's build in its own subdirectory.
# To free the space: docker image rm cmu-helpers-linux-build
# and docker volume rm cmu-helpers-linux-cargo cmu-helpers-linux-rustup
# cmu-helpers-linux-target.
#
# On an aarch64 device (Debian 13):
#   sudo apt install python3-venv
#   python3 -m venv ~/cmu-venv
#   ~/cmu-venv/bin/pip install cmu_graphics_helpers-*-manylinux_2_34_aarch64.whl
#   ~/cmu-venv/bin/pip install cmu-graphics
#
# Note: winit needs X11 or Wayland at runtime. On handhelds that run games on
# bare KMS, start a compositor first (e.g. `cage python3 app.py`).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out_dir="$repo_root/wheels-local"
arches="x86_64 aarch64"
rebuild_image=0
update_rust=0
clean_build=0

usage="Usage: $0 [-a x86_64|aarch64|all] [-o OUTPUT_DIR] [-r] [-u] [-c]"
while getopts "a:o:ruch" opt; do
  case "$opt" in
    a)
      case "$OPTARG" in
        x86_64|aarch64) arches="$OPTARG" ;;
        all) arches="x86_64 aarch64" ;;
        *) echo "$usage" >&2; exit 2 ;;
      esac
      ;;
    o) out_dir="$OPTARG" ;;
    r) rebuild_image=1 ;;
    u) update_rust=1 ;;
    c) clean_build=1 ;;
    h) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "$usage" >&2; exit 2 ;;
  esac
done

if ! command -v docker > /dev/null; then
  echo "error: docker not found" >&2
  exit 1
fi
if [ "$(uname -m)" != x86_64 ]; then
  echo "error: this script needs an x86_64 host (this is $(uname -m))" >&2
  exit 1
fi

mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

# The toolchain image. Changing this rebuilds the image on the next run.
#
# systemd-devel provides libudev, which gilrs (joystick input) links against.
#
# dnf installs the aarch64 packages into /sysroot without running them:
# --forcearch picks the architecture, and noscripts skips their install
# scriptlets, which would need an aarch64 machine to run. The sysroot only
# has to hold headers, libraries and pkg-config files, so nothing is lost.
#
# The clang wrappers target aarch64-redhat-linux-gnu, the triple AlmaLinux's
# gcc uses, so clang finds gcc's startup files and libstdc++ in the sysroot.
dockerfile="$(cat <<'DOCKERFILE'
FROM quay.io/pypa/manylinux_2_34_x86_64:latest
RUN dnf install -y clang lld llvm \
      freetype-devel fontconfig-devel alsa-lib-devel systemd-devel \
 && dnf --forcearch=aarch64 --installroot=/sysroot --releasever=9 \
      --setopt=tsflags=noscripts --setopt=install_weak_deps=False -y install \
      glibc-devel libgcc gcc libstdc++-devel \
      freetype-devel fontconfig-devel alsa-lib-devel systemd-devel \
 && dnf --installroot=/sysroot clean all \
 && dnf clean all
RUN for tool in clang clang++; do \
      printf '#!/bin/sh\nexec %s --target=aarch64-redhat-linux-gnu --sysroot=/sysroot -fuse-ld=lld "$@"\n' \
        "$tool" > "/usr/local/bin/aarch64-linux-gnu-$tool"; \
      chmod +x "/usr/local/bin/aarch64-linux-gnu-$tool"; \
    done
RUN /opt/python/cp311-cp311/bin/python -m venv /venv \
 && /venv/bin/pip install --no-cache-dir 'maturin>=1.12,<2'
DOCKERFILE
)"

image="cmu-helpers-linux-build"
recipe_hash="$(printf '%s\n' "$dockerfile" | sha256sum | cut -c1-16)"
current_hash="$(docker image inspect "$image" \
  --format '{{index .Config.Labels "cmu.recipe-hash"}}' 2> /dev/null || true)"

if [ "$rebuild_image" = 1 ] || [ "$current_hash" != "$recipe_hash" ]; then
  echo "==> Building the toolchain image $image (only needed once)"
  printf '%s\n' "$dockerfile" | docker build --pull \
    --label "cmu.recipe-hash=$recipe_hash" \
    -t "$image" -
else
  echo "==> Using the toolchain image $image"
fi

target_volume="cmu-helpers-linux-target"
if [ "$clean_build" = 1 ]; then
  docker volume rm "$target_volume" > /dev/null 2>&1 || true
fi

echo "Building manylinux_2_34 wheels for: $arches"
echo "Output: $out_dir"

docker run --rm -i \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -e UPDATE_RUST="$update_rust" -e ARCHES="$arches" \
  -v "$repo_root":/src:ro \
  -v "$out_dir":/out \
  -v cmu-helpers-linux-cargo:/root/.cargo \
  -v cmu-helpers-linux-rustup:/root/.rustup \
  -v "$target_volume":/target \
  "$image" bash -s <<'CONTAINER'
set -euo pipefail

echo "==> Setting up Rust"
if [ ! -x /root/.cargo/bin/rustup ]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
fi
. /root/.cargo/env
if [ "$UPDATE_RUST" = 1 ]; then
  rustup update stable --no-self-update
fi
for arch in $ARCHES; do
  if ! rustup target list --installed | grep -qx "$arch-unknown-linux-gnu"; then
    rustup target add "$arch-unknown-linux-gnu"
  fi
done

mkdir -p /build/cmu_graphics_helpers
cp /src/cmu_graphics_helpers/Cargo.toml /src/cmu_graphics_helpers/Cargo.lock \
  /src/cmu_graphics_helpers/pyproject.toml /src/cmu_graphics_helpers/*.png /build/cmu_graphics_helpers/
cp -r /src/cmu_graphics_helpers/src /build/cmu_graphics_helpers/
cd /build/cmu_graphics_helpers

for arch in $ARCHES; do
  echo "==> Building the $arch wheel"
  # A subshell, so the aarch64 cross-compiling settings stay out of the
  # native x86_64 build.
  (
    if [ "$arch" = aarch64 ]; then
      # TARGET_SYSROOT tells maturin where to find the libraries to check and bundle.
      export PKG_CONFIG_ALLOW_CROSS=1 \
        PKG_CONFIG_SYSROOT_DIR=/sysroot \
        PKG_CONFIG_LIBDIR=/sysroot/usr/lib64/pkgconfig:/sysroot/usr/share/pkgconfig \
        TARGET_SYSROOT=/sysroot \
        CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-clang \
        CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-clang \
        CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-clang++ \
        AR_aarch64_unknown_linux_gnu=llvm-ar
    fi
    # /target is a volume, so dependencies built by earlier runs are reused.
    # --compatibility makes maturin fail if the wheel doesn't meet manylinux_2_34.
    /venv/bin/maturin build --release --locked --target "$arch-unknown-linux-gnu" \
      --compatibility manylinux_2_34 --target-dir /target --out "/tmp/wheels/$arch"
  )

  echo "==> Checking the $arch wheel"
  for wheel in "/tmp/wheels/$arch/"*.whl; do
    extract_dir="/tmp/extracted/$arch"
    python3 -m zipfile -e "$wheel" "$extract_dir"
    so="$(find "$extract_dir" -name 'cmu_graphics_helpers*.so')"
    # grep without -q: with pipefail, -q exiting early would fail the pipeline
    case "$arch" in
      x86_64) llvm-readelf -h "$so" | grep 'Machine:.*X86-64' > /dev/null ;;
      aarch64) llvm-readelf -h "$so" | grep 'Machine:.*AArch64' > /dev/null ;;
    esac
    echo "Shared libraries needed:"
    llvm-readelf -d "$so" | grep NEEDED | sed 's/.*\[/  /; s/\]//'
    echo "Bundled libraries:"
    find "$extract_dir" -path '*.libs/*' -printf '  %f\n'
    echo "Newest glibc symbol required: $(llvm-objdump -T "$so" \
      | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
    if [ "$arch" = x86_64 ]; then
      /opt/python/cp311-cp311/bin/python -m pip install --quiet "$wheel"
      (cd / && /opt/python/cp311-cp311/bin/python -c \
        'import cmu_graphics_helpers.joystick, cmu_graphics_helpers.wyvern; print("Import succeeded:", cmu_graphics_helpers.__file__)')
    fi

    cp "$wheel" /out/
    chown "$HOST_UID:$HOST_GID" "/out/$(basename "$wheel")"
    echo "==> Wrote /out/$(basename "$wheel")"
  done
done
CONTAINER

echo "Done: wheels written to $out_dir"
