import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import time
import unittest


class PrePullActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        action = (Path(__file__).resolve().parents[1] / ".github/actions/pre-pull-docker-images/action.yml").read_text()
        scripts = re.findall(r"^      run: \|\n((?:        [^\n]*\n|\n)+)", action, re.MULTILINE)
        if len(scripts) != 2:
            raise ValueError("Expected the action's collect and pull Bash scripts")
        cls.collect_script, cls.pull_script = map(textwrap.dedent, scripts)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gha-testcontainers-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / "workspace"
        self.runner_temp = self.root / "runner-temp"
        self.bin = self.root / "bin"
        for directory in (self.workspace, self.runner_temp, self.bin):
            directory.mkdir()
        self.output = self.root / "github-output"
        self.images_file = self.runner_temp / "pre-pull-docker-images.txt"
        self.completions = self.root / "docker-completions"
        self.env = {
            **os.environ,
            "RUNNER_TEMP": str(self.runner_temp),
            "GITHUB_OUTPUT": str(self.output),
            "DOCKERFILE_PATHS": "dockerfiles",
            "IMAGES_FILE": str(self.images_file),
            "REGISTRY": "docker.io",
            "REGISTRY_LOGIN": "",
            "REGISTRY_PASSWORD": "",
            "FAKE_DOCKER_COMPLETIONS": str(self.completions),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
        }
        docker = self.bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'docker %s\\n' \"$*\"\n"
            "printf 'docker diagnostic\\n' >&2\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_COMPLETIONS\"\n"
        )
        docker.chmod(0o700)

    def dockerfile(self, name, content):
        path = self.workspace / "dockerfiles" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())

    def run_script(self, script, env=None, check=True):
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
            cwd=self.workspace,
            env=self.env if env is None else env,
            capture_output=True,
            text=True,
            timeout=10,
            check=check,
        )

    def collect(self):
        self.output.write_text("")
        result = self.run_script(self.collect_script)
        return result, self.images_file.read_text().splitlines()

    def test_first_plain_from_line_is_collected(self):
        cases = (
            ("FROM redis:7.2\n", "redis:7.2"),
            ("# comment\r\n  fRoM redis:7.2\r\n", "redis:7.2"),
            ("FROM alpine:3\nFROM nginx:1.27\n", "alpine:3"),
            ("FROM busybox", "busybox"),
            (f"FROM redis@sha256:{'a' * 64}\n", f"redis@sha256:{'a' * 64}"),
        )
        for content, expected in cases:
            with self.subTest(content=content):
                self.dockerfile("Dockerfile.test", content)
                _, images = self.collect()
                self.assertEqual(images, [expected])
                self.assertIn("found=true\n", self.output.read_text())

    def test_unsupported_from_lines_skip_the_dockerfile(self):
        for content in (
            "# comment\nRUN true\n",
            "FROM\nFROM redis:7.2\n",
            "FROM scratch\nFROM redis:7.2\n",
            "FROM SCRATCH\nFROM redis:7.2\n",
            "FROM $BASE\nFROM redis:7.2\n",
            "FROM --platform=linux/amd64 alpine\nFROM redis:7.2\n",
            "FROM alpine AS builder\nFROM builder\n",
            "FROM --platform=$BUILDPLATFORM golang AS builder\nFROM builder\n",
            "FROM invalid;reference\nFROM redis:7.2\n",
            "FROM redis:7.2 # inline comments are not supported\n",
        ):
            with self.subTest(content=content):
                self.dockerfile("Dockerfile.test", content)
                _, images = self.collect()
                self.assertEqual(images, [])
                self.assertEqual(self.output.read_text(), "found=false\n")

    def test_image_character_whitelist_accepts_names_tags_registries_and_digests(self):
        for image in (
            "redis",
            "my-registry.example:5000/team/my_image:Release_1.2-3",
            "[::1]:5000/team/redis:7.2",
            "redis@sha256:abc123",
            "redis:7.2@sha256:ABC123",
            "redis@sha3-256:abc123",
        ):
            with self.subTest(image=image):
                self.dockerfile("Dockerfile.test", f"FROM {image}\n")
                _, images = self.collect()
                self.assertEqual(images, [image])

    def test_image_character_whitelist_rejects_unsafe_characters_and_invalid_states(self):
        for image in (
            "--help",
            "/redis",
            "redis;touch",
            "$(id)",
            "`id`",
            "'redis'",
            "redis\\file",
            "redis|id",
            "redis&whoami",
            "redis:tag+suffix",
            "redis:\x1b",
            "redis:",
            "redis/",
            "redis@",
            "redis@sha256",
            "redis@sha256:",
            "redis@sha;256:abc",
            "redis@sha256:xyz",
            "redis@sha256:abc:def",
            "redis@sha256:abc@sha256:def",
        ):
            with self.subTest(image=image):
                self.dockerfile("Dockerfile.test", f"FROM {image}\n")
                _, images = self.collect()
                self.assertEqual(images, [])
                self.assertEqual(self.output.read_text(), "found=false\n")

    def test_recursive_discovery_deduplication_and_dockerignore_exclusion(self):
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.dockerfile("nested/Dockerfile.redis", "FROM redis:7.2\n")
        self.dockerfile("nested/Dockerfile.nginx", "FROM nginx:1.27\n")
        self.dockerfile("Dockerfile.redis.dockerignore", "FROM postgres:17\n")
        _, images = self.collect()
        self.assertEqual(images, ["nginx:1.27", "redis:7.2"])

    def test_missing_paths_are_reported_and_skipped(self):
        result, images = self.collect()
        self.assertEqual(images, [])
        self.assertIn("not found - skipping", result.stdout)
        self.assertEqual(self.output.read_text(), "found=false\n")

    def wait_for_pulls(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.completions.exists() and len(self.completions.read_text().splitlines()) == count:
                return
            time.sleep(0.02)
        self.fail("Background Docker pulls did not complete")

    def test_background_pulls_discard_output_and_do_not_write_logs(self):
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.dockerfile("Dockerfile.nginx", "FROM nginx:1.27\n")
        self.collect()
        victim = self.root / "shell-profile"
        victim.write_text("must stay unchanged\n")
        for name in ("docker-pull-redis-7-2.log", "docker-pull-nginx-1-27.log"):
            (self.workspace / name).symlink_to(victim)

        for invocation in (1, 2):
            result = self.run_script(self.pull_script)
            self.wait_for_pulls(invocation * 2)
            self.assertEqual(victim.read_text(), "must stay unchanged\n")
            self.assertEqual(list(self.runner_temp.iterdir()), [self.images_file])
            self.assertCountEqual(
                self.completions.read_text().splitlines(),
                ["pull -- nginx:1.27", "pull -- redis:7.2"] * invocation,
            )
            self.assertEqual(
                result.stdout,
                "No registry login.\n"
                "Pre-pulling nginx:1.27 in background\n"
                "Pre-pulling redis:7.2 in background\n",
            )
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
