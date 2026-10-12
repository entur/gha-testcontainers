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
so this is an optimization which typically could save from 5s to 30s, depending on the number and size of images. It does not use any cache.

## Features
The project has three parts:

- **GitHub Action** – pre-pulls every image found in the Dockerfiles, in the background.
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

Digests work too (`FROM redis@sha256:...`). Only plain `FROM image[:tag|@digest] [AS name]` lines are
supported. `FROM scratch`, `FROM --platform=...`, `FROM $VAR` and references to earlier build stages are ignored.

## GitHub Action

Call it right after checkout, before JDK and caches are restored:

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
    server-id: entur-partner
    server-username: MAVEN_USERNAME
    server-password: MAVEN_PASSWORD
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

| Input                | Required | Description                                                                                  |
|----------------------|----------|----------------------------------------------------------------------------------------------|
| `dockerfile-paths`   | yes      | Whitespace/newline-separated paths searched recursively for files named `Dockerfile*`.       |
| `registry`           | no       | Registry address to log in to (e.g. `ghcr.io`). Default `docker.io`.                         |
| `registry-login`     | no       | Registry username. Login only happens if both login and password are set.                    |
| `registry-password`  | no       | Registry password or access token.                                                           |

| Output   | Description                                          |
|----------|------------------------------------------------------|
| `images` | Newline-separated list of images that were pre-pulled. |

Pulls run detached - they continue after the step ends.

## Java library
Add a Dockerfile parser to get the right image into testcontainers. Alternatively write your own.

```xml
<dependency>
  <groupId>no.entur.testcontainers</groupId>
  <artifactId>dockerfile-helper</artifactId>
  <version>1.0.1-SNAPSHOT</version>
  <scope>test</scope>
</dependency>
```

```java
// classpath resource: src/test/resources/testcontainers/Dockerfile.redis
String image = DockerfileImages.fromResource("testcontainers/Dockerfile.redis");
var redis = new GenericContainer<>(DockerImageName.parse(image));
```
The helper throws `IllegalStateException` if the classpath resource is missing or there is no usable `FROM` line, and
`UncheckedIOException` if reading fails. Parsing rules match the action. See the [standalone Maven example](examples/maven).

Alternatively, **skip the dependency and copy the class**: [`DockerfileImages.java`](src/main/java/no/entur/testcontainers/dockerfile/DockerfileImages.java)
is a single self-contained file that only uses the JDK (apart from the optional `@Nullable` annotation, which you can delete). Drop it into your test sources (change the `package` as needed) and use it exactly as above. 

That avoids adding and versioning another test artifact.

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
