#!/usr/bin/env bash
# Build cmu_graphics_helpers and cmu_graphics_joystick for the host architecture
# in manylinux_2_34.
# Requires Docker. Run from anywhere; optionally pass an output directory.
# Rust downloads and compiled dependencies are cached in a Docker volume.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
arch="$(uname -m)"
case "$arch" in
  x86_64|aarch64) ;;
  *) echo "Unsupported host architecture: $arch" >&2; exit 1 ;;
esac
out_dir="${1:-$repo_root/wheels-manylinux}"
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"
docker run --rm -i \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$repo_root":/src:ro -v "$out_dir":/out \
  -v "cmu-helpers-manylinux-2-34-${arch//_/-}":/cache \
  "quay.io/pypa/manylinux_2_34_${arch}:latest" bash -s <<'CONTAINER'
set -euo pipefail
# gilrs (joystick input) links against libudev, provided by systemd-devel.
dnf install -y freetype-devel fontconfig-devel alsa-lib-devel systemd-devel
export CARGO_HOME=/cache/cargo RUSTUP_HOME=/cache/rustup
export PATH="$CARGO_HOME/bin:/opt/python/cp311-cp311/bin:$PATH"
if [ ! -x "$CARGO_HOME/bin/rustup" ]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
fi
python -m pip install 'maturin>=1.12,<2'
mkdir -p /build/.cargo
cp /src/.cargo/config.toml /build/.cargo/
for package in cmu_graphics_helpers cmu_graphics_joystick; do
  echo "==> Building $package"
  mkdir -p "/build/$package"
  cp "/src/$package/Cargo.toml" "/src/$package/Cargo.lock" "/src/$package/pyproject.toml" "/build/$package/"
  cp -r "/src/$package/src" "/build/$package/"
  if [ "$package" = cmu_graphics_helpers ]; then
    cp /src/cmu_graphics_helpers/*.png "/build/$package/"
  fi
  cd "/build/$package"
  maturin build --release --locked --compatibility manylinux_2_34 --target-dir /cache/target --out "/tmp/wheels/$package"
  for wheel in "/tmp/wheels/$package/"*.whl; do
    auditwheel show "$wheel"
    python -m pip install "$wheel"
    python -c 'import importlib, sys; module = importlib.import_module(sys.argv[1]); print("Import succeeded:", module.__file__)' "$package"
    cp "$wheel" /out/
    chown "$HOST_UID:$HOST_GID" "/out/$(basename "$wheel")"
  done
done
CONTAINER
