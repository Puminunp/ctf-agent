import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import make_cfg  # noqa: F401  (puts the repo on sys.path)
from ctfagent.challenges import build_task
from ctfagent.config import EnvironmentConfig
from ctfagent.environment import EnvironmentError_, render_compose, target_image

CFG = EnvironmentConfig()


class RenderCompose(unittest.TestCase):
    def test_service_challenge_is_isolated(self):
        text = render_compose(CFG, "llmctf/2023q-pwn-puffin:latest")
        self.assertIn("internal: true", text)
        self.assertIn("image: llmctf/2023q-pwn-puffin:latest", text)
        for forbidden in ["docker.sock", "ports:", "privileged", "network_mode: host", "cap_add", "volumes:"]:
            self.assertNotIn(forbidden, text)
        self.assertIn("cap_drop: [ALL]", text)
        self.assertIn('user: "1000:1000"', text)
        self.assertIn("no-new-privileges", text)

    def test_challenge_without_target_has_no_network_at_all(self):
        text = render_compose(CFG, None)
        self.assertIn("network_mode: none", text)
        self.assertNotIn("target", text)
        self.assertNotIn("ctf_internal", text)

    def test_target_image_read_from_challenge_compose(self):
        d = Path(tempfile.mkdtemp())
        (d / "docker-compose.yml").write_text(
            "services:\n  s:\n    image: 'llmctf/x-web-y'\n    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n")
        self.assertEqual(target_image(d), "llmctf/x-web-y")

    def test_build_only_challenge_is_rejected_clearly(self):
        d = Path(tempfile.mkdtemp())
        (d / "docker-compose.yml").write_text("services:\n  s:\n    build: ./server\n")
        with self.assertRaises(EnvironmentError_):
            target_image(d)


class TaskServiceDetection(unittest.TestCase):
    def test_box_without_container_means_no_target(self):
        chal = SimpleNamespace(name="n", category="crypto", files=["a.txt"], server_name="crypto.chal.csaw.io",
                               port=None, container=False, description="Decrypt it. (was crypto.chal.csaw.io)")
        t = build_task("cry-x", chal, "target")
        self.assertEqual((t.target_host, t.allowed_hosts), (None, set()))

    def test_container_means_target(self):
        chal = SimpleNamespace(name="n", category="pwn", files=[], server_name="pwn.chal.csaw.io",
                               port=31140, container=True, description="x")
        t = build_task("pwn-x", chal, "target")
        self.assertEqual((t.target_host, t.target_port), ("target", 31140))


if __name__ == "__main__":
    unittest.main()
