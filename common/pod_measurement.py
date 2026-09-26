"""Single-image soybean-pod segmentation and morphology measurement.

This module adapts the measurement algorithm from ``measure_pods.py`` for the
interactive desktop demo.  It consumes the instance masks produced by the
single-class YOLO segmentation model and returns JSON-friendly measurements
plus a self-contained visualization image.
"""
from __future__ import annotations

import math
from heapq import heappop, heappush

import cv2
import numpy as np


MIN_MASK_AREA = 100
ENDPOINT_TANGENT_WINDOW_FRACTION = 0.05
ENDPOINT_RAY_STEP_PX = 0.25
NEIGHBORS_8 = [
    (-1, -1, math.sqrt(2.0)),
    (-1, 0, 1.0),
    (-1, 1, math.sqrt(2.0)),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (1, -1, math.sqrt(2.0)),
    (1, 0, 1.0),
    (1, 1, math.sqrt(2.0)),
]


def _largest_filled_component(mask: np.ndarray):
    mask = np.ascontiguousarray((mask > 0).astype(np.uint8))
    if np.count_nonzero(mask) == 0:
        return None, None
    contours_info = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = contours_info[0] if len(contours_info) == 2 else contours_info[1]
    if not contours:
        return None, None
    contour = max(contours, key=cv2.contourArea)
    filled = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(filled, [contour], -1, 1, thickness=cv2.FILLED)
    return filled, contour


def _zhang_suen_thinning(mask: np.ndarray, max_iterations: int = 300) -> np.ndarray:
    image = (mask > 0).astype(np.uint8)
    if image.shape[0] < 3 or image.shape[1] < 3:
        return image

    for _ in range(max_iterations):
        before = image.copy()
        for step in (0, 1):
            padded = np.pad(image, ((1, 1), (1, 1)), mode="constant")
            p1 = padded[1:-1, 1:-1]
            p2 = padded[:-2, 1:-1]
            p3 = padded[:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, :-2]
            p8 = padded[1:-1, :-2]
            p9 = padded[:-2, :-2]
            neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
            transitions = np.zeros_like(image, dtype=np.uint8)
            for index in range(8):
                transitions += (neighbors[index] == 0) & (
                    neighbors[(index + 1) % 8] == 1
                )
            neighbor_count = sum(neighbors)
            if step == 0:
                keep_connectivity = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                keep_connectivity = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            remove = (
                (p1 == 1)
                & (neighbor_count >= 2)
                & (neighbor_count <= 6)
                & (transitions == 1)
                & keep_connectivity
            )
            image[remove] = 0
        if np.array_equal(image, before):
            break
    return image


def _skeletonize(mask: np.ndarray) -> np.ndarray:
    binary_255 = (mask > 0).astype(np.uint8) * 255
    if hasattr(cv2, "ximgproc") and hasattr(cv2.ximgproc, "thinning"):
        skeleton = cv2.ximgproc.thinning(
            binary_255, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN
        )
        return (skeleton > 0).astype(np.uint8)
    return _zhang_suen_thinning(mask)


def _skeleton_endpoints(skeleton: np.ndarray) -> list[tuple[int, int]]:
    skeleton = (skeleton > 0).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    neighbor_count = cv2.filter2D(
        skeleton, cv2.CV_16S, kernel, borderType=cv2.BORDER_CONSTANT
    ) - skeleton
    endpoints = np.column_stack(np.where((skeleton > 0) & (neighbor_count == 1)))
    return [tuple(map(int, point)) for point in endpoints]


def _pca_extreme_points(points_yx: np.ndarray):
    if len(points_yx) == 0:
        return None, None
    if len(points_yx) == 1:
        point = tuple(map(int, points_yx[0]))
        return point, point
    points_xy = points_yx[:, ::-1].astype(np.float64)
    centered = points_xy - points_xy.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    projection = centered @ vh[0]
    return (
        tuple(map(int, points_yx[int(np.argmin(projection))])),
        tuple(map(int, points_yx[int(np.argmax(projection))])),
    )


def _dijkstra(skeleton: np.ndarray, start: tuple[int, int], return_prev=False):
    skeleton_bool = skeleton > 0
    height, width = skeleton_bool.shape
    start_y, start_x = start
    distance = np.full((height, width), np.inf, dtype=np.float64)
    distance[start_y, start_x] = 0.0
    heap = [(0.0, start_y, start_x)]
    previous_y = previous_x = None
    if return_prev:
        previous_y = np.full((height, width), -1, dtype=np.int32)
        previous_x = np.full((height, width), -1, dtype=np.int32)

    while heap:
        current_distance, y, x = heappop(heap)
        if current_distance != distance[y, x]:
            continue
        for delta_y, delta_x, weight in NEIGHBORS_8:
            next_y, next_x = y + delta_y, x + delta_x
            if (
                next_y < 0
                or next_y >= height
                or next_x < 0
                or next_x >= width
                or not skeleton_bool[next_y, next_x]
            ):
                continue
            next_distance = current_distance + weight
            if next_distance < distance[next_y, next_x]:
                distance[next_y, next_x] = next_distance
                if return_prev:
                    previous_y[next_y, next_x] = y
                    previous_x[next_y, next_x] = x
                heappush(heap, (next_distance, next_y, next_x))
    return distance, previous_y, previous_x


def _reconstruct_path(previous_y, previous_x, start, end) -> np.ndarray:
    path = [end]
    current = end
    while current != start:
        y, x = current
        parent_y = int(previous_y[y, x])
        parent_x = int(previous_x[y, x])
        if parent_y < 0 or parent_x < 0:
            return np.empty((0, 2), dtype=np.int32)
        current = (parent_y, parent_x)
        path.append(current)
    path.reverse()
    return np.asarray(path, dtype=np.int32)


def _longest_skeleton_path(skeleton: np.ndarray) -> dict:
    skeleton = (skeleton > 0).astype(np.uint8)
    points = np.column_stack(np.where(skeleton > 0))
    if len(points) == 0:
        return {
            "path": np.empty((0, 2), dtype=np.int32),
            "length_px": 0.0,
            "status": "no_skeleton",
        }

    endpoints = _skeleton_endpoints(skeleton)
    if len(endpoints) >= 2:
        distance, _, _ = _dijkstra(skeleton, endpoints[0])
        reachable = [point for point in endpoints if np.isfinite(distance[point])]
        if len(reachable) >= 2:
            start = max(reachable, key=lambda point: distance[point])
            distance, previous_y, previous_x = _dijkstra(
                skeleton, start, return_prev=True
            )
            candidates = [point for point in endpoints if np.isfinite(distance[point])]
            end = max(candidates, key=lambda point: distance[point])
            return {
                "path": _reconstruct_path(previous_y, previous_x, start, end),
                "length_px": float(distance[end]),
                "status": "ok",
            }

    point1, point2 = _pca_extreme_points(points)
    distance, previous_y, previous_x = _dijkstra(skeleton, point1, return_prev=True)
    if np.isfinite(distance[point2]):
        path = _reconstruct_path(previous_y, previous_x, point1, point2)
        length_px = float(distance[point2])
    else:
        path = np.asarray([point1, point2], dtype=np.int32)
        length_px = float(np.linalg.norm(np.asarray(point1) - np.asarray(point2)))
    return {"path": path, "length_px": length_px, "status": "fallback_pca"}


def _contour_arc_length(points_xy: np.ndarray, start_index: int, end_index: int) -> float:
    count = len(points_xy)
    if count < 2 or start_index == end_index:
        return 0.0
    segment_lengths = np.linalg.norm(
        points_xy[(np.arange(count) + 1) % count] - points_xy[np.arange(count)],
        axis=1,
    )
    if start_index < end_index:
        return float(np.sum(segment_lengths[start_index:end_index]))
    return float(np.sum(segment_lengths[start_index:]) + np.sum(segment_lengths[:end_index]))


def _contour_arc_points(points_xy: np.ndarray, start_index: int, end_index: int):
    if start_index <= end_index:
        return points_xy[start_index : end_index + 1]
    return np.vstack([points_xy[start_index:], points_xy[: end_index + 1]])


def _pca_contour_tip_indices(contour_xy: np.ndarray) -> tuple[int, int]:
    if len(contour_xy) <= 1:
        return 0, 0
    centered = contour_xy - contour_xy.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    projection = centered @ vh[0]
    return int(np.argmin(projection)), int(np.argmax(projection))


def _path_prefix_by_length_fraction(
    ordered_path_xy: np.ndarray,
    fraction: float = ENDPOINT_TANGENT_WINDOW_FRACTION,
    minimum_points: int = 3,
) -> np.ndarray:
    """Return a prefix spanning a fraction of the full geodesic path length."""
    path = np.asarray(ordered_path_xy, dtype=np.float64)
    if len(path) <= minimum_points:
        return path.copy()
    segment_lengths = np.linalg.norm(np.diff(path, axis=0), axis=1)
    total_length = float(np.sum(segment_lengths))
    if total_length <= 1e-9:
        return path[:minimum_points].copy()
    target_length = float(np.clip(fraction, 0.0, 1.0)) * total_length
    cumulative = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    last_index = int(np.searchsorted(cumulative, target_length, side="left"))
    point_count = min(len(path), max(minimum_points, last_index + 1))
    return path[:point_count].copy()


def _tangent_ray_contour_tip_index(
    mask: np.ndarray,
    contour_xy: np.ndarray,
    ordered_path_xy: np.ndarray,
    window_fraction: float = ENDPOINT_TANGENT_WINDOW_FRACTION,
) -> tuple[int, np.ndarray, np.ndarray]:
    """Fit an end tangent, cast it outward, and return the hit contour index."""
    contour = np.asarray(contour_xy, dtype=np.float64)
    path = np.asarray(ordered_path_xy, dtype=np.float64)
    if len(contour) == 0:
        return 0, np.empty((0, 2), dtype=np.float64), np.zeros(2, dtype=float)
    if len(path) < 2:
        nearest = (
            int(np.argmin(np.linalg.norm(contour - path[0], axis=1)))
            if len(path)
            else 0
        )
        return nearest, path.copy(), contour[nearest].copy()

    fit_segment = _path_prefix_by_length_fraction(path, window_fraction)
    anchor = path[0].copy()
    centered = fit_segment - fit_segment.mean(axis=0)
    if len(fit_segment) >= 3 and np.any(np.abs(centered) > 0):
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        outward = vh[0].astype(np.float64)
    else:
        outward = anchor - path[min(2, len(path) - 1)]

    inward_reference = fit_segment[-1] - anchor
    if float(outward @ inward_reference) > 0:
        outward = -outward
    direction_norm = float(np.linalg.norm(outward))
    if direction_norm < 1e-9:
        outward = anchor - path[1]
        direction_norm = float(np.linalg.norm(outward))
    if direction_norm < 1e-9:
        nearest = int(np.argmin(np.linalg.norm(contour - anchor, axis=1)))
        return nearest, fit_segment, contour[nearest].copy()
    outward /= direction_norm

    last_inside = anchor.copy()
    maximum_distance = float(math.hypot(mask.shape[0], mask.shape[1]))
    for distance in np.arange(
        ENDPOINT_RAY_STEP_PX,
        maximum_distance + ENDPOINT_RAY_STEP_PX,
        ENDPOINT_RAY_STEP_PX,
    ):
        point = anchor + distance * outward
        point_x, point_y = int(round(point[0])), int(round(point[1]))
        if (
            point_x < 0
            or point_y < 0
            or point_x >= mask.shape[1]
            or point_y >= mask.shape[0]
            or mask[point_y, point_x] == 0
        ):
            break
        last_inside = point

    tip_index = int(np.argmin(np.linalg.norm(contour - last_inside, axis=1)))
    return tip_index, fit_segment, contour[tip_index].copy()


def _tangent_ray_contour_tip_indices(
    mask: np.ndarray,
    contour_xy: np.ndarray,
    path_xy: np.ndarray,
    window_fraction: float = ENDPOINT_TANGENT_WINDOW_FRACTION,
) -> tuple[int, int, np.ndarray, np.ndarray]:
    """Find both contour endpoints from the two orientations of one main path."""
    tip1_index, fit1, _ = _tangent_ray_contour_tip_index(
        mask, contour_xy, path_xy, window_fraction
    )
    tip2_index, fit2_reversed, _ = _tangent_ray_contour_tip_index(
        mask, contour_xy, path_xy[::-1], window_fraction
    )
    if tip1_index == tip2_index:
        tip1_index, tip2_index = _pca_contour_tip_indices(contour_xy)
        return tip1_index, tip2_index, np.empty((0, 2)), np.empty((0, 2))
    return tip1_index, tip2_index, fit1, fit2_reversed[::-1]


def _max_inscribed_circle(mask: np.ndarray) -> tuple[tuple[int, int], float]:
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return (0, 0), 0.0
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    cropped = np.ascontiguousarray((mask[y0:y1, x0:x1] > 0).astype(np.uint8))

    # The crop touches the foreground at each bounding-box extreme.  Without an
    # explicit zero border, distanceTransform cannot see the background beyond
    # those crop edges and can therefore return an off-centre, oversized circle.
    border = 1
    padded = cv2.copyMakeBorder(
        cropped,
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=0,
    )
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    _, distance_radius_px, _, padded_center = cv2.minMaxLoc(distance)
    center = (
        int(padded_center[0] - border + x0),
        int(padded_center[1] - border + y0),
    )

    # OpenCV's distance transform measures between pixel centres, whereas the
    # displayed contour runs through boundary-pixel centres.  Clamp the radius
    # to that same contour so the reported circle matches the purple outline.
    contours_info = cv2.findContours(cropped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = contours_info[0] if len(contours_info) == 2 else contours_info[1]
    radius_px = float(distance_radius_px)
    if contours:
        contour = max(contours, key=cv2.contourArea)
        local_center = (float(center[0] - x0), float(center[1] - y0))
        contour_radius_px = cv2.pointPolygonTest(contour, local_center, True)
        radius_px = min(radius_px, max(0.0, float(contour_radius_px)))
    return center, radius_px


def _round(value, digits=4):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _measure_one_pod(
    image: np.ndarray,
    raw_mask: np.ndarray,
    pod_index: int,
    confidence: float,
    pixel_to_cm: float,
):
    height, width = image.shape[:2]
    mask, contour = _largest_filled_component(raw_mask)
    if mask is None or contour is None or np.count_nonzero(mask) < MIN_MASK_AREA:
        return {
            "pod_index": pod_index,
            "confidence": _round(confidence, 4),
            "status": "empty_or_tiny_mask",
        }, None

    x, y, box_width, box_height = cv2.boundingRect(contour)
    padding = 3
    x0, y0 = max(0, x - padding), max(0, y - padding)
    x1 = min(width, x + box_width + padding)
    y1 = min(height, y + box_height + padding)
    skeleton = _skeletonize(mask[y0:y1, x0:x1])
    path_info = _longest_skeleton_path(skeleton)
    path_yx = path_info["path"]
    skeleton_status = path_info["status"]
    contour_xy = contour[:, 0, :].astype(np.float64)

    path_xy = np.empty((0, 2), dtype=np.float64)
    if len(path_yx) >= 2:
        path_xy = np.column_stack([path_yx[:, 1] + x0, path_yx[:, 0] + y0]).astype(
            np.float64
        )
        tip1_index, tip2_index, endpoint_fit1_xy, endpoint_fit2_xy = (
            _tangent_ray_contour_tip_indices(
                mask,
                contour_xy,
                path_xy,
                ENDPOINT_TANGENT_WINDOW_FRACTION,
            )
        )
        if len(endpoint_fit1_xy) == 0 or len(endpoint_fit2_xy) == 0:
            skeleton_status = "fallback_contour_pca_same_tip"
    else:
        tip1_index, tip2_index = _pca_contour_tip_indices(contour_xy)
        skeleton_status = "fallback_contour_pca"
        endpoint_fit1_xy = np.empty((0, 2), dtype=np.float64)
        endpoint_fit2_xy = np.empty((0, 2), dtype=np.float64)

    endpoint1_xy = contour_xy[tip1_index]
    endpoint2_xy = contour_xy[tip2_index]
    side_a_length_px = _contour_arc_length(contour_xy, tip1_index, tip2_index)
    perimeter_px = float(cv2.arcLength(contour, True))
    side_b_length_px = max(0.0, perimeter_px - side_a_length_px)
    inner_side_length_px = min(side_a_length_px, side_b_length_px)
    outer_side_length_px = max(side_a_length_px, side_b_length_px)
    if side_a_length_px <= side_b_length_px:
        outer_arc = _contour_arc_points(contour_xy, tip2_index, tip1_index)
    else:
        outer_arc = _contour_arc_points(contour_xy, tip1_index, tip2_index)

    chord_length_px = float(np.linalg.norm(endpoint1_xy - endpoint2_xy))
    curvature = chord_length_px / outer_side_length_px if outer_side_length_px > 0 else None
    circle_center_xy, circle_radius_px = _max_inscribed_circle(mask)
    width_px = 2.0 * circle_radius_px
    min_rect = cv2.minAreaRect(contour)
    rect_width_raw_px, rect_height_raw_px = min_rect[1]
    rect_length_px = float(max(rect_width_raw_px, rect_height_raw_px))
    rect_width_px = float(min(rect_width_raw_px, rect_height_raw_px))

    pixels = image[mask > 0]
    avg_b, avg_g, avg_r = np.mean(pixels, axis=0) if len(pixels) else (0.0, 0.0, 0.0)
    moments = cv2.moments(contour)
    if moments["m00"]:
        centroid = (
            int(moments["m10"] / moments["m00"]),
            int(moments["m01"] / moments["m00"]),
        )
    else:
        centroid = (x + box_width // 2, y + box_height // 2)

    row = {
        "pod_index": pod_index,
        "confidence": _round(confidence, 4),
        "status": "ok",
        "avg_r": _round(avg_r, 3),
        "avg_g": _round(avg_g, 3),
        "avg_b": _round(avg_b, 3),
        "length_px": chord_length_px,
        "length_cm": float(chord_length_px * pixel_to_cm),
        "width_px": width_px,
        "width_cm": float(width_px * pixel_to_cm),
        "outer_side_length_px": outer_side_length_px,
        "outer_side_length_cm": float(outer_side_length_px * pixel_to_cm),
        "inner_side_length_px": inner_side_length_px,
        "inner_side_length_cm": float(inner_side_length_px * pixel_to_cm),
        "curvature": float(curvature) if curvature is not None else None,
        "rect_length_px": rect_length_px,
        "rect_length_cm": float(rect_length_px * pixel_to_cm),
        "rect_width_px": rect_width_px,
        "rect_width_cm": float(rect_width_px * pixel_to_cm),
        "skeleton_status": skeleton_status,
    }
    debug = {
        "mask": mask,
        "contour": contour,
        "endpoint1_xy": endpoint1_xy,
        "endpoint2_xy": endpoint2_xy,
        "outer_arc": outer_arc,
        "path_xy": path_xy,
        "endpoint_fit1_xy": endpoint_fit1_xy,
        "endpoint_fit2_xy": endpoint_fit2_xy,
        "endpoint_tangent_window_fraction": ENDPOINT_TANGENT_WINDOW_FRACTION,
        "circle_center_xy": circle_center_xy,
        "circle_radius_px": circle_radius_px,
        "centroid": centroid,
        "min_rect": min_rect,
        **row,
    }
    return row, debug


def _mean(rows: list[dict], key: str, digits=4) -> float:
    values = [row.get(key) for row in rows]
    values = [float(value) for value in values if value is not None and np.isfinite(value)]
    return round(float(np.mean(values)), digits) if values else 0.0


def _build_summary(rows: list[dict], detection_count: int, pixel_to_cm: float) -> dict:
    return {
        "count": len(rows),
        "detection_count": int(detection_count),
        "avg_confidence": _mean(rows, "confidence", 4),
        "refinements_applied": sum(
            bool(row.get("refinement_applied")) for row in rows
        ),
        "refinement_fallbacks": sum(
            not bool(row.get("refinement_applied")) for row in rows
        ),
        "avg_raw_refined_iou": _mean(rows, "raw_refined_iou", 4),
        "avg_length": _mean(rows, "length_cm"),
        "avg_width": _mean(rows, "width_cm"),
        "avg_outer_side_length": _mean(rows, "outer_side_length_cm"),
        "avg_inner_side_length": _mean(rows, "inner_side_length_cm"),
        "avg_curvature": _mean(rows, "curvature", 3),
        "avg_rect_length": _mean(rows, "rect_length_cm"),
        "avg_rect_width": _mean(rows, "rect_width_cm"),
        "pixel_to_cm": round(float(pixel_to_cm), 6),
    }


def _create_black_background(image: np.ndarray, full_mask: np.ndarray) -> np.ndarray:
    result = np.zeros_like(image)
    result[full_mask > 0] = image[full_mask > 0]
    return result


def _make_ellipse_kernel(radius: int) -> np.ndarray:
    radius = max(1, int(radius))
    size = radius * 2 + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _mask_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    a = mask_a > 0
    b = mask_b > 0
    intersection = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return float(intersection / union) if union else 1.0


def _robust_sample(pixels: np.ndarray, maximum: int = 20000) -> np.ndarray:
    if len(pixels) <= maximum:
        return pixels
    indices = np.linspace(0, len(pixels) - 1, maximum, dtype=np.int64)
    return pixels[indices]


def _largest_component_overlapping(
    candidate: np.ndarray, reference: np.ndarray
) -> np.ndarray | None:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.ascontiguousarray((candidate > 0).astype(np.uint8)), connectivity=8
    )
    if count <= 1:
        return None
    best_label = None
    best_key = None
    for label in range(1, count):
        overlap = int(np.count_nonzero((labels == label) & (reference > 0)))
        area = int(stats[label, cv2.CC_STAT_AREA])
        key = (overlap, area)
        if best_key is None or key > best_key:
            best_key = key
            best_label = label
    if best_label is None or best_key[0] == 0:
        return None
    component = np.ascontiguousarray((labels == best_label).astype(np.uint8))
    contours_info = cv2.findContours(
        component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    contours = contours_info[0] if len(contours_info) == 2 else contours_info[1]
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(component, dtype=np.uint8)
    cv2.drawContours(filled, [contour], -1, 1, thickness=cv2.FILLED)
    return filled


def _boundary_edge_score(image_bgr: np.ndarray, mask: np.ndarray) -> float:
    """Return a robust original-image gradient score along a mask boundary."""
    binary = np.ascontiguousarray((mask > 0).astype(np.uint8))
    if not np.any(binary):
        return 0.0
    lab_lightness = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)[:, :, 0]
    smooth = cv2.GaussianBlur(lab_lightness, (5, 5), 0).astype(np.float32)
    gradient_x = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    boundary = cv2.morphologyEx(binary, cv2.MORPH_GRADIENT, kernel) > 0
    values = gradient[boundary]
    if values.size == 0:
        return 0.0
    upper = float(np.percentile(values, 90))
    return float(np.mean(np.minimum(values, upper)))


def _refine_instance_mask(
    image_bgr: np.ndarray,
    raw_mask: np.ndarray,
    margin_ratio: float,
    minimum_color_separation: float,
    minimum_iou: float,
    minimum_edge_score_gain: float,
    minimum_area_ratio: float,
    maximum_area_ratio: float,
) -> tuple[np.ndarray, dict]:
    """Refine only a narrow mask band using robust Lab foreground/background seeds."""
    height, width = image_bgr.shape[:2]
    raw_mask = np.ascontiguousarray((raw_mask > 0).astype(np.uint8))
    raw_area = int(raw_mask.sum())
    base_stats = {
        "raw_mask_area_px": raw_area,
        "refined_mask_area_px": raw_area,
        "area_ratio": 1.0,
        "raw_refined_iou": 1.0,
        "color_separation": None,
        "raw_edge_score": None,
        "candidate_edge_score": None,
        "edge_score_gain": None,
        "candidate_raw_iou": None,
        "candidate_area_ratio": None,
        "refine_margin_px": 0,
        "refinement_applied": False,
        "refinement_reason": "fallback_empty_mask" if raw_area == 0 else "unchanged",
    }
    if raw_area == 0:
        return raw_mask, base_stats

    ys, xs = np.nonzero(raw_mask)
    radius = max(3, int(round(min(height, width) * margin_ratio)))
    radius = min(radius, 40)
    base_stats["refine_margin_px"] = radius
    pad = radius + 3
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(width, int(xs.max()) + pad + 1)
    y1 = min(height, int(ys.max()) + pad + 1)

    mask_crop = raw_mask[y0:y1, x0:x1]
    image_crop = image_bgr[y0:y1, x0:x1]
    search_kernel = _make_ellipse_kernel(radius)
    half_kernel = _make_ellipse_kernel(max(2, radius // 2))
    third_kernel = _make_ellipse_kernel(max(2, radius // 3))

    search_region = cv2.dilate(mask_crop, search_kernel, iterations=1) > 0
    core = cv2.erode(mask_crop, half_kernel, iterations=1) > 0
    foreground_seed = cv2.erode(mask_crop, third_kernel, iterations=1) > 0
    near_region = cv2.dilate(mask_crop, half_kernel, iterations=1) > 0
    background_seed = search_region & ~near_region

    if np.count_nonzero(foreground_seed) < 25 or np.count_nonzero(background_seed) < 25:
        base_stats["refinement_reason"] = "fallback_insufficient_seeds"
        return raw_mask, base_stats

    lab = cv2.cvtColor(image_crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    foreground_pixels = _robust_sample(lab[foreground_seed])
    background_pixels = _robust_sample(lab[background_seed])
    foreground_center = np.median(foreground_pixels, axis=0)
    background_center = np.median(background_pixels, axis=0)
    combined = np.vstack([foreground_pixels, background_pixels])
    channel_scale = np.maximum(np.std(combined, axis=0), 5.0)
    color_separation = float(
        np.linalg.norm((foreground_center - background_center) / channel_scale)
    )
    base_stats["color_separation"] = color_separation
    if color_separation < minimum_color_separation:
        base_stats["refinement_reason"] = "fallback_low_color_separation"
        return raw_mask, base_stats

    distance_foreground = np.sum(
        ((lab - foreground_center) / channel_scale) ** 2, axis=2
    )
    distance_background = np.sum(
        ((lab - background_center) / channel_scale) ** 2, axis=2
    )
    color_advantage = distance_background - distance_foreground
    variable_region = search_region & ~core
    variable_values = color_advantage[variable_region]
    if variable_values.size < 25:
        base_stats["refinement_reason"] = "fallback_insufficient_search_band"
        return raw_mask, base_stats
    color_scale = max(float(np.std(variable_values)), 1e-6)
    normalized_color = (
        color_advantage - float(np.median(variable_values))
    ) / color_scale
    inside_distance = cv2.distanceTransform(mask_crop, cv2.DIST_L2, 3)
    outside_distance = cv2.distanceTransform(1 - mask_crop, cv2.DIST_L2, 3)
    signed_shape_prior = np.clip(
        (inside_distance - outside_distance) / max(float(radius), 1.0), -1.0, 1.0
    )
    decision_score = normalized_color + signed_shape_prior

    target_variable_area = int(mask_crop.sum()) - int(np.count_nonzero(core))
    variable_flat = np.flatnonzero(variable_region.ravel())
    target_variable_area = int(np.clip(target_variable_area, 0, variable_flat.size))
    selected = np.zeros(mask_crop.size, dtype=bool)
    if target_variable_area > 0:
        scores = decision_score.ravel()[variable_flat]
        if target_variable_area == variable_flat.size:
            selected[variable_flat] = True
        else:
            top_indices = np.argpartition(scores, -target_variable_area)[
                -target_variable_area:
            ]
            selected[variable_flat[top_indices]] = True
    candidate = selected.reshape(mask_crop.shape) | core
    candidate = cv2.morphologyEx(
        candidate.astype(np.uint8),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )
    candidate = _largest_component_overlapping(candidate, mask_crop)
    if candidate is None:
        base_stats["refinement_reason"] = "fallback_no_overlapping_component"
        return raw_mask, base_stats

    raw_refined_iou = _mask_iou(mask_crop, candidate)
    candidate_area = int(candidate.sum())
    area_ratio = candidate_area / max(1, int(mask_crop.sum()))
    raw_edge_score = _boundary_edge_score(image_crop, mask_crop)
    candidate_edge_score = _boundary_edge_score(image_crop, candidate)
    edge_score_gain = (candidate_edge_score - raw_edge_score) / max(
        raw_edge_score, 1e-6
    )
    base_stats.update(
        {
            "refined_mask_area_px": candidate_area,
            "area_ratio": float(area_ratio),
            "raw_refined_iou": float(raw_refined_iou),
            "candidate_raw_iou": float(raw_refined_iou),
            "candidate_area_ratio": float(area_ratio),
            "raw_edge_score": float(raw_edge_score),
            "candidate_edge_score": float(candidate_edge_score),
            "edge_score_gain": float(edge_score_gain),
        }
    )
    if raw_refined_iou < minimum_iou:
        base_stats["refinement_reason"] = "fallback_iou_gate"
    elif edge_score_gain < minimum_edge_score_gain:
        base_stats["refinement_reason"] = "fallback_edge_score_gate"
    elif not minimum_area_ratio <= area_ratio <= maximum_area_ratio:
        base_stats["refinement_reason"] = "fallback_area_gate"
    else:
        refined = np.zeros_like(raw_mask, dtype=np.uint8)
        refined[y0:y1, x0:x1] = candidate
        if np.array_equal(refined, raw_mask):
            base_stats["refinement_reason"] = "unchanged"
            return raw_mask, base_stats
        base_stats["refinement_applied"] = True
        base_stats["refinement_reason"] = "accepted_lab_boundary_refinement"
        return refined, base_stats

    base_stats["refined_mask_area_px"] = raw_area
    base_stats["area_ratio"] = 1.0
    base_stats["raw_refined_iou"] = 1.0
    return raw_mask, base_stats


def _mask_external_contours(mask: np.ndarray) -> list[np.ndarray]:
    contours_info = cv2.findContours(
        np.ascontiguousarray((mask > 0).astype(np.uint8)),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    return list(contours_info[0] if len(contours_info) == 2 else contours_info[1])


def _resolve_refined_overlaps(
    raw_masks: list[np.ndarray],
    refined_masks: list[np.ndarray],
    refinement_stats: list[dict],
) -> None:
    """Conservatively revert accepted refinements if instances overlap."""
    for first in range(len(refined_masks)):
        for second in range(first + 1, len(refined_masks)):
            if np.any((refined_masks[first] > 0) & (refined_masks[second] > 0)):
                for index in (first, second):
                    if refinement_stats[index]["refinement_applied"]:
                        refined_masks[index] = raw_masks[index].copy()
                        refinement_stats[index].update(
                            {
                                "refined_mask_area_px": int(raw_masks[index].sum()),
                                "area_ratio": 1.0,
                                "raw_refined_iou": 1.0,
                                "refinement_applied": False,
                                "refinement_reason": "fallback_instance_overlap",
                            }
                        )


def _unchanged_refinement_stats(raw_mask: np.ndarray) -> dict:
    raw_area = int(np.count_nonzero(raw_mask))
    return {
        "raw_mask_area_px": raw_area,
        "refined_mask_area_px": raw_area,
        "area_ratio": 1.0,
        "raw_refined_iou": 1.0,
        "color_separation": None,
        "raw_edge_score": None,
        "candidate_edge_score": None,
        "edge_score_gain": None,
        "candidate_raw_iou": None,
        "candidate_area_ratio": None,
        "refine_margin_px": 0,
        "refinement_applied": False,
        "refinement_reason": "disabled",
    }


def _draw_polyline(image, points_xy, color, thickness):
    if points_xy is None or len(points_xy) < 2:
        return
    points = np.round(points_xy).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(image, [points], False, color, thickness, lineType=cv2.LINE_AA)


def _put_text_box(image, text, origin, font_scale, thickness=2):
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(
        text, font, font_scale, thickness
    )
    x = max(3, min(int(origin[0]), max(3, image.shape[1] - text_width - 8)))
    y = max(text_height + 8, min(int(origin[1]), image.shape[0] - baseline - 5))
    cv2.rectangle(
        image,
        (x - 4, y - text_height - baseline - 4),
        (x + text_width + 4, y + baseline + 4),
        (10, 10, 10),
        cv2.FILLED,
    )
    cv2.putText(
        image,
        text,
        (x, y),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        lineType=cv2.LINE_AA,
    )


def _put_index_label(image, pod_index, origin, font_scale, thickness=2):
    """Draw only the pod index, without a filled measurement-value box."""
    text = f"#{pod_index}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(
        text, font, font_scale, thickness
    )
    x = max(3, min(int(origin[0]), max(3, image.shape[1] - text_width - 5)))
    y = max(text_height + 5, min(int(origin[1]), image.shape[0] - baseline - 5))
    cv2.putText(
        image,
        text,
        (x, y),
        font,
        font_scale,
        (0, 0, 0),
        thickness + 3,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        image,
        text,
        (x, y),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
        lineType=cv2.LINE_AA,
    )


def _draw_summary_panel(image: np.ndarray, summary: dict) -> None:
    lines = [
        f"PODS: {summary['count']}",
        f"MEAN L/W: {summary['avg_length']:.2f} / {summary['avg_width']:.2f} cm",
        f"MEAN OUTER/INNER: {summary['avg_outer_side_length']:.2f} / {summary['avg_inner_side_length']:.2f} cm",
        f"MEAN CURVATURE: {summary['avg_curvature']:.3f}",
        f"SCALE: {summary['pixel_to_cm']:.6f} cm/px",
    ]
    short_side = min(image.shape[:2])
    font_scale = float(np.clip(short_side / 1800.0, 0.5, 1.0))
    thickness = 2 if font_scale < 0.9 else 3
    font = cv2.FONT_HERSHEY_SIMPLEX
    sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
    max_width = max(size[0] for size in sizes)
    text_height = max(size[1] for size in sizes)
    pad = max(8, int(round(10 * font_scale)))
    gap = max(7, int(round(9 * font_scale)))
    step = text_height + gap
    x0, y0 = 8, 8
    panel_width = max_width + 2 * pad
    panel_height = 2 * pad + len(lines) * step - gap
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + panel_width, y0 + panel_height), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.80, image, 0.20, 0, image)
    cv2.rectangle(image, (x0, y0), (x0 + panel_width, y0 + panel_height), (220, 220, 220), 1)
    y = y0 + pad + text_height
    for line in lines:
        cv2.putText(image, line, (x0 + pad, y), font, font_scale, (0, 255, 255), thickness, cv2.LINE_AA)
        y += step


def _draw_measurements(image: np.ndarray, debug_items: list[dict], summary: dict) -> np.ndarray:
    result = image.copy()
    short_side = min(result.shape[:2])
    line_width = max(2, int(round(short_side / 900)))
    point_radius = max(5, int(round(short_side / 350)))
    font_scale = float(np.clip(short_side / 1800.0, 0.55, 1.05))

    for item in debug_items:
        if item.get("raw_contours"):
            cv2.drawContours(
                result,
                item["raw_contours"],
                -1,
                (255, 255, 0),
                line_width,
                lineType=cv2.LINE_AA,
            )
        cv2.drawContours(result, [item["contour"]], -1, (255, 0, 255), line_width, lineType=cv2.LINE_AA)
        rectangle = np.round(cv2.boxPoints(item["min_rect"])).astype(np.int32)
        cv2.drawContours(result, [rectangle], 0, (0, 255, 0), line_width, lineType=cv2.LINE_AA)
        _draw_polyline(result, item["outer_arc"], (0, 165, 255), line_width)
        point1 = tuple(np.round(item["endpoint1_xy"]).astype(int))
        point2 = tuple(np.round(item["endpoint2_xy"]).astype(int))
        cv2.line(result, point1, point2, (0, 255, 255), line_width, cv2.LINE_AA)
        cv2.circle(result, point1, point_radius, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.circle(result, point2, point_radius, (0, 0, 255), -1, cv2.LINE_AA)
        center_x, center_y = item["circle_center_xy"]
        # Keep the complete blue stroke inside the measured circle/contour.
        radius = int(
            math.floor(
                float(item["circle_radius_px"]) - (line_width / 2.0 + 1.0)
            )
        )
        if radius > 0:
            cv2.circle(result, (center_x, center_y), radius, (255, 0, 0), line_width, cv2.LINE_AA)
        label_x, label_y = item["centroid"]
        _put_index_label(
            result,
            item["pod_index"],
            (label_x - 12, label_y + 12),
            font_scale,
            thickness=max(1, line_width),
        )

    return result


class PodMeasurementEngine:
    """Run segmentation and measurement for one BGR image."""

    def __init__(
        self,
        model,
        pixel_to_cm: float = 0.007433,
        imgsz: int = 1024,
        confidence: float = 0.25,
        iou: float = 0.70,
        class_id: int = 0,
        refine_boundary: bool = False,
        refine_margin_ratio: float = 0.004,
        minimum_color_separation: float = 1.25,
        minimum_raw_refined_iou: float = 0.95,
        minimum_edge_score_gain: float = 0.12,
        minimum_area_ratio: float = 0.85,
        maximum_area_ratio: float = 1.15,
    ):
        self.model = model
        self.pixel_to_cm = float(pixel_to_cm)
        self.imgsz = int(imgsz)
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.class_id = int(class_id)
        self.refine_boundary = bool(refine_boundary)
        self.refine_margin_ratio = float(refine_margin_ratio)
        self.minimum_color_separation = float(minimum_color_separation)
        self.minimum_raw_refined_iou = float(minimum_raw_refined_iou)
        self.minimum_edge_score_gain = float(minimum_edge_score_gain)
        self.minimum_area_ratio = float(minimum_area_ratio)
        self.maximum_area_ratio = float(maximum_area_ratio)

    def analyze(self, image: np.ndarray) -> dict:
        if image is None or image.size == 0:
            raise ValueError("输入图像为空")
        if not np.isfinite(self.pixel_to_cm) or self.pixel_to_cm <= 0:
            raise ValueError("像素标定值必须为正数")

        results = self.model.predict(
            image,
            imgsz=self.imgsz,
            conf=self.confidence,
            iou=self.iou,
            retina_masks=True,
            verbose=False,
        )
        result = results[0] if results else None
        height, width = image.shape[:2]
        detections = []
        if (
            result is not None
            and getattr(result, "masks", None) is not None
            and getattr(result, "boxes", None) is not None
        ):
            masks = result.masks.data.cpu().numpy()
            boxes = result.boxes.xyxy.cpu().numpy()
            confidences = result.boxes.conf.cpu().numpy()
            class_ids = result.boxes.cls.cpu().numpy().astype(int)
            for mask, box, confidence, class_id in zip(
                masks, boxes, confidences, class_ids
            ):
                if int(class_id) != self.class_id:
                    continue
                if mask.shape != (height, width):
                    mask = cv2.resize(
                        mask.astype(np.float32),
                        (width, height),
                        interpolation=cv2.INTER_NEAREST,
                    )
                detections.append(
                    {
                        "mask": np.ascontiguousarray((mask > 0.5).astype(np.uint8)),
                        "box": np.asarray(box, dtype=float),
                        "confidence": float(confidence),
                        "class_id": int(class_id),
                    }
                )
        detections.sort(key=lambda item: (item["box"][1], item["box"][0]))

        raw_masks = [item["mask"] for item in detections]
        refined_masks = []
        refinement_stats = []
        if self.refine_boundary:
            for raw_mask in raw_masks:
                refined, stats = _refine_instance_mask(
                    image,
                    raw_mask,
                    self.refine_margin_ratio,
                    self.minimum_color_separation,
                    self.minimum_raw_refined_iou,
                    self.minimum_edge_score_gain,
                    self.minimum_area_ratio,
                    self.maximum_area_ratio,
                )
                refined_masks.append(refined)
                refinement_stats.append(stats)
            _resolve_refined_overlaps(raw_masks, refined_masks, refinement_stats)
        else:
            for raw_mask in raw_masks:
                refined_masks.append(raw_mask.copy())
                refinement_stats.append(_unchanged_refinement_stats(raw_mask))

        full_mask = np.zeros((height, width), dtype=np.uint8)
        for refined_mask in refined_masks:
            full_mask |= refined_mask
        isolated = _create_black_background(image, full_mask)

        rows = []
        debug_items = []
        for pod_index, detection in enumerate(detections, start=1):
            raw_mask = raw_masks[pod_index - 1]
            refined_mask = refined_masks[pod_index - 1]
            stats = refinement_stats[pod_index - 1]
            row, debug = _measure_one_pod(
                isolated,
                refined_mask,
                pod_index,
                detection["confidence"],
                self.pixel_to_cm,
            )
            row.update(
                {
                    "class_id": detection["class_id"],
                    **stats,
                }
            )
            if row.get("status") == "ok" and debug is not None:
                rows.append(row)
                debug["raw_contours"] = (
                    _mask_external_contours(raw_mask)
                    if stats["refinement_applied"]
                    else []
                )
                debug_items.append(debug)

        summary = _build_summary(rows, len(detections), self.pixel_to_cm)
        annotated = _draw_measurements(isolated, debug_items, summary)
        return {
            "annotated_image": annotated,
            "isolated_image": isolated,
            "summary": summary,
            "pods": rows,
        }
