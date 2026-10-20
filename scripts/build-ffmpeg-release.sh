#!/usr/bin/env bash
# Build an unmodified, static LGPL FFmpeg for Hisser's subprocess interface.
# Run through MSYS2 bash with an initialized x64 MSVC developer environment.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  printf 'Usage: %s SOURCE_DIRECTORY BUILD_DIRECTORY OUTPUT_DIRECTORY\n' "$0" >&2
  exit 2
fi

# The hosted runner also has native MinGW make and Git Bash on PATH. Use one
# MSYS2 POSIX environment, while preserving MSVC's linker ahead of coreutils.
msvc_directory=$(/usr/bin/dirname "$(command -v cl.exe)")
export PATH="$msvc_directory:/usr/bin:$PATH"
source_directory=$(/usr/bin/cygpath -u "$1")
build_directory=$(/usr/bin/cygpath -u "$2")
output_directory=$(/usr/bin/cygpath -u "$3")
mkdir -p "$build_directory" "$output_directory"
cd "$build_directory"

printf 'Resolved build tools:\n'
command -v cl.exe link.exe bash make
/usr/bin/make --version
/usr/bin/bash --version

configure_options=(
  --toolchain=msvc
  --target-os=win64
  --arch=x86_64
  --disable-autodetect
  --disable-network
  --disable-gpl
  --disable-nonfree
  --disable-ffplay
  --disable-doc
  --disable-debug
  --disable-x86asm
  --enable-w32threads
  --enable-static
  --disable-shared
)

/usr/bin/bash "$source_directory/configure" "${configure_options[@]}"
/usr/bin/make SHELL=/usr/bin/bash -j "${NUMBER_OF_PROCESSORS:-2}"
cp ffmpeg.exe ffprobe.exe "$output_directory/"

# Keep the exact generated configuration, source license and build instructions.
cp config.h config_components.h ffbuild/config.mak "$output_directory/"
cp "$source_directory/COPYING.LGPLv2.1" "$output_directory/"
"$output_directory/ffmpeg.exe" -version > "$output_directory/ffmpeg-version.txt" 2>&1
"$output_directory/ffmpeg.exe" -L > "$output_directory/ffmpeg-license.txt" 2>&1
"$output_directory/ffmpeg.exe" -buildconf > "$output_directory/ffmpeg-buildconf.txt" 2>&1
"$output_directory/ffprobe.exe" -version > "$output_directory/ffprobe-version.txt" 2>&1

if grep -q -- '--enable-gpl\|--enable-nonfree' "$output_directory/ffmpeg-buildconf.txt"; then
  printf 'Unexpected GPL or nonfree configuration; do not distribute this build.\n' >&2
  exit 1
fi
grep -q 'Lesser General Public License' "$output_directory/ffmpeg-license.txt"
