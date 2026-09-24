"""Real isolated Nginx/TLS delivery. Does not use/reload production configuration."""
import hashlib
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import ssl

from support import SCRIPT


@unittest.skipUnless(shutil.which("nginx") and shutil.which("openssl"), "Requires nginx and openssl for isolated delivery test")
class HTTPSDelivery(unittest.TestCase):
    def test_exact_bytes_plain_text_aliases_and_no_fallback(self):
        with tempfile.TemporaryDirectory(prefix="freo-bootstrap-https-") as directory:
            root = Path(directory)
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                            "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem")], check=True, capture_output=True)
            (root / "install.sh").write_bytes(SCRIPT.read_bytes())
            locations = (SCRIPT.parent / "nginx/bootstrap-locations.conf").read_text().replace("/srv/freo-bootstrap/install.sh", str(root / "install.sh"))
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
            # No worker privilege drop: private test data is reachable only by
            # the invoking uid; listener is loopback only, no application proxy.
            config = root / "nginx.conf"
            config.write_text(f"""daemon off;
master_process off;
pid {root}/nginx.pid;
error_log {root}/error.log;
events {{ worker_connections 16; }}
http {{
  access_log off;
  client_body_temp_path {root}/body;
  proxy_temp_path {root}/proxy;
  fastcgi_temp_path {root}/fastcgi;
  uwsgi_temp_path {root}/uwsgi;
  scgi_temp_path {root}/scgi;
  server {{
    listen 127.0.0.1:{port} ssl;
    server_name localhost;
    ssl_certificate {root}/cert.pem;
    ssl_certificate_key {root}/key.pem;
    {locations}
    location / {{ return 404; }}
  }}
}}
""")
            command = [shutil.which("nginx"), "-e", str(root / "error.log"), "-p", str(root) + "/", "-c", str(config)]
            subprocess.run([*command, "-t"], check=True, capture_output=True)
            server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                context = ssl.create_default_context(cafile=str(root / "cert.pem"))
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
                for _ in range(50):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        if server.poll() is not None:
                            self.fail("Isolated Nginx failed: " + server.stderr.read().decode())
                        time.sleep(0.1)
                for path in ("/install", "/install.sh"):
                    with opener.open(f"https://localhost:{port}{path}", timeout=5) as response:
                        self.assertEqual(response.headers["Content-Type"], "text/plain; charset=utf-8")
                        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                        self.assertEqual(response.headers["Cache-Control"], "no-cache")
                        body = response.read()
                        self.assertEqual(hashlib.sha256(body).hexdigest(), hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
                        subprocess.run(["bash", "-n"], input=body, check=True)
                for path in ("/install/anything", "/not-a-script"):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(f"https://localhost:{port}{path}", timeout=5)
                    self.assertEqual(error.exception.code, 404)
                request = urllib.request.Request(f"https://localhost:{port}/install", data=b"unwanted", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(request, timeout=5)
                self.assertEqual(error.exception.code, 403)
                # The bootstrap's normal CA trust must reject this private test
                # certificate; only the isolated test client explicitly trusts it.
                untrusted = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
                with self.assertRaises(urllib.error.URLError) as error:
                    untrusted.open(f"https://localhost:{port}/install", timeout=5)
                self.assertIsInstance(error.exception.reason, ssl.SSLCertVerificationError)
            finally:
                server.terminate()
                server.wait(timeout=10)
                server.stderr.close()


if __name__ == "__main__":
    unittest.main()
