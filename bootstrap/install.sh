#!/bin/bash
# Freo Bootstrap Installer 0.1.0. Delivery only; never builds or upgrades Freo.
# Keep execution inside main: an interrupted curl must not execute a partial body.
freo_bootstrap_main() {
    set -euo pipefail
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    unset CDPATH ENV BASH_ENV
    umask 077
    case "${1:-}" in
        --bootstrap-version) printf '%s\n' 'Freo Bootstrap Installer 0.1.0'; return ;;
        --help|-h)
            printf '%s\n' 'Freo Bootstrap Installer 0.1.0' \
                'Usage: bash install.sh [--domain HOST] [--https --email ADDRESS]' \
                '                       [--version VERSION] [--yes]' \
                'Fresh Ubuntu 24.04 x86_64 only. --yes requires --domain.' \
                'HTTPS requires an explicit DNS domain and email.'
            return ;;
    esac
    if (( EUID != 0 )); then
        printf '%s\n' 'Run with sudo or as root.' >&2; return 1
    fi
    if ! grep -qx 'ID=ubuntu' /etc/os-release ||
       ! grep -Eq '^VERSION_ID="?24\.04"?$' /etc/os-release; then
        printf '%s\n' 'Only Ubuntu 24.04 is supported.' >&2; return 1
    fi
    if [[ $(uname -m) != x86_64 || $(dpkg --print-architecture) != amd64 ]]; then
        printf '%s\n' 'Only x86_64/amd64 is supported.' >&2; return 1
    fi
    local existing
    for existing in /opt/freo /etc/freo /var/lib/freo /etc/systemd/system/freo*.service \
        /usr/lib/systemd/system/freo*.service /etc/nginx/sites-available/freo; do
        if [[ -e $existing || -L $existing ]]; then
            printf '%s\n' 'Existing Freo state detected. STOP. Use the signed upgrade/recovery procedure.' >&2
            return 1
        fi
    done
    if getent passwd freo >/dev/null; then
        printf '%s\n' 'Existing Freo account detected. Use the upgrade/recovery procedure.' >&2; return 1
    fi
    # Ubuntu cloud images provide Python. On stripped images, do not silently
    # modify the machine before the full Python preflight/confirmation can run.
    if [[ ! -x /usr/bin/python3 ]]; then
        printf '%s\n' 'Python 3 is missing. Install python3 from Ubuntu, then rerun this bootstrap.' >&2
        return 1
    fi
    exec env -i PATH="$PATH" HOME=/root LANG=C.UTF-8 \
        /usr/bin/python3 -I - "$@" <<'FREO_BOOTSTRAP_PY'
"""Self-contained delivery client. No application imports or third-party modules."""
import argparse
import ast
import contextlib
import datetime
import fcntl
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BOOTSTRAP_VERSION = "0.1.0"
FINGERPRINT = "B835B40E7E1A5838390256751AB72B63BEB716C3"
API = "https://api.github.com/repos/3andB/freo"
DOWNLOAD = "https://github.com/3andB/freo/releases/download"
STABLE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)\Z")
PLAIN_STABLE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_PACKAGE = 512 * 1024 * 1024
MAX_EXTRACTED = 2 * 1024 * 1024 * 1024
CLEAN_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8"}


class Stop(Exception):
    pass


def stable(value):
    if not isinstance(value, str) or len(value) > 128:
        raise Stop("Invalid stable version")
    match = PLAIN_STABLE.fullmatch(value) or STABLE.fullmatch(value)
    if not match:
        raise Stop("Only stable semantic versions are supported; no RC/beta channel")
    return tuple(int(n) for n in match.groups())


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Stop("Duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Stop("Invalid JSON number")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Stop("Malformed JSON response/manifest") from error


@contextlib.contextmanager
def deadline(seconds):
    def expired(_signum, _frame):
        raise Stop("Network operation exceeded its time limit")
    old = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def safe_url(url, hosts):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in hosts or
                parsed.port not in (None, 443) or parsed.username or parsed.password or
                parsed.fragment or any(ord(c) < 33 or ord(c) > 126 for c in url)):
            raise Stop("Disallowed download URL or redirect")
    except ValueError as error:
        raise Stop("Malformed download URL") from error
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, destination, *, limit, hosts, seconds=120):
    """No proxy/config credentials, bounded HTTPS, no reusable partial output."""
    safe_url(url, hosts)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise Stop("Download destination already exists")
    part = destination.with_name(destination.name + ".part")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), Redirects(hosts),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(url, headers={
        "User-Agent": "Freo-Bootstrap/" + BOOTSTRAP_VERSION,
        "Accept": "application/vnd.github+json" if "api.github.com" in hosts else "application/octet-stream"})
    for attempt in range(3):
        try:
            with deadline(seconds), opener.open(request, timeout=15) as response, part.open("xb") as output:
                safe_url(response.url, hosts)
                if response.status != 200:
                    raise Stop("Unexpected HTTP status")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdecimal() or int(length) > limit):
                    raise Stop("Invalid or excessive download size")
                count = 0
                while chunk := response.read(65536):
                    count += len(chunk)
                    if count > limit:
                        raise Stop("Download exceeds size limit")
                    output.write(chunk)
                if not count or (length is not None and count != int(length)):
                    raise Stop("Empty or incomplete download")
                output.flush()
                os.fsync(output.fileno())
            part.rename(destination)
            return
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise Stop(f"Download failed: HTTP {error.code}; no fallback release selected") from None
            retry = error.headers.get("Retry-After", "2")
            if not retry.isdecimal() or int(retry) > 30:
                raise Stop("Server requests a later retry; rerun later") from None
            delay = max(2, int(retry))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            if attempt == 2:
                raise Stop("HTTPS download failed after bounded retries; check network and clock") from error
            delay = 2 ** attempt
        finally:
            part.unlink(missing_ok=True)
        time.sleep(delay)


def api_json(path, work):
    destination = work / ("api-" + str(time.monotonic_ns()) + ".json")
    fetch(API + path, destination, limit=4 * 1024 * 1024, hosts={"api.github.com"})
    return strict_json(destination.read_bytes())


def release_version(release):
    if (not isinstance(release, dict) or release.get("draft") is not False or
            release.get("prerelease") is not False or not isinstance(release.get("published_at"), str)):
        raise Stop("Release is not explicitly published and stable")
    try:
        datetime.datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise Stop("Invalid release publication time") from error
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise Stop("Expected official vVERSION release tag")
    stable(tag[1:])
    return tag[1:]


def discover(work, version=None):
    if version:
        stable(version)
        release = api_json("/releases/tags/" + urllib.parse.quote("v" + version, safe=""), work)
        if release_version(release) != version:
            raise Stop("Explicit release version mismatch")
        return release
    candidates = []
    for page in range(1, 101):
        rows = api_json(f"/releases?per_page=100&page={page}", work)
        if not isinstance(rows, list) or len(rows) > 100:
            raise Stop("Invalid release listing")
        for row in rows:
            if not isinstance(row, dict):
                raise Stop("Malformed release entry")
            try:
                version = release_version(row)
            except Stop:
                # Known nonstable entries are irrelevant. Invalid metadata on a
                # putative stable release must not silently downgrade selection.
                if row.get("draft") is True or row.get("prerelease") is True:
                    continue
                tag = row.get("tag_name")
                if isinstance(tag, str):
                    try:
                        stable(tag.removeprefix("v"))
                    except Stop:
                        continue
                raise
            candidates.append((stable(version), version, row))
        if len(rows) < 100:
            break
    else:
        raise Stop("Release pagination limit exceeded; cannot establish latest stable")
    if not candidates:
        raise Stop("No published stable Freo release is available")
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise Stop("Ambiguous stable releases with equal semantic precedence")
    return candidates[0][2]


def assets(release):
    version = release_version(release)
    package = "freo-v" + version + ".tar.gz"
    required = (package, package + ".asc", "publisher.gpg", "PUBLISHER-FINGERPRINT.txt", "SHA256SUMS")
    rows = release.get("assets")
    if not isinstance(rows, list):
        raise Stop("Missing release assets")
    found = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise Stop("Malformed asset metadata")
        name = row["name"]
        if name not in required:
            continue
        expected = DOWNLOAD + "/" + urllib.parse.quote("v" + version, safe="") + "/" + urllib.parse.quote(name, safe="")
        size = row.get("size")
        if (name in found or row.get("state") != "uploaded" or
                row.get("browser_download_url") != expected or type(size) is not int or size <= 0 or
                size > (MAX_PACKAGE if name == package else 1024 * 1024)):
            raise Stop("Invalid, duplicate, or oversized release asset")
        found[name] = row
    if set(found) != set(required):
        raise Stop("Required signed release assets are missing")
    return version, package, found


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_assets(release, work):
    version, package, found = assets(release)
    for name, row in found.items():
        destination = work / name
        fetch(row["browser_download_url"], destination, limit=row["size"],
              hosts={"github.com", "release-assets.githubusercontent.com"}, seconds=600)
        if destination.stat().st_size != row["size"]:
            raise Stop("Downloaded size differs from GitHub asset metadata")
        if row.get("digest") is not None and row["digest"] != "sha256:" + sha256(destination):
            raise Stop("Downloaded hash differs from GitHub asset metadata")
    return version, package


def checksums(work, package):
    entries = {}
    for line in (work / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([A-Za-z0-9][A-Za-z0-9._+-]{0,200})", line)
        if not match or match[2] in entries:
            raise Stop("Malformed or duplicate checksum entry")
        entries[match[2]] = match[1]
    for name in (package, package + ".asc", "publisher.gpg", "PUBLISHER-FINGERPRINT.txt"):
        if entries.get(name) != sha256(work / name):
            raise Stop("SHA-256 verification failed for " + name)


def command(args, **kwargs):
    result = subprocess.run(args, env=CLEAN_ENV, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **kwargs)
    if result.returncode:
        raise Stop(Path(args[0]).name + " verification/preflight failed")
    return result.stdout.decode("utf-8", errors="strict")


def signature(work, package):
    home = work / "gnupg"
    home.mkdir(mode=0o700)
    key = work / "publisher.gpg"
    if (work / "PUBLISHER-FINGERPRINT.txt").read_text().strip() != FINGERPRINT:
        raise Stop("Published fingerprint differs from pinned publisher")
    listing = command(["/usr/bin/gpg", "--no-options", "--homedir", str(home), "--batch",
                       "--with-colons", "--import-options", "show-only", "--import", str(key)])
    primary = []
    want_primary = False
    for line in listing.splitlines():
        fields = line.split(":")
        if fields[0] in ("sec", "ssb"):
            raise Stop("Private signing material is not allowed")
        if fields[0] == "pub":
            want_primary = True
        elif fields[0] == "sub":
            want_primary = False
        elif fields[0] == "fpr" and want_primary:
            primary.append(fields[9])
            want_primary = False
    if primary != [FINGERPRINT]:
        raise Stop("Publisher key does not match pinned primary fingerprint")
    # Import only that primary identity into a new keyring, never the system's trust store.
    command(["/usr/bin/gpg", "--no-options", "--homedir", str(home), "--batch", "--import", str(key)])
    keyring = home / "trusted.gpg"
    with keyring.open("xb") as output:
        result = subprocess.run(["/usr/bin/gpg", "--no-options", "--homedir", str(home), "--batch",
                                 "--export", FINGERPRINT], env=CLEAN_ENV, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.PIPE, timeout=60)
    if result.returncode or not keyring.stat().st_size:
        raise Stop("Cannot construct isolated publisher keyring")
    status = command(["/usr/bin/gpgv", "--homedir", str(home), "--keyring", str(keyring),
                      "--status-fd", "1", str(work / (package + ".asc")), str(work / package)])
    valid = [line.split() for line in status.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
    if len(valid) != 1 or not (valid[0][2] == FINGERPRINT or valid[0][-1] == FINGERPRINT):
        raise Stop("Signature does not identify the pinned Freo publisher")
    if any("[GNUPG:] " + bad in status for bad in ("REVKEYSIG", "EXPKEYSIG", "EXPSIG", "BADSIG", "ERRSIG")):
        raise Stop("Invalid, expired, or revoked release signature")


def extract(work, package, version):
    # Read through the gzip trailer too; tar readers may stop before it.
    with gzip.open(work / package, "rb") as compressed:
        expanded = 0
        while chunk := compressed.read(65536):
            expanded += len(chunk)
            if expanded > MAX_EXTRACTED + 32 * 1024 * 1024:
                raise Stop("Compressed archive exceeds extraction limit")
    destination = work / "extraction.pending"
    destination.mkdir(mode=0o700)
    seen = set()
    total = 0
    with tarfile.open(work / package, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts or
                    str(path) != member.name or "\\" in member.name or member.name in seen or
                    not path.parts or any(ord(c) < 32 or ord(c) == 127 for c in member.name) or
                    member.mode not in (0o644, 0o755) or len(seen) >= 20000):
                raise Stop("Unsafe or unsupported release archive entry")
            total += member.size
            if member.size < 0 or total > MAX_EXTRACTED:
                raise Stop("Release extraction exceeds size limit")
            seen.add(member.name)
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 65536)
            target.chmod(member.mode)
    manifest = strict_json((destination / "release.json").read_bytes())
    if (not isinstance(manifest, dict) or type(manifest.get("format")) is not int or manifest["format"] != 1 or
            manifest.get("development") is not False or manifest.get("version") != version or
            manifest.get("platform") != "ubuntu-24.04-x86_64" or manifest.get("python") != "3.12" or
            not isinstance(manifest.get("commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]) or
            not isinstance(manifest.get("files"), dict) or seen != set(manifest["files"]) | {"release.json"}):
        raise Stop("Signed release identity/platform/inventory mismatch")
    for name, info in manifest["files"].items():
        target = destination / name
        if (not isinstance(info, dict) or info.get("sha256") != sha256(target) or
                type(info.get("size")) is not int or info["size"] != target.stat().st_size or
                info.get("mode") != stat.S_IMODE(target.stat().st_mode)):
            raise Stop("Signed package manifest verification failed")
    identity = ast.parse((destination / "app/version.py").read_text())
    versions = [ast.literal_eval(node.value) for node in identity.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)]
    if versions != [version] or not (destination / "scripts/install.sh").is_file():
        raise Stop("Application version or bundled installer is missing/mismatched")
    # cp -R in the signed installer preserves directory permissions. Public code
    # must be traversable after copying; the private working parent remains 0700.
    for directory in destination.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o755)
    destination.chmod(0o755)
    verified = work / "verified-release"
    destination.rename(verified)
    return verified, manifest


def verify(work, package, version):
    checksums(work, package)
    signature(work, package)
    return extract(work, package, version)


def options(argv):
    parser = argparse.ArgumentParser(description="Freo Bootstrap Installer " + BOOTSTRAP_VERSION)
    parser.add_argument("--domain")
    parser.add_argument("--email")
    parser.add_argument("--https", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Explicit noninteractive consent; requires --domain")
    parser.add_argument("--version")
    parser.add_argument("--bootstrap-version", action="version", version=BOOTSTRAP_VERSION)
    args = parser.parse_args(argv)
    if args.version:
        args.version = args.version.removeprefix("v")
        stable(args.version)
    if args.domain:
        args.domain = address(args.domain)
    if args.yes and not args.domain:
        raise Stop("Noninteractive mode requires --domain; IP detection is not consent")
    if args.https:
        if not args.domain or not args.email or re.fullmatch(r"[0-9.]+", args.domain):
            raise Stop("HTTPS requires an explicit DNS domain and --email")
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", args.email):
            raise Stop("Invalid certificate contact email")
    elif args.email:
        raise Stop("--email requires --https")
    return args


def address(value):
    if not isinstance(value, str) or not value or len(value) > 253:
        raise Stop("Invalid installation address")
    if re.fullmatch(r"[0-9.]+", value):
        try:
            ip = ipaddress.IPv4Address(value)
        except ValueError as error:
            raise Stop("Invalid IPv4 address") from error
        if not ip.is_global:
            raise Stop("Use the server's public IPv4 address or a DNS name")
        return str(ip)
    if ("." not in value or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                                for label in value.split("."))):
        raise Stop("Use a DNS hostname, without scheme, port, path, or shell syntax")
    return value.lower()


def preflight():
    if os.geteuid() != 0:
        raise Stop("Run with sudo or as root")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise Stop("Only Ubuntu 24.04 is supported")
    if platform.machine() != "x86_64" or command(["/usr/bin/dpkg", "--print-architecture"]).strip() != "amd64":
        raise Stop("Only x86_64/amd64 is supported")
    for path in (Path("/opt/freo"), Path("/etc/freo"), Path("/var/lib/freo"),
                 Path("/etc/nginx/sites-available/freo"),
                 *Path("/etc/systemd/system").glob("freo*"), *Path("/usr/lib/systemd/system").glob("freo*")):
        if path.exists() or path.is_symlink():
            raise Stop("Existing Freo state detected. Use the signed upgrade/recovery procedure")
    for account in ("freo", "freo-playout", "freo-ingest", "freo-automation", "freo-stats"):
        try:
            pwd.getpwnam(account)
        except KeyError:
            continue
        raise Stop("Existing Freo service account detected; investigate or use supported recovery")
    # A fresh target does not need an existing PostgreSQL cluster. Its presence
    # may hide old Freo roles/data even when directories have been removed.
    if Path("/etc/postgresql").exists() and any(Path("/etc/postgresql").iterdir()):
        raise Stop("Existing PostgreSQL cluster configuration found; use a fresh VM")


def confirm(message):
    try:
        with open("/dev/tty", "w", encoding="utf-8", buffering=1) as output, open("/dev/tty", "r", encoding="utf-8") as tty:
            output.write(message + " [y/N] ")
            output.flush()
            reply = tty.readline(100).strip().lower()
    except OSError as error:
        raise Stop("No interactive terminal; use documented --yes with explicit --domain") from error
    if reply not in ("y", "yes"):
        raise Stop("Cancelled. Freo was not installed")


def public_ip(work):
    try:
        output = work / "public-ip.txt"
        fetch("https://api.ipify.org", output, limit=128, hosts={"api.ipify.org"}, seconds=20)
        value = output.read_text().strip()
        if not ipaddress.IPv4Address(value).is_global:
            return None, False
        local = command(["/usr/sbin/ip", "-j", "-4", "address", "show", "scope", "global"])
        assigned = [a.get("local") for interface in strict_json(local) for a in interface.get("addr_info", [])]
        return value, value in assigned
    except (Stop, OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return None, False


def choose_address(args, detected, corroborated):
    if args.domain:
        return args.domain
    if detected and corroborated:
        return address(detected)
    try:
        with open("/dev/tty", "w", encoding="utf-8", buffering=1) as output, open("/dev/tty", "r", encoding="utf-8") as tty:
            output.write("Public installation IPv4 address or DNS hostname (automatic detection uncertain): ")
            output.flush()
            return address(tty.readline(300).strip())
    except OSError as error:
        raise Stop("Specify --domain; cannot safely determine the installation address") from error


def screen(args, version, detected):
    hostname = re.sub(r"[^A-Za-z0-9_.-]", "?", socket.gethostname())
    print(f"\nFreo Installer\n\nServer: {hostname}\nPublic IP: {detected or 'Unknown (not detected)'}"
          f"\nInstallation address: {'https' if args.https else 'http'}://{args.domain}"
          f"\nOS: Ubuntu 24.04\nArchitecture: x86_64 / amd64"
          f"\nBootstrap: {BOOTSTRAP_VERSION}\nInstalling Freo: {version}"
          "\n\nThis will install Freo and configure services on this server.", flush=True)


def dependencies(args):
    packages = []
    if not Path("/etc/ssl/certs/ca-certificates.crt").is_file():
        # No verified TLS discovery is possible without the OS trust store.
        raise Stop("Ubuntu CA certificates are missing. Install ca-certificates, then rerun")
    if not Path("/usr/bin/gpg").is_file():
        packages.append("gnupg")
    if not Path("/usr/bin/gpgv").is_file():
        packages.append("gpgv")
    if packages:
        print("Required verification tools: " + ", ".join(packages), flush=True)
        if not args.yes:
            confirm("Install these public Ubuntu verification tools before verifying Freo?")
        for cmd in (["/usr/bin/apt-get", "update"], ["/usr/bin/apt-get", "install", "--no-upgrade", "-y", *packages]):
            result = subprocess.run(cmd, env={**CLEAN_ENV, "DEBIAN_FRONTEND": "noninteractive"},
                                    stdin=subprocess.DEVNULL, timeout=900)
            if result.returncode:
                raise Stop("Verification tool installation failed; Freo installer was not run")


def install(source, args, log, version):
    stable(version)
    env = {**CLEAN_ENV, "FREO_DOMAIN": args.domain, "FREO_ENABLE_HTTPS": "1" if args.https else "0",
           "FREO_VERSION": version}  # Existing provisioner's /etc/freo/release marker.
    if args.https:
        env["FREO_CERTBOT_EMAIL"] = args.email
    with log.open("xb") as output:
        process = subprocess.Popen(["/bin/bash", str(source / "scripts/install.sh")], cwd=source,
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            for line in iter(process.stdout.readline, b""):
                output.write(line)
                output.flush()
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
            code = process.wait()
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        finally:
            process.stdout.close()
    if code:
        raise Stop(f"Bundled installer failed (exit {code}). Do not delete Freo state or automatically retry")


def lock():
    fd = os.open("/run/freo-bootstrap.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
        os.close(fd)
        raise Stop("Unsafe bootstrap lock file")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise Stop("Another bootstrap is running") from None
    return fd  # Keep locked through the installer; never unlink a live lock.


def main(argv=None):
    os.umask(0o077)
    args = options(sys.argv[1:] if argv is None else argv)
    preflight()
    lock_fd = lock()
    work = Path(tempfile.mkdtemp(prefix="freo-bootstrap-", dir="/var/tmp"))
    success = False
    try:
        release = discover(work, args.version)
        version, package, _ = assets(release)
        detected, corroborated = public_ip(work)
        args.domain = choose_address(args, detected, corroborated)
        screen(args, version, detected)
        if not args.yes:
            confirm("Continue?")
        dependencies(args)
        download_assets(release, work)
        source, manifest = verify(work, package, version)
        receipt = {"bootstrap_version": BOOTSTRAP_VERSION, "freo_version": version,
                   "tag": release["tag_name"], "commit": manifest["commit"],
                   "package_sha256": sha256(work / package), "publisher_fingerprint": FINGERPRINT,
                   "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "installation": "not_started"}
        evidence = work / "verification.json"
        evidence.write_text(json.dumps(receipt, indent=2) + "\n")
        print("Verified publisher, signature, package hashes and Freo " + version + ".", flush=True)
        preflight()  # State may have changed while downloading; refuse before execution.
        receipt["installation"] = "started"
        evidence.write_text(json.dumps(receipt, indent=2) + "\n")
        try:
            install(source, args, work / "installer.log", version)
        except BaseException:
            receipt["installation"] = "failed_or_interrupted"
            evidence.write_text(json.dumps(receipt, indent=2) + "\n")
            raise
        receipt["installation"] = "completed"
        evidence.write_text(json.dumps(receipt, indent=2) + "\n")
        success = True
        print(f"\nFreo {version} installed. Open {'https' if args.https else 'http'}://{args.domain}/admin/login"
              "\nComplete first-time administrator setup immediately.")
    finally:
        if success:
            # Keep only private diagnostics/receipt; never retain an executable
            # temporary package as something an operator might rerun later.
            for child in work.iterdir():
                if child.name not in ("installer.log", "verification.json"):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        print(f"Private diagnostics: {work}\nDo not share credentials, .env files, or unreviewed logs.", flush=True)
        os.close(lock_fd)


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except (Stop, OSError, EOFError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        # Do not dump remote content, URLs with CDN credentials, or environment.
        print("STOP: " + (str(error) if isinstance(error, Stop) else type(error).__name__ + "; operation failed safely"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("STOP: Interrupted. Inspect retained diagnostics before taking further action.", file=sys.stderr)
        sys.exit(130)
FREO_BOOTSTRAP_PY
}
freo_bootstrap_main "$@"
