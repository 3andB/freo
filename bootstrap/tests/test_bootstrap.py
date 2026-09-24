"""Standalone unittest suite: no Freo/Flask imports, real installer never runs."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
import urllib.error

from support import load, SCRIPT


def release(version="0.3.0", **kwargs):
    package = "freo-v" + version + ".tar.gz"
    value = dict(tag_name="v" + version, draft=False, prerelease=False,
                 published_at="2026-09-24T19:58:14Z", assets=[])
    for name in (package, package + ".asc", "publisher.gpg", "PUBLISHER-FINGERPRINT.txt", "SHA256SUMS"):
        value["assets"].append(dict(name=name, state="uploaded", size=10,
                                   browser_download_url="https://github.com/3andB/freo/releases/download/v" + version + "/" + name))
    value.update(kwargs)
    return value


class Base(unittest.TestCase):
    def setUp(self):
        self.b = load()
        self.temp = tempfile.TemporaryDirectory(prefix="freo-bootstrap-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)


class Discovery(Base):
    def test_highest_stable_not_date_order(self):
        rows = [release("0.3.0"), release("0.10.0"), release("0.9.0"),
                release("9.0.0", draft=True), release("8.0.0", prerelease=True), release("7.0.0-rc.1")]
        with patch.object(self.b, "api_json", return_value=rows):
            self.assertEqual(self.b.discover(self.work)["tag_name"], "v0.10.0")

    def test_pagination_including_second_page(self):
        rows = [release(f"0.0.{i}") for i in range(100)]
        with patch.object(self.b, "api_json", side_effect=[rows, [release("1.0.0")]]) as api:
            self.assertEqual(self.b.discover(self.work)["tag_name"], "v1.0.0")
            self.assertEqual(api.call_count, 2)

    def test_explicit_version_published_release_only(self):
        with patch.object(self.b, "api_json", return_value=release()) as api:
            self.b.discover(self.work, "0.3.0")
            self.assertEqual(api.call_args.args[0], "/releases/tags/v0.3.0")
        for value in (release(draft=True), release(prerelease=True), release("0.4.0"), release(published_at=None)):
            with self.subTest(value=value), patch.object(self.b, "api_json", return_value=value), self.assertRaises(self.b.Stop):
                self.b.discover(self.work, "0.3.0")

    def test_empty_or_unavailable_no_fallback(self):
        for result in ([], {}, [release("0.4.0-rc.1")], [release(published_at="bad")]):
            with self.subTest(result=result), patch.object(self.b, "api_json", return_value=result), self.assertRaises(self.b.Stop):
                self.b.discover(self.work)
        with patch.object(self.b, "api_json", side_effect=self.b.Stop("unavailable")), self.assertRaises(self.b.Stop):
            self.b.discover(self.work)

    def test_equal_precedence_is_ambiguous(self):
        with patch.object(self.b, "api_json", return_value=[release("1.0.0+a"), release("1.0.0+b")]), self.assertRaises(self.b.Stop):
            self.b.discover(self.work)

    def test_version_validation(self):
        for value in ("1.2.3-rc.1", "01.2.3", "1.2", "1.2.3;id", "1.2.3/../../x", "1.2.3\n", None):
            with self.subTest(value=value), self.assertRaises(self.b.Stop):
                self.b.stable(value)
        self.assertEqual(self.b.stable("1.2.3+build.1"), (1, 2, 3))

    def test_missing_duplicate_or_malicious_assets(self):
        bad = []
        item = release(); item["assets"].pop(); bad.append(item)
        item = release(); item["assets"].append(item["assets"][0]); bad.append(item)
        for value in ("http://github.com/package", "https://github.com.evil.test/pkg", "https://evil.test/pkg",
                      "https://github.com/other/freo/releases/download/v0.3.0/freo-v0.3.0.tar.gz"):
            item = release(); item["assets"][0]["browser_download_url"] = value; bad.append(item)
        for size in (0, -1, True, "123", self.b.MAX_PACKAGE + 1):
            item = release(); item["assets"][0]["size"] = size; bad.append(item)
        for item in bad:
            with self.subTest(item=item), self.assertRaises(self.b.Stop):
                self.b.assets(item)
        self.assertEqual(self.b.assets(release())[1], "freo-v0.3.0.tar.gz")

    def test_duplicate_json_keys_and_nonfinite(self):
        for value in ('{"draft":true,"draft":false}', '{"x":NaN}', '<html>failure</html>'):
            with self.subTest(value=value), self.assertRaises(self.b.Stop):
                self.b.strict_json(value)


class Inputs(Base):
    def test_http_arguments(self):
        args = self.b.options(["--domain", "8.8.8.8", "--yes", "--version", "v0.3.0"])
        self.assertFalse(args.https)
        self.assertEqual(args.domain, "8.8.8.8")
        self.assertEqual(args.version, "0.3.0")

    def test_https_explicit_domain_email(self):
        args = self.b.options(["--https", "--domain", "Radio.Example.com", "--email", "owner@example.com", "--yes"])
        self.assertEqual(args.domain, "radio.example.com")
        self.assertTrue(args.https)
        for argv in (["--https"], ["--https", "--domain", "8.8.8.8", "--email", "a@b.com"],
                     ["--email", "a@b.com"], ["--https", "--domain", "radio.example.com", "--email", "a\nb@c.com"]):
            with self.subTest(argv=argv), self.assertRaises(self.b.Stop):
                self.b.options(argv)

    def test_noninteractive_never_guesses(self):
        with self.assertRaises(self.b.Stop):
            self.b.options(["--yes"])

    def test_injection_and_unsafe_hosts(self):
        for host in ("$(id).com", "foo.com;id", "foo.com\n", "https://foo.com", "-x.com", "foo.com/hi", "foo.com:443",
                     "127.0.0.1", "10.0.0.1", "999.1.1.1", "::1", "a..com", "a." + "b" * 64):
            with self.subTest(host=host), self.assertRaises(self.b.Stop):
                self.b.address(host)

    def test_confirmation_cancellation_and_yes(self):
        for reply in ("", "n", "no", "yes please"):
            tty = Mock(); tty.readline.return_value = reply
            cm = Mock(); cm.__enter__ = Mock(return_value=tty); cm.__exit__ = Mock(return_value=False)
            with patch("builtins.open", return_value=cm), self.assertRaises(self.b.Stop):
                self.b.confirm("Continue?")
        tty.readline.return_value = "yes\n"
        with patch("builtins.open", return_value=cm):
            self.b.confirm("Continue?")
        with patch("builtins.open", side_effect=OSError), self.assertRaises(self.b.Stop):
            self.b.confirm("Continue?")

    def test_confirmation_uses_tty_when_stdin_is_pipe(self):
        # This child calls only confirm(), never preflight/main/install.
        child, master = pty.fork()
        if child == 0:
            try:
                os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
                self.b.confirm("Pipe confirmation")
                os._exit(0)
            except BaseException:
                os._exit(1)
        try:
            ready, _, _ = select.select([master], [], [], 5)
            self.assertTrue(ready)
            self.assertIn(b"[y/N]", os.read(master, 4096))
            os.write(master, b"yes\n")
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            os.close(master)

    def test_public_ip_corroboration_and_failure(self):
        def download(_url, target, **_kwargs):
            target.write_text("8.8.8.8")
        with patch.object(self.b, "fetch", side_effect=download), patch.object(self.b, "command", return_value='[{"addr_info":[{"local":"8.8.8.8"}]}]'):
            self.assertEqual(self.b.public_ip(self.work), ("8.8.8.8", True))
        with patch.object(self.b, "fetch", side_effect=download), patch.object(self.b, "command", return_value='[]'):
            self.assertEqual(self.b.public_ip(self.work), ("8.8.8.8", False))
        with patch.object(self.b, "fetch", side_effect=self.b.Stop("offline")):
            self.assertEqual(self.b.public_ip(self.work), (None, False))

    def test_uncertain_ip_prompts_not_autoaccepted(self):
        args = self.b.options([])
        with patch("builtins.open", side_effect=OSError), self.assertRaises(self.b.Stop):
            self.b.choose_address(args, "8.8.8.8", False)
        self.assertEqual(self.b.choose_address(args, "8.8.8.8", True), "8.8.8.8")

    def test_confirmation_screen_all_fields(self):
        output = io.StringIO()
        args = self.b.options(["--domain", "radio.example.com"])
        with contextlib.redirect_stdout(output), patch.object(self.b.socket, "gethostname", return_value="TEST-SERVER"):
            self.b.screen(args, "0.3.0", "8.8.8.8")
        for text in ("TEST-SERVER", "8.8.8.8", "http://radio.example.com", "Ubuntu 24.04", "x86_64 / amd64", "Bootstrap: 0.1.0", "Installing Freo: 0.3.0"):
            self.assertIn(text, output.getvalue())


class Preflight(Base):
    def clean(self):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(self.b.os, "geteuid", return_value=0))
        stack.enter_context(patch.object(self.b.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}))
        stack.enter_context(patch.object(self.b.platform, "machine", return_value="x86_64"))
        stack.enter_context(patch.object(self.b, "command", return_value="amd64\n"))
        stack.enter_context(patch.object(Path, "exists", return_value=False))
        stack.enter_context(patch.object(Path, "is_symlink", return_value=False))
        stack.enter_context(patch.object(Path, "glob", return_value=[]))
        stack.enter_context(patch.object(self.b.pwd, "getpwnam", side_effect=KeyError))
        return stack

    def test_ubuntu_accepted(self):
        with self.clean():
            self.b.preflight()

    def test_wrong_os_arch_or_nonroot(self):
        cases = [(self.b.os, "geteuid", 1000), (self.b.platform, "machine", "aarch64"),
                 (self.b.platform, "freedesktop_os_release", {"ID": "ubuntu", "VERSION_ID": "22.04"}),
                 (self.b.platform, "freedesktop_os_release", {"ID": "debian", "VERSION_ID": "24.04"})]
        for target, name, value in cases:
            with self.subTest(name=name, value=value), self.clean(), patch.object(target, name, return_value=value), self.assertRaises(self.b.Stop):
                self.b.preflight()

    def test_existing_opt_freo_or_dangling_symlink_rejected(self):
        for name in ("exists", "is_symlink"):
            with self.subTest(name=name), self.clean(), patch.object(Path, name, new=lambda p: str(p) == "/opt/freo"), self.assertRaises(self.b.Stop):
                self.b.preflight()

    def test_existing_accounts_rejected(self):
        with self.clean(), patch.object(self.b.pwd, "getpwnam", return_value=object()), self.assertRaises(self.b.Stop):
            self.b.preflight()


class Network(Base):
    def test_asset_api_digest_or_size_mismatch(self):
        for defect in ("size", "digest"):
            data = release()
            for item in data["assets"]:
                item["size"] = 3
                item["digest"] = "sha256:" + hashlib.sha256(b"abc").hexdigest()
            if defect == "digest":
                data["assets"][0]["digest"] = "sha256:" + "0" * 64
            def download(_url, target, **_kwargs):
                target.write_bytes(b"ab" if defect == "size" else b"abc")
            with self.subTest(defect=defect), patch.object(self.b, "fetch", side_effect=download), self.assertRaises(self.b.Stop):
                self.b.download_assets(data, self.work)

    def test_download_destination_symlink_rejected(self):
        outside = self.work / "untouched"
        outside.write_text("safe")
        (self.work / "download").symlink_to(outside)
        with self.assertRaises(self.b.Stop):
            self.fetch()
        self.assertEqual(outside.read_text(), "safe")

    def test_redirect_handler_rejects_external_host(self):
        request = self.b.urllib.request.Request("https://github.com/example")
        with self.assertRaises(self.b.Stop):
            self.b.Redirects({"github.com"}).redirect_request(request, None, 302, "", {}, "https://evil.test/payload")

    def test_network_deadline_is_enforced(self):
        with self.assertRaises(self.b.Stop):
            with self.b.deadline(1):
                signal.raise_signal(signal.SIGALRM)

    def response(self, payload=b"hello", length="5"):
        result = io.BytesIO(payload)
        result.url = "https://github.com/3andB/freo/releases/download/v0.3.0/example"
        result.status = 200
        result.headers = {"Content-Length": length}
        return result

    def fetch(self):
        return self.b.fetch("https://github.com/3andB/freo/releases/download/v0.3.0/example", self.work / "download", limit=100, hosts={"github.com"})

    def test_atomic_success(self):
        opener = Mock(); opener.open.return_value = self.response()
        with patch.object(self.b.urllib.request, "build_opener", return_value=opener):
            self.fetch()
        self.assertEqual((self.work / "download").read_bytes(), b"hello")
        self.assertFalse((self.work / "download.part").exists())

    def test_partial_corrupt_or_oversized_download_not_retained(self):
        for payload, length in ((b"bad", "50"), (b"", "0"), (b"hi", "9999"), (b"hi", "oops")):
            opener = Mock(); opener.open.return_value = self.response(payload, length)
            with self.subTest(payload=payload, length=length), patch.object(self.b.urllib.request, "build_opener", return_value=opener), self.assertRaises(self.b.Stop):
                self.fetch()
            self.assertFalse((self.work / "download").exists())
            self.assertFalse((self.work / "download.part").exists())

    def test_http_errors_and_timeout_retry_bounded(self):
        for error, attempts in ((urllib.error.HTTPError("https://github.com", 404, "missing", {}, None), 1),
                                (urllib.error.HTTPError("https://github.com", 503, "outage", {}, None), 3),
                                (TimeoutError(), 3), (urllib.error.URLError("network"), 3)):
            opener = Mock(); opener.open.side_effect = error
            with self.subTest(error=error), patch.object(self.b.urllib.request, "build_opener", return_value=opener), patch.object(self.b.time, "sleep"), self.assertRaises(self.b.Stop):
                self.fetch()
            self.assertEqual(opener.open.call_count, attempts)

    def test_rate_limit_long_retry_stops(self):
        opener = Mock(); opener.open.side_effect = urllib.error.HTTPError("https://github.com", 429, "rate", {"Retry-After": "3600"}, None)
        with patch.object(self.b.urllib.request, "build_opener", return_value=opener), self.assertRaises(self.b.Stop):
            self.fetch()
        self.assertEqual(opener.open.call_count, 1)

    def test_redirects_https_and_host_restrictions(self):
        allowed = {"github.com", "release-assets.githubusercontent.com"}
        self.b.safe_url("https://release-assets.githubusercontent.com/a?signature=example", allowed)
        for url in ("http://github.com/a", "file:///etc/passwd", "https://github.com.evil.test/a", "https://user:pass@github.com/a", "https://github.com:444/a", "https://github.com/a\n", "https://evil.test/a"):
            with self.subTest(url=url), self.assertRaises(self.b.Stop):
                self.b.safe_url(url, allowed)


class Crypto(Base):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory(prefix="freo-bootstrap-test-key-")
        cls.home = Path(cls.keys.name)
        cls.home.chmod(0o700)
        subprocess.run(["gpg", "--homedir", str(cls.home), "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                        "--quick-generate-key", "Bootstrap Fixture <fixture@example.invalid>", "ed25519", "sign", "0"], check=True, capture_output=True)
        listing = subprocess.check_output(["gpg", "--homedir", str(cls.home), "--with-colons", "--list-keys"], stderr=subprocess.DEVNULL).decode()
        cls.fingerprint = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", str(cls.home), "--kill", "gpg-agent"], capture_output=True)
        cls.keys.cleanup()

    def payload(self, *, version="0.3.0", name="freo-v0.3.0.tar.gz", extra=None, manifest_change=None):
        files = {"app/version.py": (f"VERSION = {version!r}\n".encode(), 0o644),
                 "scripts/install.sh": (b"#!/bin/bash\nprintf 'FIXTURE ONLY\\n'\n", 0o755),
                 "wsgi.py": (b"# fixture\n", 0o644)}
        manifest = dict(format=1, development=False, version="0.3.0", platform="ubuntu-24.04-x86_64", python="3.12", commit="a" * 40,
                        files={key: dict(sha256=hashlib.sha256(data).hexdigest(), mode=mode, size=len(data)) for key, (data, mode) in files.items()})
        if manifest_change:
            manifest_change(manifest)
        files["release.json"] = (json.dumps(manifest).encode(), 0o644)
        with tarfile.open(self.work / name, "w:gz") as archive:
            for path, (data, mode) in files.items():
                entry = tarfile.TarInfo(path); entry.size = len(data); entry.mode = mode
                archive.addfile(entry, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b"X" * extra.size) if extra.isfile() else None)
        self.sign(name)
        return name

    def sign(self, name):
        subprocess.run(["gpg", "--homedir", str(self.home), "--batch", "--yes", "--armor", "--detach-sign", str(self.work / name)], check=True, capture_output=True)
        (self.work / "publisher.gpg").write_bytes(subprocess.check_output(["gpg", "--homedir", str(self.home), "--export", self.fingerprint]))
        (self.work / "PUBLISHER-FINGERPRINT.txt").write_text(self.fingerprint + "\n")
        self.sums(name)

    def sums(self, name):
        (self.work / "SHA256SUMS").write_text("".join(self.b.sha256(self.work / item) + "  " + item + "\n" for item in (name, name + ".asc", "publisher.gpg", "PUBLISHER-FINGERPRINT.txt")))

    def verify(self, name):
        with patch.object(self.b, "FINGERPRINT", self.fingerprint):
            return self.b.verify(self.work, name, "0.3.0")

    def test_real_gpg_signature_manifest_and_safe_permissions(self):
        name = self.payload()
        source, manifest = self.verify(name)
        self.assertEqual(manifest["version"], "0.3.0")
        self.assertEqual((source / "scripts").stat().st_mode & 0o777, 0o755)
        self.assertEqual(source.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(source.name, "verified-release")

    def test_bad_sha_prevents_signature_and_execution(self):
        name = self.payload()
        (self.work / name).write_bytes(b"corrupt")
        with patch.object(self.b, "signature") as signature, patch.object(self.b, "install") as install, self.assertRaises(self.b.Stop):
            self.verify(name)
        signature.assert_not_called(); install.assert_not_called()

    def test_wrong_publisher_fingerprint_rejected(self):
        name = self.payload()
        with self.assertRaises(self.b.Stop):
            self.b.verify(self.work, name, "0.3.0")

    def test_matching_fingerprint_text_does_not_trust_wrong_key(self):
        name = self.payload()
        (self.work / "PUBLISHER-FINGERPRINT.txt").write_text(self.b.FINGERPRINT)
        self.sums(name)
        with self.assertRaisesRegex(self.b.Stop, "pinned primary"):
            self.b.verify(self.work, name, "0.3.0")

    def test_bad_signature_even_when_checksum_replaced(self):
        name = self.payload()
        with (self.work / name).open("ab") as stream:
            stream.write(b"tampered")
        self.sums(name)
        with patch.object(self.b, "extract") as extract, self.assertRaises(self.b.Stop):
            self.verify(name)
        extract.assert_not_called()

    def test_corrupt_signature_file_rejected(self):
        name = self.payload()
        (self.work / (name + ".asc")).write_text("not a signature")
        self.sums(name)
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_signed_platform_mismatch(self):
        name = self.payload(manifest_change=lambda m: m.update(platform="other-platform"))
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_signed_missing_inventory_entry(self):
        name = self.payload(manifest_change=lambda m: m["files"].pop("wsgi.py"))
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_archive_extraction_resource_limit(self):
        name = self.payload()
        with patch.object(self.b, "MAX_EXTRACTED", 1), self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_checksum_parsing_rejects_duplicates_traversal_shell(self):
        name = self.payload()
        original = (self.work / "SHA256SUMS").read_text()
        for suffix in (original.splitlines()[0] + "\n", "a" * 64 + "  ../escape\n", "a" * 64 + "  $(id)\n"):
            (self.work / "SHA256SUMS").write_text(original + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(self.b.Stop):
                self.b.checksums(self.work, name)

    def test_signed_version_mismatch(self):
        name = self.payload(version="9.9.9")
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_signed_internal_hash_mismatch(self):
        name = self.payload(manifest_change=lambda m: m["files"]["wsgi.py"].update(sha256="0" * 64))
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_signed_development_manifest_rejected(self):
        name = self.payload(manifest_change=lambda m: m.update(development=True))
        with self.assertRaises(self.b.Stop):
            self.verify(name)

    def test_signed_corrupt_gzip_rejected(self):
        name = self.payload()
        (self.work / name).write_bytes((self.work / name).read_bytes()[:-8])
        self.sign(name)
        with self.assertRaises((EOFError, OSError, self.b.Stop)):
            self.verify(name)

    def test_signed_unsafe_archive_members(self):
        for path, kind in (("../escape", tarfile.REGTYPE), ("/tmp/escape", tarfile.REGTYPE),
                           ("app/link", tarfile.SYMTYPE), ("app/hard", tarfile.LNKTYPE),
                           ("app/fifo", tarfile.FIFOTYPE), ("app/version.py", tarfile.REGTYPE), ("app/./extra", tarfile.REGTYPE)):
            with self.subTest(path=path):
                for child in self.work.iterdir():
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
                entry = tarfile.TarInfo(path); entry.type = kind; entry.mode = 0o644; entry.linkname = "../../escape"
                name = self.payload(extra=entry)
                with self.assertRaises(self.b.Stop):
                    self.verify(name)
                self.assertFalse((self.work / "verified-release").exists())


class Lifecycle(Base):
    def test_concurrent_bootstrap_lock_and_symlink_guard(self):
        # Redirect only the lock's absolute pathname into a disposable directory.
        real_open = os.open
        lockfile = self.work / "lock"
        def redirected(path, flags, mode=0o777):
            self.assertEqual(path, "/run/freo-bootstrap.lock")
            return real_open(lockfile, flags, mode)
        # The same rule is checked under CI's nonroot uid without root execution.
        real_fstat = os.fstat
        def owned(fd):
            info = real_fstat(fd)
            return type("LockInfo", (), dict(st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink))()
        with patch.object(self.b.os, "open", side_effect=redirected), patch.object(self.b.os, "fstat", side_effect=owned):
            fd = self.b.lock()
            try:
                with self.assertRaises(self.b.Stop):
                    self.b.lock()
            finally:
                os.close(fd)
            lockfile.unlink()
            lockfile.symlink_to(self.work / "missing")
            with self.assertRaises(OSError):
                self.b.lock()

    def test_missing_tools_only_installed_with_consent(self):
        args = self.b.options(["--domain", "radio.example.com"])
        with patch.object(Path, "is_file", new=lambda p: str(p) == "/etc/ssl/certs/ca-certificates.crt"), \
                patch.object(self.b, "confirm", side_effect=self.b.Stop("cancelled")), \
                patch.object(self.b.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(self.b.Stop):
            self.b.dependencies(args)
        run.assert_not_called()

    def test_existing_state_created_during_download_stops_install(self):
        stack, mocks = self.lifecycle(preflight=Mock(side_effect=[None, self.b.Stop("existing")]))
        with stack, self.assertRaises(self.b.Stop):
            self.b.main(["--domain", "radio.example.com", "--yes"])
        mocks["install"].assert_not_called()

    def lifecycle(self, **overrides):
        # Every host-affecting operation is mocked, including installation.
        stack = contextlib.ExitStack()
        patches = dict(preflight=Mock(), lock=Mock(return_value=123456), public_ip=Mock(return_value=("8.8.8.8", True)),
                       discover=Mock(return_value=release()), dependencies=Mock(), download_assets=Mock(),
                       verify=Mock(return_value=(self.work / "source", {"commit": "a" * 40})),
                       sha256=Mock(return_value="0" * 64), install=Mock(), confirm=Mock())
        patches.update(overrides)
        for name, value in patches.items():
            stack.enter_context(patch.object(self.b, name, value))
        stack.enter_context(patch.object(self.b.tempfile, "mkdtemp", return_value=str(self.work)))
        stack.enter_context(patch.object(self.b.os, "close"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return stack, patches

    def test_verification_failure_never_runs_installer_preserves_evidence(self):
        for stage in ("discover", "dependencies", "download_assets", "verify"):
            (self.work / "diagnostic").write_text("evidence")
            stack, mocks = self.lifecycle(**{stage: Mock(side_effect=self.b.Stop("injected"))})
            with stack, self.assertRaises(self.b.Stop):
                self.b.main(["--domain", "radio.example.com", "--yes"])
            mocks["install"].assert_not_called()
            self.assertTrue((self.work / "diagnostic").exists())

    def test_cancel_no_dependency_changes_or_installation(self):
        stack, mocks = self.lifecycle(confirm=Mock(side_effect=self.b.Stop("cancelled")))
        with stack, self.assertRaises(self.b.Stop):
            self.b.main(["--domain", "radio.example.com"])
        mocks["dependencies"].assert_not_called(); mocks["install"].assert_not_called()

    def test_success_rechecks_preflight_and_removes_downloads(self):
        (self.work / "download").write_text("archive")
        stack, mocks = self.lifecycle()
        with stack:
            self.b.main(["--domain", "radio.example.com", "--yes"])
        mocks["install"].assert_called_once(); mocks["confirm"].assert_not_called()
        self.assertEqual(mocks["preflight"].call_count, 2)
        self.assertFalse((self.work / "download").exists())
        self.assertEqual(json.loads((self.work / "verification.json").read_text())["installation"], "completed")

    def test_failed_installation_does_not_retry_or_delete_state(self):
        (self.work / "installer.log").write_text("failure output")
        stack, mocks = self.lifecycle(install=Mock(side_effect=self.b.Stop("installer failed")))
        with stack, self.assertRaises(self.b.Stop):
            self.b.main(["--domain", "radio.example.com", "--yes"])
        mocks["install"].assert_called_once()
        self.assertTrue((self.work / "installer.log").exists())

    def test_actual_installer_handoff_http_https_clean_environment(self):
        # Harmless fixture script only; never the Freo application installer.
        source = self.work / "source"; (source / "scripts").mkdir(parents=True)
        target = self.work / "env.json"
        (source / "scripts/install.sh").write_text("#!/bin/bash\n/usr/bin/python3 -c 'import os,json; print(json.dumps(dict(os.environ)))' > " + str(target) + "\n")
        for https in (False, True):
            argv = ["--domain", "radio.example.com"] + (["--https", "--email", "owner@example.com"] if https else [])
            args = self.b.options(argv)
            with patch.dict(os.environ, {"FREO_VERSION": "evil", "FREO_INSTALL_DIR": "/bad", "PYTHONPATH": "/bad", "TOKEN": "secret"}):
                self.b.install(source, args, self.work / ("https.log" if https else "http.log"), "0.3.0")
            env = json.loads(target.read_text())
            self.assertEqual(env["FREO_DOMAIN"], "radio.example.com")
            self.assertEqual(env["FREO_ENABLE_HTTPS"], "1" if https else "0")
            self.assertEqual(env.get("FREO_CERTBOT_EMAIL"), "owner@example.com" if https else None)
            self.assertEqual(env["FREO_VERSION"], "0.3.0")
            for key in ("FREO_INSTALL_DIR", "PYTHONPATH", "TOKEN"):
                self.assertNotIn(key, env)

    def test_syntax_and_no_runtime_030_hash_pin(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        self.assertNotIn("f171ebac", SCRIPT.read_text())


if __name__ == "__main__":
    unittest.main()
