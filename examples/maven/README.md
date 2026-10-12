# Standalone Maven example

A complete, buildable project (`mvn verify`, needs Docker) showing the whole setup:

| File | Purpose |
|------|---------|
| `src/test/resources/testcontainers/Dockerfile.redis`, `Dockerfile.nginx` | One Dockerfile per Testcontainers image. Never built; only the `FROM` line matters. |
| `pom.xml` | Depends (test scope) on `no.entur.testcontainers:dockerfile-helper`, the library built from the repository root. While it is unreleased, run `mvn install` in the repository root first. |
| `src/test/java/com/example/RedisIT.java`, `NginxIT.java` | Integration tests (Failsafe) using `DockerfileImages.fromResource("testcontainers/Dockerfile.redis")` / `...nginx`. |
| `.github/workflows/ci.yml` | Pre-pulls the images in the background, then sets up Java + Maven cache, then runs `mvn verify`. |
| `.github/dependabot.yaml` | Lets Dependabot bump the images (and Maven/Actions dependencies). |

To use it in your project, copy the files to the same locations in your repository root (GitHub only reads
`.github/` at the repository root, so the files here are templates), and adjust the action reference and paths.
Keep the `dockerfile-paths` input and Dependabot's `directory` pointing at the same directory as the Dockerfiles.
