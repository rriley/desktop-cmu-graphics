#!/usr/bin/env bash
# Cross-compile the cmu_graphics_helpers wheel for Linux arm64 (aarch64).
#
# For local builds and testing. The published aarch64 wheel is a manylinux
# wheel that CI builds natively on an ARM runner (see
# .github/actions/linux-helpers-wheel); this script is for building one on an
# x86_64 machine without waiting for CI.
#
# The build runs on an x86_64 host inside a Debian container using Debian's
# arm64 multiarch packages and cross compilers -- no ARM machine or qemu
# needed. The wheel links against the container's glibc, FreeType,
# fontconfig, and ALSA, so build with the same Debian release as the device
# you'll install on (default: trixie / Debian 13, e.g. dArkOS on the R36S).
#
# Usage:
#   build/helpers/build_linux_arm64.sh [-d DEBIAN_RELEASE] [-o OUTPUT_DIR]
#
#   -d  Debian release for the build container (default: trixie)
#   -o  Directory to write the wheel to (default: wheels-arm64 in the repo root)
#
# Requires Docker. The repo is mounted read-only and the crate is built from a
# copy, so the working tree isn't touched apart from the output directory.
# Cargo and rustup state are kept in Docker volumes so later runs are faster.
#
# On the device (Debian 13):
#   sudo apt install python3-venv libfreetype6 libfontconfig1 libasound2t64
#   python3 -m venv ~/cmu-venv
#   ~/cmu-venv/bin/pip install cmu_graphics_helpers-*-linux_aarch64.whl
#   ~/cmu-venv/bin/pip install cmu-graphics
#
# Note: winit needs X11 or Wayland at runtime. On handhelds that run games on
# bare KMS, start a compositor first (e.g. `cage python3 app.py`).

set -euo pipefail

debian_release=trixie
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out_dir="$repo_root/wheels-arm64"

while getopts "d:o:h" opt; do
  case "$opt" in
    d) debian_release="$OPTARG" ;;
    o) out_dir="$OPTARG" ;;
    h) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Usage: $0 [-d DEBIAN_RELEASE] [-o OUTPUT_DIR]" >&2; exit 2 ;;
  esac
done

if ! command -v docker > /dev/null; then
  echo "error: docker not found" >&2
  exit 1
fi

mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

echo "Building cmu_graphics_helpers for aarch64 in debian:$debian_release"
echo "Output: $out_dir"

docker run --rm -i \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$repo_root":/src:ro \
  -v "$out_dir":/out \
  -v cmu-helpers-arm64-cargo:/root/.cargo \
  -v cmu-helpers-arm64-rustup:/root/.rustup \
  "debian:$debian_release" bash -s <<'CONTAINER'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> Installing the arm64 cross toolchain and libraries"
dpkg --add-architecture arm64
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates curl build-essential pkg-config python3-venv clang file \
  gcc-aarch64-linux-gnu g++-aarch64-linux-gnu binutils-aarch64-linux-gnu \
  libfreetype-dev:arm64 libfontconfig-dev:arm64 libasound2-dev:arm64 \
  > /dev/null

echo "==> Setting up Rust"
if [ ! -x /root/.cargo/bin/rustup ]; then
  curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
fi
. /root/.cargo/env
rustup update stable --no-self-update
rustup target add aarch64-unknown-linux-gnu

python3 -m venv /venv
/venv/bin/pip install -q 'maturin>=1.12,<2'

export PKG_CONFIG_ALLOW_CROSS=1 \
  PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig \
  CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
  CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc \
  CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++

echo "==> Building the wheel"
cp -r /src/cmu_graphics_helpers /build
rm -rf /build/target
cd /build
mkdir -p /tmp/wheel
/venv/bin/maturin build --release --target aarch64-unknown-linux-gnu \
  --compatibility linux --target-dir /tmp/target --out /tmp/wheel

echo "==> Checking the result"
wheel="$(ls /tmp/wheel/*.whl)"
mkdir -p /tmp/x && cd /tmp/x && python3 -m zipfile -e "$wheel" .
so="$(find . -name '*.so')"
file "$so"
echo "Shared libraries needed:"
aarch64-linux-gnu-readelf -d "$so" | grep NEEDED | sed 's/.*\[/  /; s/\]//'
echo "Newest glibc symbol required: $(aarch64-linux-gnu-objdump -T "$so" \
  | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
echo "glibc in this container:      GLIBC_$(ldd --version | head -1 | grep -o '[0-9.]*$')"

cp "$wheel" /out/
chown "$HOST_UID:$HOST_GID" "/out/$(basename "$wheel")"
echo "==> Wrote /out/$(basename "$wheel")"
CONTAINER

echo "Done: $(ls -t "$out_dir"/*linux_aarch64.whl | head -1)"
