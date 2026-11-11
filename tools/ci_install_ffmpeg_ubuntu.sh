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

install_signed_ubuntu_ffmpeg() (
  local work mirror
  work=$(mktemp -d "${TMPDIR:-/tmp}/ffmpeg-apt.XXXXXX") || return 1
  # Bash 3.2 can unwind local variables before an errexit EXIT trap runs.
  # Freeze the safely shell-quoted path now instead of looking it up on exit.
  trap "rm -rf -- $(printf '%q' "$work")" EXIT
  chmod 755 "$work" || return 1
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
      'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' > "$work/ubuntu.sources" || return 1
    chmod 644 "$work/ubuntu.sources" || return 1
    echo "Fetching signed Ubuntu FFmpeg packages from $mirror"
    # These time limits apply only to index/package downloads, never to dpkg.
    if sudo timeout --kill-after=5s 90s apt-get "${apt_options[@]}" \
        -o 'APT::Update::Error-Mode=any' update -qq &&
        sudo timeout --kill-after=5s 150s apt-get "${apt_options[@]}" \
        install --download-only --no-install-recommends -y ffmpeg; then
      sudo apt-get "${apt_options[@]}" install --no-download --no-install-recommends -y ffmpeg || return 1
      command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || return 1
      return
    fi
    echo "Download from $mirror failed or exceeded its time budget; trying the next official archive." >&2
  done
  echo 'Could not download signed Ubuntu FFmpeg packages within the bounded attempts.' >&2
  # Only exhausted acquisition phases may try the independent package registry.
  # A failed dpkg installation or missing executable returns above instead.
  return 75
)

runner_homebrew_binary() {
  # This is the preinstalled package manager from the official hosted image.
  # Never download an installer or accept an arbitrary executable from PATH.
  printf '%s\n' /home/linuxbrew/.linuxbrew/bin/brew
}

install_runner_homebrew_ffmpeg() (
  if [[ "${GITHUB_ACTIONS:-}" != true || -z "${GITHUB_PATH:-}" ]]; then
    echo 'Homebrew fallback requires the GitHub Actions runner path channel.' >&2
    return 1
  fi
  local brew brew_root prefix bindir variable
  for variable in HOMEBREW_API_DOMAIN HOMEBREW_BOTTLE_DOMAIN HOMEBREW_ARTIFACT_DOMAIN \
      HOMEBREW_BREW_GIT_REMOTE HOMEBREW_CORE_GIT_REMOTE HOMEBREW_CURLRC; do
    if [[ -n "${!variable:-}" ]]; then
      echo "Refusing a Homebrew download-source override: $variable" >&2
      return 1
    fi
  done
  brew=$(runner_homebrew_binary) || return
  if [[ ! -x "$brew" ]]; then
    echo 'The official runner Homebrew installation is unavailable.' >&2
    return 1
  fi
  brew_root="${brew%/bin/brew}"
  if [[ "$brew_root" == "$brew" || "$brew_root" != /* ]]; then
    echo 'Unexpected runner Homebrew executable location.' >&2
    return 1
  fi
  echo 'Ubuntu archive downloads failed; installing FFmpeg from official Homebrew.'
  # Prefer published bottles; Homebrew verifies their checksums. Use the explicit
  # core formula, no sudo, third-party taps, alternate DNS or disabled TLS checks.
  HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 \
    HOMEBREW_CURL_CONNECT_TIMEOUT=15 HOMEBREW_CURL_MAX_TIME=150 \
    HOMEBREW_CURL_RETRIES=1 timeout --kill-after=5s 300s \
    "$brew" install --force-bottle homebrew/core/ffmpeg || return
  prefix=$("$brew" --prefix homebrew/core/ffmpeg) || return
  if [[ "$prefix" != "$brew_root/"* || "$prefix" == *$'\n'* || "$prefix" == *$'\r'* ||
      "$prefix" == */../* || "$prefix" == */.. ]]; then
    echo 'Homebrew did not return a single prefix within its installation.' >&2
    return 1
  fi
  bindir="$prefix/bin"
  if [[ ! -x "$bindir/ffmpeg" || ! -x "$bindir/ffprobe" ]]; then
    echo 'Homebrew installation did not provide both FFmpeg executables.' >&2
    return 1
  fi
  "$bindir/ffmpeg" -version >/dev/null && "$bindir/ffprobe" -version >/dev/null || return
  # The script is a subprocess; exporting PATH here would not reach later steps.
  printf '%s\n' "$bindir" >> "$GITHUB_PATH" || return
)

install_ubuntu_ffmpeg() {
  if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
    return 0
  fi
  verify_ubuntu_host || return
  local status=0
  install_signed_ubuntu_ffmpeg || status=$?
  if [[ "$status" == 75 ]]; then
    install_runner_homebrew_ffmpeg
  else
    return "$status"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  install_ubuntu_ffmpeg
fi
