import os
import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap
from editors.effect_stack import EffectStack
from utils.logger import get_logger

logger = get_logger(__name__)

class UnifiedRenderer:
    """Unified Rendering Engine powering BOTH Live Preview and Video Export."""

    # Cached VideoCapture per file so slider drags don't reopen the decoder each tick.
    _cap_cache = {}
    _MAX_PREVIEW_WIDTH = 1280

    @classmethod
    def _get_capture(cls, path):
        cap = cls._cap_cache.get(path)
        if cap is not None and cap.isOpened():
            return cap
        # Keep the cache tiny: release captures for other files
        for old_path in list(cls._cap_cache.keys()):
            if old_path != path:
                try:
                    cls._cap_cache.pop(old_path).release()
                except Exception:
                    pass
        cap = cv2.VideoCapture(path)
        cls._cap_cache[path] = cap
        return cap

    @classmethod
    def release_captures(cls):
        for cap in cls._cap_cache.values():
            try:
                cap.release()
            except Exception:
                pass
        cls._cap_cache.clear()

    @staticmethod
    def render_preview_frame(image_path_or_video: str, timestamp: float, effect_stack: EffectStack):
        """Renders a live preview frame at timestamp using the exact EffectStack parameters.

        Always returns a (QPixmap | None, ndarray | None) tuple so callers can
        safely unpack the result on every code path.
        """
        if not image_path_or_video or not os.path.exists(image_path_or_video):
            logger.warning(f"[UNIFIED RENDERER] Source file not found: {image_path_or_video}")
            return None, None

        try:
            # 1. Read decoded video frame at timestamp (cached OpenCV capture)
            cap = UnifiedRenderer._get_capture(image_path_or_video)
            if timestamp > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ret, frame = cap.read()

            if not ret or frame is None:
                # One retry with a fresh capture (file may have been replaced on disk)
                UnifiedRenderer._cap_cache.pop(image_path_or_video, None)
                try:
                    cap.release()
                except Exception:
                    pass
                cap = UnifiedRenderer._get_capture(image_path_or_video)
                if timestamp > 0:
                    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ret, frame = cap.read()

            if not ret or frame is None:
                logger.warning(f"[UNIFIED RENDERER] Failed to decode frame at {timestamp:.2f}s")
                return None, None

            # Downscale large frames for interactive speed (preview only — export is full-res)
            h0, w0 = frame.shape[:2]
            if w0 > UnifiedRenderer._MAX_PREVIEW_WIDTH:
                scale = UnifiedRenderer._MAX_PREVIEW_WIDTH / float(w0)
                frame = cv2.resize(
                    frame,
                    (UnifiedRenderer._MAX_PREVIEW_WIDTH, max(2, int(h0 * scale))),
                    interpolation=cv2.INTER_AREA
                )

            # 2. Apply EffectStack Parameters (Non-destructive matrix shading)
            # A. Exposure & Contrast Scaling
            b = effect_stack.brightness
            c = effect_stack.contrast
            s = effect_stack.saturation
            t = effect_stack.temperature
            e = effect_stack.exposure
            dn = effect_stack.denoise
            sh = effect_stack.sharpness

            alpha_c = max(0.1, 1.0 + (c / 100.0))
            beta_b = (b * 1.5) + (e * 2.0)
            frame = cv2.convertScaleAbs(frame, alpha=alpha_c, beta=beta_b)

            # B. Temperature Tuning (Red vs Blue channel balance)
            if t != 0.0:
                temp_factor = t / 100.0
                b_ch, g_ch, r_ch = cv2.split(frame)
                if t > 0:
                    r_ch = cv2.add(r_ch, int(temp_factor * 40))
                    b_ch = cv2.subtract(b_ch, int(temp_factor * 20))
                else:
                    b_ch = cv2.add(b_ch, int(abs(temp_factor) * 40))
                    r_ch = cv2.subtract(r_ch, int(abs(temp_factor) * 20))
                frame = cv2.merge([b_ch, g_ch, r_ch])

            # C. Saturation (HSV S-channel scaling)
            if s != 0.0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
                sat_factor = max(0.0, 1.0 + (s / 100.0))
                hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_factor, 0, 255)
                frame = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

            # D. Denoise / Smooth (Bilateral Edge-Preserving Skin Smoothing)
            if dn > 0.0:
                d_val = max(3, int(dn * 0.15))
                sigma = dn * 0.8
                frame = cv2.bilateralFilter(frame, d_val, sigma, sigma)

            # E. Sharpness (Unsharp Masking)
            if sh > 0.0:
                amount = sh / 50.0
                blurred = cv2.GaussianBlur(frame, (0, 0), 3)
                frame = cv2.addWeighted(frame, 1.0 + amount, blurred, -amount, 0)

            # Convert BGR OpenCV image to QPixmap for CanvasFrame display
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            return pix, frame
        except Exception as err:
            logger.error(f"[UNIFIED RENDERER] Error rendering preview frame: {err}", exc_info=True)
            return None, None

    @staticmethod
    def get_export_filtergraph(effect_stack: EffectStack) -> str:
        """Returns the exact FFmpeg filtergraph string for video export."""
        vf = effect_stack.to_ffmpeg_vf()
        logger.info(f"[UNIFIED RENDERER] Export Filtergraph: '{vf}'")
        return vf
