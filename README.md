# 🚧 Experimental 🚧

# gha-testcontainers

This repo tries to help enable two goals for testcontainers-users:

1. **Faster builds** – pull the Testcontainers images in the background so it runs in parallel to JDK, dependency cache and build setup.
2. **Automatic image bumps** – create `Dockerfile`s instead of inlining image names in code. So that Dependabot can do its job.

## Features

- **Background pre-pull** – GitHub Action downloads all images detached from the step, overlapping with Java setup and dependency caching/resolution.
- **Dependabot-friendly** – one `Dockerfile.<name>` per image; Dependabot/Renovate bump the tag or digest. The Dockerfiles are never built.
- **Single source of truth** – the same Dockerfiles are read by CI (the action) and by test code (the Java library).
- **Tiny Java library** – resolve an image name from a classpath Dockerfile; a single class with no dependencies, Java 17+, so you can depend on it or simply copy it.
- **Safe parsing** – ignores `scratch`, `--platform` flags, `$VAR` and earlier build stages; supports tags and digests.
- **Configurable** – custom directories, file prefixes and classloaders; optional login to any registry (Docker Hub by default).

The project has three parts:

- **GitHub Action** – pre-pulls every image found in the Dockerfiles, in the background.
- **Java library** – resolves an image name from the `FROM` line of a Dockerfile on the classpath, so test code
  uses exactly the image CI pre-pulled and Dependabot bumped.
- **Dependabot config example ** – Copy-paste ready
  

## Layout

```
gha-testcontainers/
├── .github/actions/pre-pull-docker-images/action.yml   # the GitHub Action (composite)
├── src/           # the Java library (single Maven jar project, Java 17+, no runtime dependencies)
└── examples/maven # complete standalone Maven project: Dockerfiles, tests, workflow and Dependabot config
```

## Dockerfiles

One file per image, e.g. `src/test/resources/testcontainers/Dockerfile.redis`:

```dockerfile
FROM redis:7.2
```

Digests work too (`FROM redis@sha256:...`). Only plain `FROM image[:tag|@digest] [AS name]` lines are
supported. `FROM scratch`, `FROM --platform=...`, `FROM $VAR` and references to earlier build stages are ignored.

## GitHub Action

Call it right after checkout, before dependency caches are restored:

```yaml
- uses: actions/checkout@v4
- uses: entur/gha-testcontainers/.github/actions/pre-pull-docker-images@v1
  with:
    dockerfile-paths: src/test/resources/testcontainers
```

| Input                | Required | Description                                                                                  |
|----------------------|----------|----------------------------------------------------------------------------------------------|
| `dockerfile-paths`   | yes      | Whitespace/newline-separated paths searched recursively for files named `Dockerfile*`.       |
| `registry`           | no       | Registry address to log in to (e.g. `ghcr.io`). Default `docker.io`.                         |
| `registry-login`     | no       | Registry username. Login only happens if both login and password are set.                    |
| `registry-password`  | no       | Registry password or access token.                                                           |

| Output   | Description                                          |
|----------|------------------------------------------------------|
| `images` | Newline-separated list of images that were pre-pulled. |

Pulls run detached (`setsid` + `disown`), so they continue after the step ends; output goes to
`docker-pull-<image>.log` in the working directory. Missing paths and Dockerfiles without usable images
are skipped; if nothing is found the action is a no-op. See [`examples/maven/.github/workflows/ci.yml`](examples/maven/.github/workflows/ci.yml).

## Java library

```xml
<dependency>
  <groupId>no.entur.testcontainers</groupId>
  <artifactId>dockerfile-helper</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <scope>test</scope>
</dependency>
```

```java
// reads classpath:testcontainers/Dockerfile.redis
String image = DockerfileImages.get("redis");
var redis = new GenericContainer<>(DockerImageName.parse(image));

// custom directory / file name prefix: classpath:docker/Dockerfile-nginx
String nginx = DockerfileImages.in("docker").withPrefix("Dockerfile-").image("nginx");
```

Throws `IllegalStateException` if the file is missing or has no usable `FROM` line. Parsing rules match the
action. See the [standalone Maven example](examples/maven).

Alternatively, **skip the dependency and copy the class**: [`DockerfileImages.java`](src/main/java/no/entur/testcontainers/dockerfile/DockerfileImages.java)
is a single self-contained file that only uses the JDK. Drop it into your test sources (change the `package` as
needed) and use it exactly as above. That avoids adding and versioning another test artifact; the trade-off is
that fixes are not picked up automatically, so re-copy it if you need them. A trimmed-down copy that only handles
your own Dockerfile layout is fine too.

### Putting the files on the classpath

Place them under `src/test/resources/testcontainers/` (test code) or `src/main/resources/testcontainers/`
(if shipped, e.g. emulator helpers). Use the same directory for the action's `dockerfile-paths` and
Dependabot's `directory` (see [`examples/maven/.github/dependabot.yaml`](examples/maven/.github/dependabot.yaml)).

## Permissions and secrets

The action needs **no** `GITHUB_TOKEN` permissions and no secrets: pulling public images is anonymous.

- Declare `permissions: contents: read` (the example workflow does) - the action itself adds nothing to that.
- Only pass `registry-login`/`registry-password` if you need private images or higher rate limits, and then
  use a **read-only pull token**, not a personal password. Pass them to this step only, never as workflow-wide `env`.
  For `ghcr.io`, `github.actor` with `secrets.GITHUB_TOKEN` and `packages: read` avoids a stored secret altogether.
- Credentials reach the login via environment variables and `--password-stdin` (never on a command line or
  interpolated into the script), and are written to the runner's Docker config for the lifetime of the job, as
  the background pulls need them. Use ephemeral/GitHub-hosted runners, or log out yourself on shared runners.
- Dockerfile content is treated as **untrusted** (e.g. from a pull request): each image must match the
  [Docker/OCI reference grammar](https://github.com/distribution/reference/blob/main/reference.go)
  (`[domain[:port]/]path[:tag][@algorithm:hex]`: lowercase path components, tag of at most 128 characters, digest with
  at least 32 hex characters, repository name of at most 255 characters), which only permits letters, digits and
  `. _ - / : @ [ ]` in their defined positions; anything else is ignored. Logged values have control
  characters stripped (no workflow-command or log-line injection), the `images` output uses a random delimiter,
  and images are passed to `docker pull --` so they can never be parsed as options.
- Use `actions/checkout` with `persist-credentials: false` unless later steps push to git.
- The action does not read secrets, make network calls other than `docker pull`/`docker login`, or write outside
  `$RUNNER_TEMP` and the working directory (pull logs).
- Pin the action to a commit SHA for supply-chain safety.

## Keeping images up to date (Dependabot)

Dependabot's `docker` ecosystem understands `FROM` lines in files named `Dockerfile*`, so it bumps the
tag or digest in your test Dockerfiles with no extra tooling. Add to `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "docker"
    directory: "/src/test/resources/testcontainers"
    schedule:
      interval: "weekly"
    cooldown:
      default-days: 7
    groups:
      testcontainers:
        patterns:
          - "*"
    ignore:
      - dependency-name: "bitnamisecure/redis"
```

- `directory` must match where the Dockerfiles live (same as the action's `dockerfile-paths`) and starts with `/`.
  It is **not** recursive: add one entry per directory (or use `directories:` with globs).
- Dependabot picks up files whose name contains `Dockerfile` (e.g. `Dockerfile.redis`), so `Dockerfile.<name>` works out of the box.
- `groups` collects all image bumps into a single PR; `cooldown` delays brand-new releases.
- `ignore` is for images deliberately pinned (e.g. a known-bad `latest`); add a comment in the Dockerfile explaining why.
- Digest-pinned images (`FROM image@sha256:...`) are bumped too, as long as a tag is present
  (`FROM image:1.2@sha256:...`) - without a tag Dependabot has nothing to track.
- Each bump PR runs your normal CI, so the new image is verified by the integration tests (and pre-pulled by the action).
- Renovate works the same way via its `dockerfile` manager (set `fileMatch`/`managerFilePatterns` to include `Dockerfile.*`).

See [`examples/maven/.github/dependabot.yaml`](examples/maven/.github/dependabot.yaml).

## Development

```bash
cd java && mvn test
```
