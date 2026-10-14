import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import time
import unittest


def action_scripts(name, expected):
    action = (Path(__file__).resolve().parents[1] / ".github/actions" / name / "action.yml").read_text()
    scripts = re.findall(r"^      run: \|\n((?:        [^\n]*\n|\n)+)", action, re.MULTILINE)
    if len(scripts) != expected:
        raise ValueError(f"Expected {expected} Bash script(s) in {name}")
    return list(map(textwrap.dedent, scripts))


def run_bash(script, cwd, env):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def image_id(image):
    return hashlib.sha256(image.encode()).hexdigest()[:12]


class ActionWiringTest(unittest.TestCase):
    """The script tests set environment variables directly; check that the action inputs feed them."""

    def action(self, name):
        return (Path(__file__).resolve().parents[1] / ".github/actions" / name / "action.yml").read_text()

    def test_inputs_feed_the_script_environment(self):
        pre_pull = self.action("pre-pull-docker-images")
        self.assertRegex(pre_pull, r"(?m)^  prepare-report:\n(?:    .*\n)*?    default: \"false\"\n")
        self.assertIn("        PREPARE_REPORT: ${{ inputs.prepare-report }}\n", pre_pull)
        report = self.action("pre-pull-docker-images-report")
        self.assertRegex(report, r"(?m)^  fail-on-error:\n(?:    .*\n)*?    default: \"false\"\n")
        self.assertIn("        FAIL_ON_ERROR: ${{ inputs.fail-on-error }}\n", report)


class PrePullActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect_script, cls.pull_script = action_scripts("pre-pull-docker-images", 2)

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
        # FAKE_DOCKER_NOISE: extra stdout; FAKE_DOCKER_BLOCK: wait while this file exists (for FAKE_DOCKER_BLOCK_IMAGE);
        # FAKE_DOCKER_FAIL: exit 3 for images containing this text.
        docker = self.bin / "docker"
        docker.write_text(
            r"""#!/usr/bin/env bash
printf 'docker %s\n' "$*"
printf 'docker diagnostic\n' >&2
[[ -z "${FAKE_DOCKER_NOISE:-}" ]] || printf '%b\n' "$FAKE_DOCKER_NOISE"
if [[ -n "${FAKE_DOCKER_BLOCK:-}" && "$*" == *"${FAKE_DOCKER_BLOCK_IMAGE:-}"* ]]; then
  while [[ -e "$FAKE_DOCKER_BLOCK" ]]; do sleep 0.02; done
fi
printf '%s\n' "$*" >> "$FAKE_DOCKER_COMPLETIONS"
[[ -z "${FAKE_DOCKER_FAIL:-}" || "$*" != *"$FAKE_DOCKER_FAIL"* ]] || exit 3
"""
        )
        docker.chmod(0o700)

    def dockerfile(self, name, content):
        path = self.workspace / "dockerfiles" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())

    def run_script(self, script, env=None, check=True):
        result = run_bash(script, self.workspace, self.env if env is None else env)
        if check:
            result.check_returncode()
        return result

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

    @property
    def reports_dir(self):
        return self.runner_temp / "pre-pull-docker-images-reports"

    def wait_for_statuses(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if len(list(self.reports_dir.glob("*.status"))) == count:
                return
            time.sleep(0.02)
        self.fail("Background pull reports did not complete")

    def test_reports_record_log_status_and_start_for_every_pull(self):
        images = ("redis:7.2", "nginx:1.27", "my-registry.example:5000/team/app:1.0")
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.dockerfile("Dockerfile.nginx", "FROM nginx:1.27\n")
        self.dockerfile("Dockerfile.app", "FROM my-registry.example:5000/team/app:1.0\n")
        self.collect()

        # an unrelated file in the checkout that a malicious repository could point a symlink at
        victim = self.root / "shell-profile"
        victim.write_text("must stay unchanged\n")
        (self.workspace / "pre-pull-docker-images-reports").symlink_to(victim)

        result = self.run_script(self.pull_script, {**self.env, "PREPARE_REPORT": "True", "FAKE_DOCKER_FAIL": "nginx"})
        self.wait_for_statuses(3)

        self.assertEqual(result.stderr, "")
        for image in images:
            self.assertIn(f"Pre-pulling {image} in background (report {image_id(image)})\n", result.stdout)
        self.assertEqual((self.reports_dir / "format").read_text(), "1\n")
        self.assertEqual(self.reports_dir.stat().st_mode & 0o777, 0o700)
        for image in images:
            base = self.reports_dir / image_id(image)
            self.assertRegex(base.with_suffix(".meta").read_text(), rf"^\d+\t{re.escape(image)}\n$")
            expected_exit = 3 if image == "nginx:1.27" else 0
            self.assertRegex(base.with_suffix(".status").read_text(), rf"^{expected_exit} \d+\n$")
            self.assertIn(f"docker pull -- {image}\n", base.with_suffix(".log").read_text())
        # no temp leftovers, nothing outside the private reports directory, nothing in the checkout
        self.assertEqual(
            sorted(path.name for path in self.reports_dir.iterdir()),
            sorted(["format"] + [f"{image_id(image)}.{ext}" for image in images for ext in ("meta", "log", "status")]),
        )
        self.assertCountEqual(self.runner_temp.iterdir(), [self.images_file, self.reports_dir])
        self.assertEqual(victim.read_text(), "must stay unchanged\n")

    def test_reports_rerun_clears_the_previous_result_while_running(self):
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.collect()
        env = {**self.env, "PREPARE_REPORT": "true"}
        self.run_script(self.pull_script, env)
        self.wait_for_statuses(1)

        block = self.root / "block"
        block.touch()
        self.run_script(self.pull_script, {**env, "FAKE_DOCKER_BLOCK": str(block)})
        base = self.reports_dir / image_id("redis:7.2")
        self.assertTrue(base.with_suffix(".meta").exists())
        self.assertFalse(base.with_suffix(".status").exists(), "a running pull must not show the previous result")
        block.unlink()
        self.wait_for_statuses(1)

    def test_reports_disabled_unless_true(self):
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.collect()
        for invocation, value in enumerate(("", "false", "banana", "1", "yes"), start=1):
            with self.subTest(prepare_report=value):
                result = self.run_script(self.pull_script, {**self.env, "PREPARE_REPORT": value})
                self.wait_for_pulls(invocation)
                self.assertEqual(result.stdout, "No registry login.\nPre-pulling redis:7.2 in background\n")
                self.assertEqual(list(self.runner_temp.iterdir()), [self.images_file])

    def test_reports_fall_back_to_discarding_output_if_the_directory_is_not_ours(self):
        self.dockerfile("Dockerfile.redis", "FROM redis:7.2\n")
        self.collect()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.reports_dir.symlink_to(elsewhere)

        result = self.run_script(self.pull_script, {**self.env, "PREPARE_REPORT": "true"})
        self.wait_for_pulls(1)

        self.assertIn("::warning::Cannot use ", result.stdout)
        self.assertIn("Pre-pulling redis:7.2 in background\n", result.stdout)
        self.assertEqual(list(elsewhere.iterdir()), [])


class PrePullReportActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.report_script,) = action_scripts("pre-pull-docker-images-report", 1)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gha-testcontainers-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runner_temp = self.root / "runner-temp"
        self.runner_temp.mkdir()
        self.reports_dir = self.runner_temp / "pre-pull-docker-images-reports"
        self.summary = self.root / "step-summary"
        self.env = {
            **os.environ,
            "RUNNER_TEMP": str(self.runner_temp),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "FAIL_ON_ERROR": "false",
        }

    def record(self, image, status=None, log=None, age=5):
        """Write what the pre-pull action records: image started `age` seconds ago, finished as `status` ('exit end-offset')."""
        self.reports_dir.mkdir(exist_ok=True)
        (self.reports_dir / "format").write_text("1\n")
        base = self.reports_dir / image_id(image)
        (self.reports_dir / f"{base.name}.meta").write_text(f"{int(time.time()) - age}\t{image}\n")
        if status is not None:
            (self.reports_dir / f"{base.name}.status").write_text(status)
        if log is not None:
            (self.reports_dir / f"{base.name}.log").write_bytes(log if isinstance(log, bytes) else log.encode())

    def report(self, **env):
        return run_bash(self.report_script, self.root, {**self.env, **env})

    def summary_text(self):
        return self.summary.read_text() if self.summary.exists() else ""

    def test_reports_pulled_failed_running_and_unknown_pulls(self):
        now = int(time.time())
        self.record("redis:7.2", f"0 {now - 5 + 7}\n", "Status: Downloaded newer image for redis:7.2\n")
        self.record("nginx:1.27", f"3 {now - 5 + 2}\n", "Error response from daemon: manifest unknown\n")
        self.record("postgres:17", None, "Pulling fs layer\n")
        self.record("alpine:3", "garbage\n", "")

        result = self.report()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("::group::✅ pulled - redis:7.2 (7s)\n| Status: Downloaded newer image for redis:7.2\n::endgroup::\n", result.stdout)
        self.assertIn("::group::❌ failed (exit 3) - nginx:1.27 (2s)\n| Error response from daemon: manifest unknown\n", result.stdout)
        self.assertRegex(result.stdout, r"::group::⏳ still running - postgres:17 \(running for \d+s\)\n\| Pulling fs layer\n")
        self.assertIn("::group::❓ unknown - alpine:3 (-)\n| (no output)\n", result.stdout)
        self.assertIn("Pre-pull report: 1 pulled, 1 failed, 1 still running, 1 unknown\n", result.stdout)

        summary = self.summary_text()
        self.assertRegex(summary, r"^### Pre-pulled Docker images \(report at \d\d:\d\d:\d\d UTC\)\n\n")
        self.assertIn("| `redis:7.2` | ✅ pulled | 7s |\n", summary)
        self.assertIn("| `nginx:1.27` | ❌ failed (exit 3) | 2s |\n", summary)
        self.assertRegex(summary, r"\| `postgres:17` \| ⏳ still running \| running for \d+s \|\n")
        # rows are sorted by image name; logs are only added to the summary for pulls that did not succeed
        self.assertLess(summary.index("`alpine:3`"), summary.index("`nginx:1.27`"))
        self.assertIn("manifest unknown", summary)
        self.assertIn("Pulling fs layer", summary)
        self.assertNotIn("Downloaded newer image", summary)

    def test_no_data_notice_and_foreign_format_do_not_fail(self):
        result = self.report()
        self.assertEqual(result.returncode, 0)
        self.assertIn("set 'prepare-report: true'", result.stdout)

        self.reports_dir.mkdir()
        (self.reports_dir / "format").write_text("2\n")
        result = self.report()
        self.assertEqual(result.returncode, 0)
        self.assertIn("::warning::Unsupported pre-pull report format", result.stdout)

        (self.reports_dir / "format").write_text("1\n")
        result = self.report()
        self.assertEqual(result.returncode, 0)
        self.assertIn("No pre-pulled images recorded", result.stdout)
        self.assertEqual(self.summary_text(), "")

    def test_symlinked_report_directory_is_not_followed(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "format").write_text("1\n")
        self.reports_dir.symlink_to(elsewhere)
        result = self.report()
        self.assertEqual(result.returncode, 0)
        self.assertIn("No pre-pull report data", result.stdout)

    def test_pull_output_cannot_inject_workflow_commands_or_break_the_summary(self):
        filler = b"\n".join(b"filler line %d" % i for i in range(100)) + b"\n"
        hostile = (
            "::error::boom\r::add-mask::secret\n"
            "\x1b[31mred\x1b[0m ```\n"
            "```\n"
            "</details>\n"
            "::stop-commands::x\n"
            "non-ascii: \xe9 \xff\n"
        ).encode("latin-1")
        now = int(time.time())
        self.record("redis:7.2", f"1 {now}\n", filler + hostile)
        # files that are not ours are ignored
        (self.reports_dir / "evil;id.meta").write_text(f"{now}\tevil:1\n")
        (self.reports_dir / ("a" * 12 + ".meta")).write_text("not-a-number\tbad:1\n")

        result = self.report()

        self.assertEqual(result.returncode, 0, result.stderr)
        for text in (result.stdout, self.summary_text()):
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\r", text)
            self.assertNotIn("evil", text)
            self.assertNotIn("bad:1", text)
            self.assertNotIn("filler line 0\n", text, "only the tail of the log is shown")
            self.assertIn("| filler line 99\n", text)
        # the only workflow commands are the report's own groups
        commands = [line for line in result.stdout.splitlines() if line.startswith("::")]
        self.assertEqual(commands, ["::group::❌ failed (exit 1) - redis:7.2 (5s)", "::endgroup::"])
        # injected text is neutralised by the prefix and cannot be told apart from ordinary log text
        for injected in ("::error::boom", "::add-mask::secret", "::stop-commands::x"):
            self.assertIn(f"| {injected}", result.stdout)
        # the tail is capped
        self.assertLessEqual(sum(line.startswith("| ") for line in result.stdout.splitlines()), 30)
        # in the summary the log stays inside its own code fence
        summary_lines = self.summary_text().splitlines()
        self.assertEqual([line for line in summary_lines if line.startswith("```")], ["```", "```"])
        self.assertIn("| ```", summary_lines)
        self.assertIn("| </details>", summary_lines)
        self.assertEqual(summary_lines.count("</details>"), 1)

    def test_fail_on_error_only_fails_for_failed_pulls(self):
        now = int(time.time())
        self.record("redis:7.2", f"0 {now}\n", "")
        self.record("postgres:17", None, "")
        for value in ("false", "banana", "true"):
            self.assertEqual(self.report(FAIL_ON_ERROR=value).returncode, 0, value)

        self.record("nginx:1.27", f"3 {now}\n", "")
        self.assertEqual(self.report(FAIL_ON_ERROR="false").returncode, 0)
        result = self.report(FAIL_ON_ERROR="TRUE")
        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::1 Docker image pre-pull(s) failed\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
