#!/bin/sh
# Build a portable Ubuntu 24.04 archive from this repo.
# Usage: packaging/make-linux-tarball.sh [version] [output-dir]
# The default version comes from linux/desktop_recorder/__init__.py.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
default_version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$root/linux/desktop_recorder/__init__.py")
version=${1:-$default_version}
if [ -z "$version" ]; then
  echo "Cannot read __version__ from linux/desktop_recorder/__init__.py." >&2
  exit 1
fi
out_dir=${2:-$root}
name="desktop-recorder-${version}-linux-x86_64"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
dest="$stage/$name"
mkdir -p "$dest/desktop_recorder"
cp "$root"/linux/desktop_recorder/*.py "$dest/desktop_recorder/"
cp "$root/packaging/linux/desktop-recorder" "$dest/desktop-recorder"
cp "$root/packaging/linux/README.txt" "$dest/README.txt"
cp "$root/packaging/linux/desktop-recorder.png" "$dest/desktop-recorder.png"
cat > "$dest/desktop-recorder.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=Desktop Recorder
Comment=Record a region of the screen to MP4
Exec=desktop-recorder
Icon=desktop-recorder
Terminal=false
Categories=AudioVideo;Recorder;
StartupNotify=false
EOF
chmod 755 "$dest/desktop-recorder"
chmod 644 "$dest/README.txt" "$dest/desktop-recorder.png" "$dest/desktop-recorder.desktop" "$dest"/desktop_recorder/*.py
tar -C "$stage" -czf "$out_dir/$name.tar.gz" "$name"
echo "$out_dir/$name.tar.gz"
