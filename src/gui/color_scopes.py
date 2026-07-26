import cv2
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget, QComboBox
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt

class ColorScopesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #121214; border: 1px solid #222228; border-radius: 6px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Header controls
        self.scope_type_combo = QComboBox(self)
        self.scope_type_combo.addItems(["📊 RGB Parade", "📈 Luminance Waveform", "📉 Brightness Histogram"])
        self.scope_type_combo.setStyleSheet("""
            QComboBox {
                background: #1e1e24;
                color: #00ffcc;
                border: 1px solid #00ffcc;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        self.scope_type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.scope_type_combo)

        # Scope Display Label
        self.scope_label = QLabel(self)
        self.scope_label.setAlignment(Qt.AlignCenter)
        self.scope_label.setFixedHeight(160)
        self.scope_label.setStyleSheet("background: #08080a; border: 1px solid #1a1a20; border-radius: 4px;")
        layout.addWidget(self.scope_label)

        self._current_image = None

    def update_frame(self, frame_bgr: np.ndarray):
        """Updates the scopes visualization from a BGR OpenCV NumPy array."""
        if frame_bgr is None or frame_bgr.size == 0:
            return

        self._current_image = frame_bgr
        self.render_scopes()

    def _on_type_changed(self, idx):
        if self._current_image is not None:
            self.render_scopes()

    def render_scopes(self):
        if self._current_image is None:
            return

        mode = self.scope_type_combo.currentIndex()
        h, w = 160, 320
        canvas = np.zeros((h, w, 3), dtype=np.uint8)

        # Downsample source frame for high FPS scope calculations
        small = cv2.resize(self._current_image, (120, 90))

        sh_, sw_ = small.shape[:2]
        if mode == 0:
            # RGB PARADE (vectorized — the per-pixel Python loops were ~100x slower)
            sub_w = w // 3
            cols = np.tile(np.arange(sw_), sh_)
            for c_idx, color in enumerate([(255, 50, 50), (50, 255, 50), (50, 100, 255)]):  # B, G, R
                channel = small[:, :, c_idx]
                x_pos = c_idx * sub_w + ((cols / sw_) * sub_w).astype(np.int32)
                y_pos = (h - 1) - ((channel.flatten() / 255.0) * (h - 1)).astype(np.int32)
                canvas[y_pos, x_pos] = color
        elif mode == 1:
            # LUMINANCE WAVEFORM (vectorized)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            cols = np.tile(np.arange(sw_), sh_)
            x_pos = ((cols / sw_) * w).astype(np.int32)
            y_pos = (h - 1) - ((gray.flatten() / 255.0) * (h - 1)).astype(np.int32)
            canvas[y_pos, x_pos] = (0, 255, 204)  # Cyan scope intensity
        else:
            # HISTOGRAM
            # (removed: an unused 256^3-bin cv2.calcHist call here allocated ~67MB per frame)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist_g = cv2.calcHist([gray], [0], None, [256], [0, 256])
            cv2.normalize(hist_g, hist_g, 0, h - 10, cv2.NORM_MINMAX)

            for i in range(1, 256):
                pt1 = (int((i - 1) * (w / 256.0)), h - 1 - int(hist_g[i - 1][0]))
                pt2 = (int(i * (w / 256.0)), h - 1 - int(hist_g[i][0]))
                cv2.line(canvas, pt1, pt2, (0, 255, 204), 1)

        # Convert to PySide6 QPixmap
        bytes_per_line = 3 * w
        q_img = QImage(canvas.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.scope_label.setPixmap(QPixmap.fromImage(q_img))
