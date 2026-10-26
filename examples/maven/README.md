# Standalone Maven example

A complete, buildable project (`mvn verify`, needs Docker) showing the whole setup:

| File | Purpose |
|------|---------|
| `src/test/resources/testcontainers/Dockerfile.redis`, `Dockerfile.nginx`, `Dockerfile.gcp-emulators` | One Dockerfile per Testcontainers image. Never built; only the `FROM` line matters. The GCP emulators image (Pub/Sub, Datastore, Firestore, Bigtable, Spanner) is over 1 GB, which is where pre-pulling pays off most. |
| `pom.xml` | Depends (test scope) on `no.entur.testcontainers:dockerfile-helper`, the library built from the repository root. While it is unreleased, run `mvn install` in the repository root first. Also depends on Spring Boot (web, actuator, gRPC) and [cloud-logging](https://github.com/entur/cloud-logging), like a typical service, so there is a realistic amount of dependencies to cache. |
| `src/main/java/com/example/Application.java` | The (empty) Spring Boot application, started by the integration tests. |
| `src/test/java/com/example/RedisIT.java`, `NginxIT.java`, `PubSubEmulatorIT.java` | Integration tests (Failsafe, `@SpringBootTest`) using `DockerfileImages.fromResource("testcontainers/Dockerfile.redis")` / `...nginx` / `...gcp-emulators`. The containers are started by Spring (`@ImportTestcontainers`), after logging is configured. `PubSubEmulatorIT` creates a topic in the Pub/Sub emulator over gRPC. |
| `src/test/resources/application.properties` | Log levels, so that Testcontainers startup is logged (with timestamps, by cloud-logging's human-readable output): image pulls and container start times are visible in the build log. |
| `.github/workflows/ci.yml` | Pre-pulls the images in the background, then sets up Java + Maven cache, then runs `mvn verify`. Optional `prepare-report` shows how each pull went. |
| `.github/dependabot.yaml` | Lets Dependabot bump the images (and Maven/Actions dependencies). |

To use it in your project, copy the files to the same locations in your repository root (GitHub only reads
`.github/` at the repository root, so the files here are templates), and adjust the action reference and paths.
Keep the `dockerfile-paths` input and Dependabot's `directory` pointing at the same directory as the Dockerfiles.
