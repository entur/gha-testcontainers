# 🚧 Experimental 🚧

# gha-testcontainers

This repo tries to help enable two goals for users of testcontainers:

1. **Faster builds** – pull the Testcontainers images in the background so it runs in parallel to JDK, dependency cache and build setup.
2. **Automatic image bumps** – create `Dockerfile`s instead of inlining image names in code. So that Dependabot can do its job.

In a nutshell what we are trying to do it to stop waiting for testcontainers, i.e. logs like

```
: ✔︎ Docker server version should be at least 1.6.0
: Pulling docker image: postgis/postgis:17-3.5. Please be patient; this may take some time but only needs to be done once.
: Starting to pull image
: Pulling image layers:  0 pending,  0 downloaded,  0 extracted, (0 bytes/0 bytes)
...
: Pulling image layers:  0 pending, 18 downloaded, 18 extracted, (208 MB/208 MB)
: Pull complete. 18 layers, pulled in 7s (downloaded 208 MB at 29 MB/s)
```
so this can save from **5 to 30 seconds per build**, depending on the number and size of images. It does not use any cache.

## Features
The project has three parts:

- **GitHub Action** – pre-pulls the first plain `FROM` image from each simple Dockerfile, in the background.
- **Java library** – resolves an image name from the `FROM` line of a Dockerfile on the classpath, so test code
  uses exactly the image CI pre-pulled and Dependabot bumped.
- **Dependabot config example** – Copy-paste ready

# Usage
## Dockerfiles
Create a directory with very simple Dockerfiles, preferably

> Dockerfile.myapp

e.g. `src/test/resources/testcontainers/Dockerfile.redis`:

```dockerfile
FROM redis:7.2
```
or with digest

```dockerfile
FROM redis@sha256:...
```

The action reads only the first `FROM` line, in the form `FROM image[:tag][@digest]`.
It does not build Dockerfiles or support builders/stage aliases (`AS`), flags, build args or inline comments.
If that line is unsupported, uses `scratch` (case-insensitive), or fails the image-character whitelist,
the Dockerfile is skipped; later `FROM` lines are not considered. Blank lines and standalone comments are fine.
The Java parser is more permissive, but both read the same image from simple Dockerfiles.

## GitHub Action

Call `pre-pull-docker-images` right after checkout, before JDK and caches are restored:

```yaml
- uses: actions/checkout@v7
- name: Pre-pull Docker images in background
  uses: entur/gha-testcontainers/.github/actions/pre-pull-docker-images@v1
  with:
    dockerfile-paths: src/test/resources/testcontainers
- name: Set up Java 25
  uses: actions/setup-java@de7274f081f381c8f8158605e0321c36c376e2e6 # v6.0.1
  with:
    java-version: 25
    distribution: liberica
- name: Restore Maven repository cache
  id: maven-cache-restore
  uses: actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
  with:
    path: ~/.m2/repository
    key: ${{ runner.os }}-maven-${{ hashFiles('**/pom.xml') }}
    restore-keys: |
      ${{ runner.os }}-maven-
...

```

or the equivalent for Gradle.

| Input                | Required | Description                                                                                  |
|----------------------|----------|----------------------------------------------------------------------------------------------|
| `dockerfile-paths`   | yes      | Whitespace/newline-separated paths searched recursively for files named `Dockerfile*`.       |
| `registry`           | no       | Registry address to log in to (e.g. `ghcr.io`). Default `docker.io`.                         |
| `registry-login`     | no       | Registry username. Login only happens if both login and password are set.                    |
| `registry-password`  | no       | Registry password or access token.                                                           |

| Output   | Description                                          |
|----------|------------------------------------------------------|
| `images` | Newline-separated list of images that were pre-pulled. |

Pulls run detached - they continue in the background after the step ends. 

## Bootstrapping testcontainers in tests
Add a parser to get the right image into testcontainers. Alternatively write your own.

```java
// classpath resource: src/test/resources/testcontainers/Dockerfile.redis
String image = DockerfileImages.fromResource("testcontainers/Dockerfile.redis");
var redis = new GenericContainer<>(DockerImageName.parse(image));
```

Get our parser from `no.entur.testcontainers:dockerfile-helper:1.0.1-SNAPSHOT`, alternatively directly copy the class [`DockerfileImages.java`](src/main/java/no/entur/testcontainers/dockerfile/DockerfileImages.java).That avoids adding and versioning another test artifact.

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

## Permissions and secrets

The action needs **no** `GITHUB_TOKEN` permissions and no secrets: pulling public images is anonymous.

- Only pass `registry-login`/`registry-password` if you need private images or higher rate limits, and then
  use a **read-only pull token**, not a personal password. Pass them to this step only, never as workflow-wide `env`.
  For `ghcr.io`, `github.actor` with `secrets.GITHUB_TOKEN` and `packages: read` avoids a stored secret altogether.
- Credentials reach the login via environment variables and `--password-stdin` (never on a command line or
  interpolated into the script), and are written to the runner's Docker config for the lifetime of the job, as
  the background pulls need them. Use ephemeral/GitHub-hosted runners, or log out yourself on shared runners.
- Dockerfile content is treated as **untrusted** (e.g. from a pull request). A stateful character whitelist allows
  letters, digits and `. _ / : - [ ]` in image names/tags, letters, digits and `_ + . -` in digest algorithms,
  and only hexadecimal characters in the digest. References cannot start with an option or contain shell syntax,
  whitespace or control characters. This is not a full Docker/OCI grammar validator. Logged values have control
  characters stripped, the `images` output uses a random delimiter, and images are passed to `docker pull --`
  so they can never be parsed as options.
- Use `actions/checkout` with `persist-credentials: false` unless later steps push to git.
- The action does not write files into the checkout. Collected image lists are stored under `$RUNNER_TEMP`,
  and background pull output goes to `/dev/null`, so repository symlinks cannot redirect pull logs into runner files.
- Pin the action to a commit SHA for supply-chain safety.
