package no.entur.testcontainers.dockerfile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

/**
 * Resolves Docker image names from the {@code FROM} line of Dockerfiles on the classpath.
 * <p>
 * Keeping images (e.g. Testcontainers images) in Dockerfiles lets Dependabot/Renovate bump them, while the tests read the very same files as their single
 * source of truth. The Dockerfiles are never built.
 * <p>
 * By default, {@code get("redis")} reads {@code testcontainers/Dockerfile.redis}. Use {@link #in(String)} and {@link #withPrefix(String)} to change the
 * directory and file name prefix.
 */
public final class DockerfileImages {

	public static final String DEFAULT_DIRECTORY = "testcontainers";
	public static final String DEFAULT_FILE_PREFIX = "Dockerfile.";

	private static final DockerfileImages DEFAULT = new DockerfileImages(DEFAULT_DIRECTORY, DEFAULT_FILE_PREFIX, DockerfileImages.class.getClassLoader());

	private final String directory;
	private final String filePrefix;
	private final ClassLoader classLoader;

	private DockerfileImages(String directory, String filePrefix, ClassLoader classLoader) {
		this.directory = directory;
		this.filePrefix = filePrefix;
		this.classLoader = classLoader;
	}

	/**
	 * Resolve the image of {@code testcontainers/Dockerfile.<name>}.
	 *
	 * @param name the Dockerfile suffix, e.g. {@code redis}
	 * @return the image of the first (non-stage-reference) {@code FROM} line, e.g. {@code redis:7.2}
	 * @throws IllegalStateException if the file is missing or has no usable FROM line
	 */
	public static String get(String name) {
		return DEFAULT.image(name);
	}

	/**
	 * @param directory classpath directory containing the Dockerfiles, e.g. {@code docker/test}
	 */
	public static DockerfileImages in(String directory) {
		return DEFAULT.withDirectory(directory);
	}

	public DockerfileImages withDirectory(String directory) {
		return new DockerfileImages(trimSlashes(directory), filePrefix, classLoader);
	}

	/**
	 * @param filePrefix file name prefix preceding the name, e.g. {@code Dockerfile.}
	 */
	public DockerfileImages withPrefix(String filePrefix) {
		return new DockerfileImages(directory, filePrefix, classLoader);
	}

	public DockerfileImages withClassLoader(ClassLoader classLoader) {
		return new DockerfileImages(directory, filePrefix, classLoader);
	}

	public String image(String name) {
		String resource = (directory.isEmpty() ? "" : directory + "/") + filePrefix + name;
		try (InputStream in = classLoader.getResourceAsStream(resource)) {
			if (in == null) {
				throw new IllegalStateException("Dockerfile not found on classpath: " + resource);
			}
			return parse(new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8)))
					.orElseThrow(() -> new IllegalStateException("No usable FROM line found in " + resource));
		} catch (IOException e) {
			throw new IllegalStateException("Could not load " + resource, e);
		}
	}

	/**
	 * Returns the image of the first {@code FROM image[:tag|@digest] [AS stage]} line. Mirrors the pre-pull GitHub Action: {@code scratch}, flags
	 * ({@code --platform}), build args ({@code $VAR}) and references to earlier stages are skipped.
	 */
	static Optional<String> parse(BufferedReader reader) throws IOException {
		List<String> stages = new ArrayList<>();
		String line;
		while ((line = reader.readLine()) != null) {
			String[] words = line.trim().split("\\s+");
			if (words.length < 2 || !words[0].equalsIgnoreCase("FROM")) {
				continue;
			}
			String image = words[1];
			boolean usable = !image.startsWith("--") && !image.contains("$") && !image.equalsIgnoreCase("scratch")
					&& !stages.contains(image.toLowerCase(Locale.ROOT));
			if (usable) {
				return Optional.of(image);
			}
			for (int i = 2; i < words.length - 1; i++) {
				if (words[i].equalsIgnoreCase("AS")) {
					stages.add(words[i + 1].toLowerCase(Locale.ROOT));
				}
			}
		}
		return Optional.empty();
	}

	private static String trimSlashes(String path) {
		String result = path;
		while (result.startsWith("/")) {
			result = result.substring(1);
		}
		while (result.endsWith("/")) {
			result = result.substring(0, result.length() - 1);
		}
		return result;
	}
}
