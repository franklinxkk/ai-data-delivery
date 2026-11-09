import http.client
import http.cookiejar
import json
import socket
import tempfile
import threading
import unittest
import urllib.request

from workbench.service import Service
from workbench.serve import make_server


class BrowserEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service(self.temp.name)
        self.server = make_server(self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            self.response_headers = dict(response.getheaders())
            return response.status, response.read()
        finally:
            conn.close()

    def test_idle_browser_preconnection_cannot_block_real_navigation(self):
        idle = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3)
        try:
            status, body = self.get("/", {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
            self.assertEqual(status, 200)
            self.assertIn(b"knowledge.js", body)
        finally:
            idle.close()

    def test_top_level_link_allowed_but_cross_site_api_and_frames_remain_denied(self):
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        status, body = self.get("/", headers)
        self.assertEqual(status, 200)
        self.assertIn(b"session-token", body)
        status, _ = self.get("/api/knowledge/state", headers)
        self.assertEqual(status, 403)
        status, _ = self.get("/", {**headers, "Sec-Fetch-Dest": "iframe"})
        self.assertEqual(status, 403)
        status, _ = self.get("/", {**headers, "Sec-Fetch-Mode": "cors"})
        self.assertEqual(status, 403)

    def test_browser_download_cookie_only_reads_immutable_snapshot(self):
        self.service.knowledge.edit({"revision": 0, "operation_id": "download-asset", "asset": {"id": "vehicle", "kind": "entity", "name": "车辆"}})
        published = self.service.knowledge.publish({"revision": 1, "operation_id": "download-test", "draft": True})["result"]
        status, _ = self.get("/", {})
        self.assertEqual(status, 200)
        cookie = self.response_headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/api/knowledge/download/", cookie)
        headers = {"Cookie": cookie.split(";", 1)[0], "Sec-Fetch-Site": "same-origin"}
        status, body = self.get(published["download_url"], headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.service.knowledge.download(published["snapshot_id"]))
        self.assertTrue(body.startswith(b"PK"))
        self.assertEqual(int(self.response_headers["Content-Length"]), len(body))
        self.assertIn("attachment", self.response_headers["Content-Disposition"])
        for path in ("/api/knowledge/state", "/api/knowledge/source/absent"):
            self.assertEqual(self.get(path, headers)[0], 403)
        self.assertEqual(self.get(published["download_url"], {**headers, "Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.get(published["download_url"], {"Cookie": "workbench_download=wrong"})[0], 403)

    def test_two_local_projects_keep_independent_browser_download_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            other_service = Service(directory)
            other_server = make_server(other_service)
            thread = threading.Thread(target=other_server.serve_forever, daemon=True)
            thread.start()
            try:
                browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                snapshots = []
                for server, service in ((self.server, self.service), (other_server, other_service)):
                    service.knowledge.edit({"revision": 0, "operation_id": "session-asset", "asset": {"id": "term", "kind": "term", "name": "样例"}})
                    result = service.knowledge.publish({"revision": 1, "operation_id": "session-publish", "draft": True})["result"]
                    base = f"http://127.0.0.1:{server.server_port}"
                    with browser.open(base + "/", timeout=3) as response:
                        response.read()
                    snapshots.append((base + result["download_url"], service.knowledge.download(result["snapshot_id"])))
                # Both tabs remain usable after opening the second project's home.
                for url, expected in snapshots:
                    with browser.open(url, timeout=3) as response:
                        self.assertEqual(response.read(), expected)
            finally:
                other_server.shutdown()
                other_server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
