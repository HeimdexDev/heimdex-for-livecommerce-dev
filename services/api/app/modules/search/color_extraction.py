"""Color extraction and histogram generation for color-based scene search.

Pure functions with no dependencies on search or ingest modules.
Only requires PIL (Pillow), which is already in the worker dependencies.
"""

from __future__ import annotations

import colorsys
import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

# Histogram layout: 8 hue buckets × 3 saturation levels + 3 achromatic bins = 27
NUM_HUE_BUCKETS = 8
NUM_SAT_LEVELS = 3
NUM_ACHROMATIC_BINS = 3  # black, gray, white
HISTOGRAM_DIM = NUM_HUE_BUCKETS * NUM_SAT_LEVELS + NUM_ACHROMATIC_BINS  # 27

# Achromatic thresholds (in HSL space, S and L are 0-1)
ACHROMATIC_SAT_THRESHOLD = 0.10
BLACK_LIGHTNESS_THRESHOLD = 0.20
WHITE_LIGHTNESS_THRESHOLD = 0.80

# Saturation level boundaries (for chromatic pixels)
SAT_BOUNDARIES = [0.33, 0.66]  # low < 0.33, mid 0.33-0.66, high > 0.66

# K-means parameters
KMEANS_MAX_ITERATIONS = 10
KMEANS_RESIZE_PX = 128

# Gaussian spread for single-color query vectors
# Tighter sigma = more precise color matching, less bleed to neighbors
QUERY_HUE_SIGMA = 0.5  # spread across neighboring hue buckets (was 1.0)
QUERY_SAT_SIGMA = 0.3  # spread across saturation levels (was 0.5)


def extract_dominant_colors(
    image: Image.Image, k: int = 5, seed: int = 42
) -> tuple[list[tuple[int, int, int]], list[float]]:
    """Extract k dominant colors from an image using k-means on RGB pixels.

    Returns (colors, weights) where colors are RGB tuples and weights
    are the fraction of pixels assigned to each cluster.
    """
    if image.size[0] == 0 or image.size[1] == 0:
        return [], []

    resized = image.convert("RGB").resize(
        (KMEANS_RESIZE_PX, KMEANS_RESIZE_PX), resample=0  # NEAREST for speed
    )
    pixels = list(resized.getdata())  # type: ignore[arg-type]

    if not pixels:
        return [], []

    colors, weights = _kmeans_rgb(pixels, k=k, seed=seed)
    # Sort by weight descending (most dominant first)
    paired = sorted(zip(colors, weights), key=lambda x: x[1], reverse=True)
    colors = [c for c, _ in paired]
    weights = [w for _, w in paired]
    return colors, weights


def rgb_to_hsl_histogram(
    colors: list[tuple[int, int, int]], weights: list[float]
) -> list[float]:
    """Convert dominant colors with weights to a 27-dim HSL histogram vector.

    Layout:
      [0..23]  8 hue buckets × 3 saturation levels (chromatic)
      [24]     black (low saturation, low lightness)
      [25]     gray (low saturation, mid lightness)
      [26]     white (low saturation, high lightness)

    The result is L2-normalized.
    """
    histogram = [0.0] * HISTOGRAM_DIM

    for (r, g, b), weight in zip(colors, weights):
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        # h is 0-1 (hue), l is 0-1 (lightness), s is 0-1 (saturation)

        if s < ACHROMATIC_SAT_THRESHOLD:
            # Achromatic: route to black/gray/white bins
            base = NUM_HUE_BUCKETS * NUM_SAT_LEVELS
            if l < BLACK_LIGHTNESS_THRESHOLD:
                histogram[base] += weight  # black
            elif l > WHITE_LIGHTNESS_THRESHOLD:
                histogram[base + 2] += weight  # white
            else:
                histogram[base + 1] += weight  # gray
        else:
            # Chromatic: route to hue × saturation bucket
            hue_bucket = int(h * NUM_HUE_BUCKETS) % NUM_HUE_BUCKETS
            if s < SAT_BOUNDARIES[0]:
                sat_level = 0
            elif s < SAT_BOUNDARIES[1]:
                sat_level = 1
            else:
                sat_level = 2
            idx = hue_bucket * NUM_SAT_LEVELS + sat_level
            histogram[idx] += weight

    return _l2_normalize(histogram)


def hex_to_color_histogram(hex_color: str) -> list[float]:
    """Convert a single hex color to a 27-dim query vector with Gaussian spread.

    The picked color gets weight in its primary bucket plus spread to
    neighboring hue and saturation buckets, producing softer matches
    for similar tones.
    """
    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

    histogram = [0.0] * HISTOGRAM_DIM

    if s < ACHROMATIC_SAT_THRESHOLD:
        # Achromatic query: concentrate in achromatic bins with spread
        base = NUM_HUE_BUCKETS * NUM_SAT_LEVELS
        if l < BLACK_LIGHTNESS_THRESHOLD:
            histogram[base] = 1.0
            histogram[base + 1] = 0.3  # some gray spread
        elif l > WHITE_LIGHTNESS_THRESHOLD:
            histogram[base + 2] = 1.0
            histogram[base + 1] = 0.3  # some gray spread
        else:
            histogram[base + 1] = 1.0
            histogram[base] = 0.2  # some black spread
            histogram[base + 2] = 0.2  # some white spread
    else:
        # Chromatic query: Gaussian spread across hue and saturation
        center_hue = h * NUM_HUE_BUCKETS
        if s < SAT_BOUNDARIES[0]:
            center_sat = 0
        elif s < SAT_BOUNDARIES[1]:
            center_sat = 1
        else:
            center_sat = 2

        for hue_bucket in range(NUM_HUE_BUCKETS):
            # Circular hue distance
            hue_dist = min(
                abs(hue_bucket - center_hue),
                NUM_HUE_BUCKETS - abs(hue_bucket - center_hue),
            )
            hue_weight = math.exp(-0.5 * (hue_dist / QUERY_HUE_SIGMA) ** 2)

            for sat_level in range(NUM_SAT_LEVELS):
                sat_dist = abs(sat_level - center_sat)
                sat_weight = math.exp(-0.5 * (sat_dist / QUERY_SAT_SIGMA) ** 2)
                idx = hue_bucket * NUM_SAT_LEVELS + sat_level
                histogram[idx] = hue_weight * sat_weight

    return _l2_normalize(histogram)


def colors_to_hex(colors: list[tuple[int, int, int]]) -> list[str]:
    """Convert RGB tuples to hex strings."""
    return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in colors]


# --- Internal helpers ---


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (R, G, B)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _kmeans_rgb(
    pixels: list[tuple[int, int, int]], k: int, seed: int
) -> tuple[list[tuple[int, int, int]], list[float]]:
    """Simple k-means clustering on RGB pixels.

    Returns (centroids, weights) where weights are fractions summing to 1.0.
    """
    rng = random.Random(seed)
    n = len(pixels)
    if n == 0:
        return [], []
    k = min(k, n)

    # Initialize centroids via random sample
    centroids = [list(p) for p in rng.sample(pixels, k)]

    assignments = [0] * n

    for _ in range(KMEANS_MAX_ITERATIONS):
        changed = False

        # Assign each pixel to nearest centroid
        for i, (pr, pg, pb) in enumerate(pixels):
            best_dist = float("inf")
            best_c = assignments[i]
            for c, (cr, cg, cb) in enumerate(centroids):
                dist = (pr - cr) ** 2 + (pg - cg) ** 2 + (pb - cb) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_c = c
            if best_c != assignments[i]:
                assignments[i] = best_c
                changed = True

        if not changed:
            break

        # Update centroids
        sums = [[0, 0, 0] for _ in range(k)]
        counts = [0] * k
        for i, (pr, pg, pb) in enumerate(pixels):
            c = assignments[i]
            sums[c][0] += pr
            sums[c][1] += pg
            sums[c][2] += pb
            counts[c] += 1

        for c in range(k):
            if counts[c] > 0:
                centroids[c] = [
                    sums[c][0] // counts[c],
                    sums[c][1] // counts[c],
                    sums[c][2] // counts[c],
                ]

    # Build results
    counts = [0] * k
    for a in assignments:
        counts[a] += 1

    total = sum(counts)
    result_colors = []
    result_weights = []
    for c in range(k):
        if counts[c] > 0:
            result_colors.append((centroids[c][0], centroids[c][1], centroids[c][2]))
            result_weights.append(counts[c] / total)

    return result_colors, result_weights


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector. Returns zero vector if magnitude is 0."""
    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude == 0:
        return vec
    return [v / magnitude for v in vec]
