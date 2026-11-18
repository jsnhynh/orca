#!/bin/bash
# build relay.elf, the console relay that runs on the first Arm core.
# needs an aarch64 bare-metal GCC (AMD's Vitis installs one); `python3 src/run.py build relay`
# finds it, or set AARCH64_GCC. output: out/relay.elf
set -eu
here=$(cd "$(dirname "$0")" && pwd)
gcc=${AARCH64_GCC:-aarch64-none-elf-gcc}
mkdir -p "$here/out"
flags=(-O2 -nostdlib -ffreestanding -mgeneral-regs-only -Wall)
case "$gcc" in
*.exe)
	# a windows compiler needs the sources on a drive
	stage=/mnt/c/Users/Public/orca-relay-build
	mkdir -p "$stage"
	cp "$here"/relay.c "$here"/start.S "$here"/relay.ld "$stage"/
	(cd "$stage" && "$gcc" "${flags[@]}" -T relay.ld start.S relay.c -o relay.elf)
	cp "$stage/relay.elf" "$here/out/relay.elf"
	rm -rf "$stage" ;;
*)
	"$gcc" "${flags[@]}" -T "$here/relay.ld" "$here/start.S" "$here/relay.c" -o "$here/out/relay.elf" ;;
esac
sha256sum "$here/out/relay.elf"
