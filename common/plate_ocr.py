"""
Plate OCR helper for soybean variety tags.

The reader is intentionally isolated from the UI layer. It locates red/green
plates in the lower-left part of the image, runs OCR on rotated variants, then
normalizes the result according to business rules:

- red plate: use the code as printed
- green plate: replace the trailing P + digit with N5

Expected printed code format: two letters + three digits + A/B + P + digit,
for example DW027BP8.
"""
from dataclasses import dataclass
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np


CODE_PATTERN = re.compile(r"^[A-Z]{2}\d{3}[AB]P\d$")


@dataclass
class PlateReadResult:
    success: bool
    color: str = ""
    raw_code: str = ""
    final_code: str = ""
    confidence: float = 0.0
    error: str = ""
    text_candidates: Tuple[str, ...] = ()
    plate_box: Tuple[int, int, int, int] = ()


class PlateCodeReader:
    """Read variety code from red/green tag plates."""

    def __init__(self, lower_left_roi=(0.0, 0.60, 0.0, 1.0), min_plate_area_ratio=0.002):
        # Ratios are x1, x2, y1, y2 in the full image.
        self.lower_left_roi = lower_left_roi
        self.min_plate_area_ratio = min_plate_area_ratio
        self._ocr = None
        self._ocr_error = None

    def read(self, image: np.ndarray) -> PlateReadResult:
        if image is None or image.size == 0:
            return PlateReadResult(False, error="empty image")

        try:
            search_regions = []
            roi, offset = self._crop_lower_left(image)
            search_regions.append(("left-area", roi, offset))
            search_regions.append(("full-image", image, (0, 0)))

            last_result = PlateReadResult(False, error="plate not found")
            for region_name, region, offset in search_regions:
                located_plates = self._locate_plates_by_color(region)
                if not located_plates:
                    continue

                color, plate_crop, local_box = located_plates[0]
                plate_box = self._offset_box(local_box, offset)
                result = self._read_plate_crop(plate_crop, color)
                result.plate_box = plate_box
                if result.success:
                    return result
                last_result = result
                last_result.error = f"{region_name}: {color}: {result.error}"

            return last_result
        except Exception as exc:
            return PlateReadResult(False, error=str(exc))

    def _read_plate_crop(self, plate_crop: np.ndarray, color: str) -> PlateReadResult:
        variants = self._make_ocr_variants(plate_crop)
        candidates, best_code, best_score, matched_pattern = self._run_ocr_variants(variants)

        if self._ocr is None and self._ocr_error:
            return PlateReadResult(False, color=color, error=f"OCR dependency not available: {self._ocr_error}")

        all_texts: List[str] = []
        for text, score in candidates:
            all_texts.append(text)

        if not best_code:
            return PlateReadResult(
                False,
                color=color,
                error="code pattern not matched",
                text_candidates=tuple(all_texts),
            )

        final_code = self._apply_color_rule(best_code, color) if matched_pattern else best_code
        return PlateReadResult(
            True,
            color=color,
            raw_code=best_code,
            final_code=final_code,
            confidence=best_score,
            text_candidates=tuple(all_texts),
        )

    def _crop_lower_left(self, image: np.ndarray):
        h, w = image.shape[:2]
        x1r, x2r, y1r, y2r = self.lower_left_roi
        x1 = max(0, min(w - 1, int(w * x1r)))
        x2 = max(x1 + 1, min(w, int(w * x2r)))
        y1 = max(0, min(h - 1, int(h * y1r)))
        y2 = max(y1 + 1, min(h, int(h * y2r)))
        return image[y1:y2, x1:x2].copy(), (x1, y1)

    def _locate_plate_by_color(self, roi: np.ndarray):
        candidates = self._locate_plates_by_color(roi)
        if not candidates:
            return None
        return candidates[0]

    def _locate_plates_by_color(self, roi: np.ndarray):
        hsv_rgb = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
        hsv_bgr = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # First find large, saturated red/green blocks. Area alone is not
        # enough: tray rims can be large too, so avoid low-saturation dark
        # brown/black areas even when their hue is close to red. The camera
        # path may provide either RGB or BGR frames; green is mostly unchanged
        # by channel order, but red becomes blue in the wrong order.
        red_mask = cv2.bitwise_or(
            self._red_hsv_mask(hsv_rgb, saturation=48, value=40),
            self._red_hsv_mask(hsv_bgr, saturation=48, value=40),
        )
        red_regions = self._plate_like_regions(roi, red_mask)
        if not red_regions:
            red_mask = cv2.bitwise_or(
                self._red_hsv_mask(hsv_rgb, saturation=36, value=45),
                self._red_hsv_mask(hsv_bgr, saturation=36, value=45),
            )
            red_regions = self._plate_like_regions(roi, red_mask)

        green_mask = cv2.inRange(hsv_rgb, np.array([32, 42, 35]), np.array([98, 255, 255]))
        green_mask = cv2.bitwise_or(
            green_mask,
            cv2.inRange(hsv_bgr, np.array([32, 42, 35]), np.array([98, 255, 255])),
        )
        green_mask = cv2.bitwise_or(green_mask, self._green_rgb_fallback_mask(roi))

        candidates = []
        for area, crop, score, box in red_regions:
            candidates.append(("red", area, crop, score, box))
        for area, crop, score, box in self._plate_like_regions(roi, green_mask):
            candidates.append(("green", area, crop, score, box))
        if not candidates:
            return []

        min_area = roi.shape[0] * roi.shape[1] * self.min_plate_area_ratio
        candidates = [c for c in candidates if c[1] >= min_area]
        if not candidates:
            return []

        candidates.sort(key=lambda item: item[3], reverse=True)
        return [(color, crop, box) for color, _, crop, _, box in candidates[:1]]

    def _offset_box(self, box: Tuple[int, int, int, int], offset: Tuple[int, int]):
        x_offset, y_offset = offset
        x1, y1, x2, y2 = box
        return (x1 + x_offset, y1 + y_offset, x2 + x_offset, y2 + y_offset)

    def _red_hsv_mask(self, hsv: np.ndarray, saturation: int, value: int):
        red_mask1 = cv2.inRange(hsv, np.array([0, saturation, value]), np.array([25, 255, 255]))
        red_mask2 = cv2.inRange(hsv, np.array([145, saturation, value]), np.array([180, 255, 255]))
        return cv2.bitwise_or(red_mask1, red_mask2)

    def _green_rgb_fallback_mask(self, roi: np.ndarray):
        rgb = roi.astype(np.int16)
        r = rgb[:, :, 0]
        g = rgb[:, :, 1]
        b = rgb[:, :, 2]

        green_dominant = (g > 75) & (g > r + 18) & (g > b + 18)
        green_bright = (g > 95) & (g > r * 1.15) & (g > b * 1.15)
        mask = np.where(green_dominant | green_bright, 255, 0).astype(np.uint8)
        return mask

    def _largest_color_region(self, roi: np.ndarray, mask: np.ndarray):
        regions = self._plate_like_regions(roi, mask, limit=1)
        if not regions:
            return None
        area, crop, _, _ = regions[0]
        return area, crop

    def _plate_like_regions(self, roi: np.ndarray, mask: np.ndarray, limit=8):
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []

        regions = []
        for contour in contours:
            contour_score = self._score_plate_like_contour(contour, roi.shape)
            if contour_score <= 0:
                continue

            area = cv2.contourArea(contour)
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)
            bound_x, bound_y, bound_w, bound_h = cv2.boundingRect(contour)
            crop = self._warp_rect(roi, box)
            if crop is None or crop.size == 0:
                x, y, w, h = bound_x, bound_y, bound_w, bound_h
                pad = max(8, int(max(w, h) * 0.08))
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(roi.shape[1], x + w + pad)
                y2 = min(roi.shape[0], y + h + pad)
                crop = roi[y1:y2, x1:x2].copy()

            pad = max(8, int(max(bound_w, bound_h) * 0.08))
            x1 = max(0, bound_x - pad)
            y1 = max(0, bound_y - pad)
            x2 = min(roi.shape[1], bound_x + bound_w + pad)
            y2 = min(roi.shape[0], bound_y + bound_h + pad)
            regions.append((area, crop, contour_score, (x1, y1, x2, y2)))

        regions.sort(key=lambda item: item[2], reverse=True)
        return regions[:limit]

    def _choose_plate_like_contour(self, contours, image_shape):
        best_contour = None
        best_score = 0.0

        for contour in contours:
            score = self._score_plate_like_contour(contour, image_shape)

            if score > best_score:
                best_score = score
                best_contour = contour

        return best_contour

    def _score_plate_like_contour(self, contour, image_shape):
        area = cv2.contourArea(contour)
        if area <= 0:
            return 0.0

        image_area = image_shape[0] * image_shape[1]
        rect = cv2.minAreaRect(contour)
        width, height = rect[1]
        short_side = min(width, height)
        long_side = max(width, height)
        if short_side < 20 or long_side < 45:
            return 0.0

        aspect = long_side / max(short_side, 1.0)
        area_ratio = area / max(image_area, 1)

        if area_ratio < self.min_plate_area_ratio:
            return 0.0
        if area_ratio > 0.14:
            return 0.0
        if aspect < 1.25:
            return 0.0
        if aspect > 5.2:
            return 0.0

        score = area
        if 1.45 <= aspect <= 3.6:
            score *= 3.0
        elif aspect > 4.2:
            score *= 0.45

        return score

    def _warp_rect(self, image: np.ndarray, box: np.ndarray):
        pts = self._order_points(box.astype("float32"))
        tl, tr, br, bl = pts
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_width = int(max(width_a, width_b))
        max_height = int(max(height_a, height_b))
        if max_width < 20 or max_height < 20:
            return None

        dst = np.array(
            [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
            dtype="float32",
        )
        matrix = cv2.getPerspectiveTransform(pts, dst)
        return cv2.warpPerspective(image, matrix, (max_width, max_height))

    def _order_points(self, pts: np.ndarray):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    def _make_ocr_variants(self, crop: np.ndarray):
        if crop.shape[0] > crop.shape[1]:
            variants = [cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)]
        else:
            variants = [crop]

        variants.append(cv2.rotate(variants[0], cv2.ROTATE_180))
        variants.append(self._enhance_for_ocr(variants[0]))
        return variants

    def _enhance_for_ocr(self, image: np.ndarray):
        lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        merged = cv2.merge([l, a, b])
        return cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)

    def _run_ocr_variants(self, variants: List[np.ndarray]):
        ocr = self._get_ocr()
        results = []
        if ocr is None:
            return results, "", 0.0, False

        best_code = ""
        best_score = 0.0
        best_loose_code = ""
        best_loose_score = 0.0
        for img in variants:
            try:
                output = ocr(img)
            except Exception:
                continue
            parsed = self._parse_ocr_output(output)
            results.extend(parsed)

            for text, score in parsed:
                code = self._extract_code(text)
                if code and score >= best_score:
                    best_code = code
                    best_score = score
                loose_code = self._extract_loose_code(text)
                if loose_code and score >= best_loose_score:
                    best_loose_code = loose_code
                    best_loose_score = score
            if best_code:
                break

        if best_code:
            return results, best_code, best_score, True
        return results, best_loose_code, best_loose_score, False

    def _get_ocr(self):
        if self._ocr is not None or self._ocr_error is not None:
            return self._ocr

        errors = []
        try:
            from rapidocr import RapidOCR

            self._ocr = RapidOCR()
            return self._ocr
        except Exception as exc:
            errors.append(f"rapidocr: {exc}")

        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            return self._ocr
        except Exception as exc:
            errors.append(f"rapidocr_onnxruntime: {exc}")

        self._ocr_error = "; ".join(errors)
        self._ocr = None
        return self._ocr

    def _parse_ocr_output(self, output):
        # rapidocr >= 3 returns RapidOCROutput with txts/scores. The older
        # rapidocr_onnxruntime returns (results, elapsed), where each result
        # usually includes box, text, score.
        if hasattr(output, "txts") and hasattr(output, "scores"):
            txts = output.txts or []
            scores = output.scores or []
            return [(str(text), float(score)) for text, score in zip(txts, scores) if text]

        if isinstance(output, tuple):
            output = output[0]
        if not output:
            return []

        parsed = []
        for item in output:
            text = ""
            score = 0.0
            if isinstance(item, (list, tuple)):
                if len(item) >= 2:
                    text = str(item[1])
                if len(item) >= 3:
                    try:
                        score = float(item[2])
                    except Exception:
                        score = 0.0
            elif isinstance(item, dict):
                text = str(item.get("text", ""))
                try:
                    score = float(item.get("score", 0.0))
                except Exception:
                    score = 0.0
            if text:
                parsed.append((text, score))
        return parsed

    def _extract_code(self, text: str) -> str:
        compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if not compact:
            return ""

        candidates = []
        if len(compact) >= 8:
            for i in range(0, len(compact) - 7):
                candidates.append(compact[i : i + 8])
        else:
            candidates.append(compact)

        for candidate in candidates:
            fixed = self._fix_candidate(candidate)
            if CODE_PATTERN.match(fixed):
                return fixed
        return ""

    def _extract_loose_code(self, text: str) -> str:
        compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if len(compact) < 2:
            return ""
        return compact

    def _fix_candidate(self, value: str) -> str:
        value = value[:8].ljust(8, " ")
        chars = list(value)

        digit_to_letter = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "4": "A"}
        letter_to_digit = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"}

        for idx in (0, 1):
            chars[idx] = digit_to_letter.get(chars[idx], chars[idx])
        for idx in (2, 3, 4, 7):
            chars[idx] = letter_to_digit.get(chars[idx], chars[idx])

        if chars[5] not in ("A", "B"):
            chars[5] = digit_to_letter.get(chars[5], chars[5])
            if chars[5] not in ("A", "B"):
                chars[5] = "B"

        if chars[6] != "P":
            # P is fixed by the plate rule; OCR often reads it as F/R/D.
            chars[6] = "P"

        return "".join(chars).strip()

    def _apply_color_rule(self, code: str, color: str) -> str:
        if color == "green":
            return code[:-2] + "N5"
        return code
