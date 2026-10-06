#!/usr/bin/env bash
set -euo pipefail

# Build the installer asset attached to the GitHub release. Dependencies are
# installed by install.sh on the target Linux host, not embedded in this tarball.
version="${1:-v0.2.1}"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
out_dir="${2:-$repo_dir/dist}"
bundle_name="nsogcd-${version}-linux"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

mkdir -p "$stage/$bundle_name/daemon/gc_controller/ble" "$out_dir"
cp "$repo_dir/install.sh" "$repo_dir/README.md" "$repo_dir/CREDITS.md" \
   "$repo_dir/LICENSE" "$stage/$bundle_name/"
cp "$repo_dir/daemon/nsogcd.py" "$repo_dir/daemon/pairing_policy.py" "$stage/$bundle_name/daemon/"
cp "$repo_dir/daemon/gc_controller/__init__.py" "$stage/$bundle_name/daemon/gc_controller/"
cp "$repo_dir/daemon/gc_controller/ble/__init__.py" \
   "$repo_dir/daemon/gc_controller/ble/bumble_backend.py" \
   "$repo_dir/daemon/gc_controller/ble/sw2_protocol.py" \
   "$stage/$bundle_name/daemon/gc_controller/ble/"

tar -C "$stage" -czf "$out_dir/$bundle_name.tar.gz" "$bundle_name"
(cd "$out_dir" && sha256sum "$bundle_name.tar.gz" > "$bundle_name.tar.gz.sha256")
printf '%s\n' "$out_dir/$bundle_name.tar.gz" "$out_dir/$bundle_name.tar.gz.sha256"
