#!/usr/bin/env bash
# Ubuntu 24.04 hosted CI only. Keep network waits away from dpkg installation.
set -euo pipefail

verify_ubuntu_host() {
  . /etc/os-release
  if [[ "$ID" != ubuntu || "${VERSION_CODENAME:-}" != noble ]] ||
      [[ "$(dpkg --print-architecture)" != amd64 ]] ||
      [[ ! -f /usr/share/keyrings/ubuntu-archive-keyring.gpg ]]; then
    echo 'Expected Ubuntu 24.04 amd64 with the installed Ubuntu archive keyring.' >&2
    return 1
  fi
}

install_ubuntu_ffmpeg() (
  if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
    return 0
  fi
  verify_ubuntu_host || return
  local work mirror
  work=$(mktemp -d "${TMPDIR:-/tmp}/ffmpeg-apt.XXXXXX")
  # Bash 3.2 can unwind local variables before an errexit EXIT trap runs.
  # Freeze the safely shell-quoted path now instead of looking it up on exit.
  trap "rm -rf -- $(printf '%q' "$work")" EXIT
  chmod 755 "$work"
  local apt_options=(
    -o "Dir::Etc::sourcelist=$work/ubuntu.sources"
    -o 'Dir::Etc::sourceparts=-'
    -o 'Acquire::Retries=0'
    -o 'Acquire::http::Timeout=15'
    -o 'Acquire::https::Timeout=15'
  )
  # Avoid the runner's mirrorlist choosing the stalled Azure HTTP endpoint.
  # Keep all three official archives from the hosted runner's mirror list.
  # security.ubuntu.com is also a full archive and may remain reachable when
  # the archive/Azure endpoints fail. Every attempt uses the existing signing key.
  # https://github.com/actions/runner-images/blob/ubuntu24/20261101.360/images/ubuntu/scripts/build/configure-apt-sources.sh
  for mirror in https://archive.ubuntu.com/ubuntu \
      https://azure.archive.ubuntu.com/ubuntu https://security.ubuntu.com/ubuntu; do
    printf '%s\n' \
      'Types: deb' "URIs: $mirror" \
      'Suites: noble noble-updates noble-security' \
      'Components: main universe' 'Architectures: amd64' \
      'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' > "$work/ubuntu.sources"
    chmod 644 "$work/ubuntu.sources"
    echo "Fetching signed Ubuntu FFmpeg packages from $mirror"
    # These time limits apply only to index/package downloads, never to dpkg.
    if sudo timeout --kill-after=5s 90s apt-get "${apt_options[@]}" \
        -o 'APT::Update::Error-Mode=any' update -qq &&
        sudo timeout --kill-after=5s 150s apt-get "${apt_options[@]}" \
        install --download-only --no-install-recommends -y ffmpeg; then
      sudo apt-get "${apt_options[@]}" install --no-download --no-install-recommends -y ffmpeg || return
      command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null
      return
    fi
    echo "Download from $mirror failed or exceeded its time budget; trying the next official archive." >&2
  done
  echo 'Could not download signed Ubuntu FFmpeg packages within the bounded attempts.' >&2
  return 1
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  install_ubuntu_ffmpeg
fi
