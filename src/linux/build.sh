#!/bin/bash
# build ORCA's no-MMU Linux image: Buildroot 2026.08 with this directory as the external tree.
# usage: ./build.sh            full build (about an hour); output in build/out/images/
# needs a Linux host with build-essential, cpio, unzip, rsync, bc, wget, python3 and GNU coreutils.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
work=$here/build
# buildroot rejects PATH entries that contain spaces
clean_path=
IFS=: read -r -a entries <<< "$PATH"
for entry in "${entries[@]}"; do
	case "$entry" in *" "*|*"	"*) ;; *) clean_path=${clean_path:+$clean_path:}$entry ;; esac
done
export PATH=$clean_path
version=2026.08
mkdir -p "$work/dl"
if [ ! -d "$work/buildroot-$version" ]; then
	tarball=$work/dl/buildroot-$version.tar.xz
	[ -f "$tarball" ] || curl -fL -o "$tarball" "https://buildroot.org/downloads/buildroot-$version.tar.xz"
	tar -C "$work" -xf "$tarball"
fi
for patch in "$here"/patches/buildroot/*.patch; do
	[ -f "$patch" ] || continue
	stamp=$work/buildroot-$version/.orca-applied-$(basename "$patch")
	[ -f "$stamp" ] && continue
	patch -d "$work/buildroot-$version" -p1 --forward < "$patch"
	touch "$stamp"
done
out=$work/out
if [ ! -f "$out/.config" ]; then
	make -C "$work/buildroot-$version" O="$out" BR2_EXTERNAL="$here" BR2_DL_DIR="$work/dl" orca_rv32_nommu_defconfig
fi
make -C "$work/buildroot-$version" O="$out" BR2_DL_DIR="$work/dl" "$@"
