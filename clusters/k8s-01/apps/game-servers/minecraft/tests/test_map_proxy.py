"""Exercise the deployed Nginx config with HTTP auth and BlueMap fixtures.

From the repository root:
  nix-shell -p 'python3.withPackages (ps: [ ps.pyyaml ])' nginx --run \
    'python3 -m unittest discover -s clusters/k8s-01/apps/game-servers/minecraft/tests -v'

Set RENDERED_MANIFESTS to a Helm-rendered YAML file to also verify the Services,
route, metrics discovery and volume isolation.
"""

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

import yaml


APP = Path(__file__).resolve().parents[1]


class AuthFixture(BaseHTTPRequestHandler):
    available = True

    def do_GET(self):
        if not type(self).available:
            self.send_response(503)
        elif self.path == "/auth":
            valid = self.headers.get("Cookie") == "mc_auth_sid=valid"
            self.send_response(200 if valid else 401)
            if valid:
                self.send_header("X-Minecraft-UUID", "verified-uuid")
                self.send_header("X-Minecraft-Username", "VolcanPlayer")
        elif self.path == "/login":
            self.send_response(200)
            self.send_header("Set-Cookie", "mc_auth_sid=pending; Path=/; Secure; HttpOnly; SameSite=Lax")
        else:
            self.send_response(404)
        self.end_headers()

    def do_POST(self):
        self.send_response(302 if self.path in {"/logout", "/logout/all"} else 404)
        self.send_header("Set-Cookie", "mc_auth_sid=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax")
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


class MapFixture(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        type(self).requests.append(self.path)
        payload = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        # BlueMap's default caching must never leak through the proxy.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("CDN-Cache-Control", "max-age=60")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class MapProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nginx = os.environ.get("NGINX") or shutil.which("nginx")
        if not nginx:
            raise RuntimeError("nginx is required; see this file's docstring")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        (folder / "logs").mkdir()

        ports = []
        for fixture in (AuthFixture, MapFixture):
            server = ThreadingHTTPServer(("127.0.0.1", 0), fixture)
            cls.addClassCleanup(server.server_close)
            cls.addClassCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            ports.append(server.server_port)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]

        config = (APP / "configs/map/nginx.conf").read_text()
        # Only replace local addresses and file paths; exercise production routing.
        config = config.replace("listen 8123;", f"listen 127.0.0.1:{cls.port};")
        config = config.replace("127.0.0.1:8200", f"127.0.0.1:{ports[0]}")
        config = config.replace("127.0.0.1:8100", f"127.0.0.1:{ports[1]}")
        config = config.replace("/tmp/", str(folder) + "/")
        config = config.replace("/etc/nginx/map/logout.html", str(APP / "configs/map/logout.html"))
        config = config.replace("/dev/stdout", str(folder / "access.log"))
        config = config.replace("/dev/stderr", str(folder / "error.log"))
        config_path = folder / "nginx.conf"
        config_path.write_text(config)
        args = [nginx, "-e", str(folder / "error.log"), "-p", str(folder), "-c", str(config_path)]
        subprocess.run(args + ["-t"], check=True, capture_output=True)
        cls.process = subprocess.Popen(args + ["-g", "daemon off;"], stdout=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_nginx)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError((folder / "error.log").read_text())
            try:
                if cls.request("/healthz")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.02)
        else:
            raise RuntimeError("Nginx did not become ready")

    @classmethod
    def stop_nginx(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)

    @classmethod
    def request(cls, path, *, cookie=None, method="GET", headers=None):
        request_headers = {"Host": "mc-map.volcan.cloud", "X-Envoy-External-Address": "203.0.113.10"}
        request_headers.update(headers or {})
        if cookie:
            request_headers["Cookie"] = cookie
        connection = HTTPConnection("127.0.0.1", cls.port, timeout=3)
        try:
            connection.request(method, path, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def setUp(self):
        AuthFixture.available = True
        MapFixture.requests.clear()

    def test_anonymous_map_data_requires_login(self):
        for path in ("/", "/settings.json", "/maps/overworld/tiles/0.json", "/live/players.json", "/assets/test.png"):
            with self.subTest(path=path):
                status, headers, _ = self.request(path)
                self.assertEqual(status, 302)
                self.assertEqual(headers["Location"], "/authentication-outpost/login")
                self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(MapFixture.requests, [])

    def test_spoofed_identity_and_pending_or_invalid_cookie_are_rejected(self):
        for cookie in (None, "mc_auth_sid=invalid", "mc_auth_sid=pending"):
            status, _, _ = self.request("/maps/overworld/tiles/0.json", cookie=cookie, headers={
                "X-Minecraft-UUID": "spoofed", "X-Minecraft-Username": "admin", "X-Minecraft-Loggedin": "true",
            })
            self.assertEqual(status, 302)
        self.assertEqual(MapFixture.requests, [])

    def test_valid_session_overwrites_identity_and_private_cache_headers(self):
        status, headers, body = self.request("/settings.json", cookie="mc_auth_sid=valid", headers={
            "X-Minecraft-UUID": "spoofed", "X-Minecraft-Username": "admin", "Authorization": "Bearer spoofed",
        })
        self.assertEqual(status, 200)
        forwarded = {key.lower(): value for key, value in json.loads(body).items()}
        self.assertEqual(forwarded["x-minecraft-uuid"], "verified-uuid")
        self.assertEqual(forwarded["x-minecraft-username"], "VolcanPlayer")
        self.assertEqual(forwarded["x-minecraft-loggedin"], "true")
        self.assertEqual(forwarded["x-forwarded-proto"], "https")
        self.assertNotIn("cookie", forwarded)
        self.assertNotIn("authorization", forwarded)
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(headers["CDN-Cache-Control"], "no-store")

    def test_login_polling_and_post_logout_routes(self):
        status, headers, _ = self.request("/authentication-outpost/login")
        self.assertEqual(status, 200)
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertEqual(self.request("/authentication-outpost/auth")[0], 401)
        self.assertEqual(self.request("/authentication-outpost/auth", cookie="mc_auth_sid=valid")[0], 200)
        for path in ("/authentication-outpost/logout", "/authentication-outpost/logout/all"):
            status, headers, _ = self.request(path, method="POST", cookie="mc_auth_sid=valid")
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "/")
            self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIn(b"method=\"post\"", self.request("/logout")[2])
        self.assertEqual(MapFixture.requests, [])

    def test_internal_auth_endpoint_cannot_be_called_directly(self):
        self.assertEqual(self.request("/_session")[0], 404)
        self.assertEqual(self.request("/_session", cookie="mc_auth_sid=valid")[0], 404)

    def test_auth_service_failure_does_not_reach_map(self):
        AuthFixture.available = False
        try:
            self.assertEqual(self.request("/settings.json", cookie="mc_auth_sid=valid")[0], 500)
            self.assertEqual(MapFixture.requests, [])
        finally:
            AuthFixture.available = True


@unittest.skipUnless(os.environ.get("RENDERED_MANIFESTS"), "set RENDERED_MANIFESTS to verify Helm output")
class RenderedMapTest(unittest.TestCase):
    def test_network_and_mount_boundaries(self):
        resources = list(yaml.safe_load_all(Path(os.environ["RENDERED_MANIFESTS"]).read_text()))
        resources = [resource for resource in resources if resource]
        services = {r["metadata"]["name"]: r for r in resources if r["kind"] == "Service"}
        game = services["minecraft-volcan"]
        self.assertEqual(game["spec"]["type"], "LoadBalancer")
        self.assertEqual([p["port"] for p in game["spec"]["ports"]], [25565])
        for name in ("minecraft-volcan-map", "minecraft-volcan-metrics"):
            self.assertEqual(services[name]["spec"]["type"], "ClusterIP")
        for service in services.values():
            self.assertFalse({8100, 8200} & {p["port"] for p in service["spec"]["ports"]})
        route = next(r for r in resources if r["kind"] == "HTTPRoute")
        backend = route["spec"]["rules"][0]["backendRefs"][0]
        self.assertEqual((backend["name"], backend["port"]), ("minecraft-volcan-map", 8123))
        monitor = next(r for r in resources if r["kind"] == "ServiceMonitor")
        self.assertEqual(monitor["spec"]["selector"]["matchLabels"]["app.kubernetes.io/service"], "minecraft-volcan-metrics")
        deployment = next(r for r in resources if r["kind"] == "Deployment")
        containers = deployment["spec"]["template"]["spec"]["containers"]
        proxy = next(c for c in containers if c["name"] == "map-proxy")
        self.assertNotIn("/data", {m["mountPath"] for m in proxy["volumeMounts"]})
        self.assertTrue(proxy["securityContext"]["readOnlyRootFilesystem"])

    def test_backend_ports_are_not_allowed_by_network_policy(self):
        policy = yaml.safe_load((APP / "configs/netpol.yaml").read_text())["spec"]
        self.assertTrue(policy["enableDefaultDeny"]["ingress"])
        allowed_ports = {
            port["port"]
            for rule in policy["ingress"]
            for group in rule["toPorts"]
            for port in group["ports"]
        }
        self.assertEqual(allowed_ports, {"25565", "8123", "9100"})
        proxy_rule = next(rule for rule in policy["ingress"] if rule.get("fromEntities") == ["ingress"])
        self.assertEqual(proxy_rule["toPorts"][0]["ports"][0]["port"], "8123")


if __name__ == "__main__":
    unittest.main()
