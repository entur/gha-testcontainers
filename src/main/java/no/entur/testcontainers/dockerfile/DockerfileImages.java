package no.entur.testcontainers.dockerfile;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import org.jspecify.annotations.Nullable;

/**
 * Parses the image of the first usable {@code FROM} line of a Dockerfile.
 * <p>
 * Keeping images (e.g. Testcontainers images) in Dockerfiles lets Dependabot/Renovate bump them, while the tests read the very same files as their single
 * source of truth. The Dockerfiles are never built.
 * <p>
 * Parsing mirrors the pre-pull GitHub Action: {@code FROM image[:tag|@digest] [AS stage]}; {@code scratch}, flags ({@code --platform}), build args
 * ({@code $VAR}) and references to earlier stages are skipped.
 * <p>
 * All methods throw {@link IllegalStateException} if there is no usable {@code FROM} line (or the classpath resource is missing) and
 * {@link UncheckedIOException} if reading fails.
 */
public final class DockerfileImages {

	private DockerfileImages() {
	}

	/**
	 * @param dockerfile Dockerfile content
	 * @return the image, e.g. {@code redis:7.2}
	 */
	public static String parse(String dockerfile) {
		return firstImage(dockerfile, "Dockerfile content");
	}

	/**
	 * Reads UTF-8 content; the stream is not closed.
	 */
	public static String parse(InputStream dockerfile) {
		try {
			return parse(dockerfile.readAllBytes(), "input stream");
		} catch (IOException e) {
			throw new UncheckedIOException("Could not read Dockerfile from input stream", e);
		}
	}

	/**
	 * @param dockerfile UTF-8 encoded Dockerfile content
	 */
	public static String parse(byte[] dockerfile) {
		return parse(dockerfile, "byte array");
	}

	/**
	 * @param resource classpath resource, e.g. {@code testcontainers/Dockerfile.redis}; looked up with the thread context class loader, then this class's
	 */
	public static String fromResource(String resource) {
		String name = stripLeadingSlash(resource);
		InputStream in = null;
		ClassLoader context = Thread.currentThread().getContextClassLoader();
		if (context != null) {
			in = context.getResourceAsStream(name);
		}
		if (in == null) {
			in = DockerfileImages.class.getClassLoader().getResourceAsStream(name);
		}
		return fromResource(in, resource);
	}

	/**
	 * @param resource    classpath resource, e.g. {@code testcontainers/Dockerfile.redis}
	 * @param classLoader the class loader to look it up with
	 */
	public static String fromResource(String resource, ClassLoader classLoader) {
		return fromResource(classLoader.getResourceAsStream(stripLeadingSlash(resource)), resource);
	}

	private static String fromResource(@Nullable InputStream stream, String resource) {
		if (stream == null) {
			throw new IllegalStateException("Dockerfile not found on classpath: " + resource);
		}
		try (InputStream in = stream) {
			return parse(in.readAllBytes(), "classpath resource " + resource);
		} catch (IOException e) {
			throw new UncheckedIOException("Could not read Dockerfile from classpath resource " + resource, e);
		}
	}

	private static String stripLeadingSlash(String resource) {
		return resource.startsWith("/") ? resource.substring(1) : resource;
	}

	public static String fromPath(Path path) {
		try {
			return parse(Files.readAllBytes(path), path.toString());
		} catch (IOException e) {
			throw new UncheckedIOException("Could not read Dockerfile " + path, e);
		}
	}

	public static String fromFile(File file) {
		return fromPath(file.toPath());
	}

	private static String parse(byte[] dockerfile, String source) {
		return firstImage(new String(dockerfile, StandardCharsets.UTF_8), source);
	}

	private static String firstImage(String dockerfile, String source) {
		List<String> stages = new ArrayList<>();
		for (String line : dockerfile.split("\\R")) {
			String[] words = line.trim().split("\\s+");
			if (words.length < 2 || !words[0].equalsIgnoreCase("FROM")) {
				continue;
			}
			String image = words[1];
			boolean usable = !image.startsWith("--") && !image.contains("$") && !image.equalsIgnoreCase("scratch")
					&& !stages.contains(image.toLowerCase(Locale.ROOT));
			if (usable) {
				return image;
			}
			for (int i = 2; i < words.length - 1; i++) {
				if (words[i].equalsIgnoreCase("AS")) {
					stages.add(words[i + 1].toLowerCase(Locale.ROOT));
				}
			}
		}
		throw new IllegalStateException("No usable FROM line found in " + source);
	}
}
