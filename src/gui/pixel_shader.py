import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

class PixelShaderEngine:
    @staticmethod
    def apply_color_grading(image_path_or_frame, b=0, c=0, s=0, t=0, e=0, dn=0, sh=0, timestamp=0.5):
        try:
            if isinstance(image_path_or_frame, str):
                cap = cv2.VideoCapture(image_path_or_frame)
                if timestamp > 0:
                    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ret, frame = cap.read()
                cap.release()
                if not ret or frame is None:
                    return None
            else:
                frame = image_path_or_frame.copy()

            # 1. Exposure & Contrast Scaling
            alpha_c = 1.0 + (c / 100.0)
            beta_b = (b * 1.5) + (e * 2.0)
            frame = cv2.convertScaleAbs(frame, alpha=max(0.1, alpha_c), beta=beta_b)

            # 2. Temperature Tuning (Red vs Blue channel balance)
            if t != 0:
                temp_factor = t / 100.0
                b_ch, g_ch, r_ch = cv2.split(frame)
                if t > 0:
                    r_ch = cv2.add(r_ch, int(temp_factor * 40))
                    b_ch = cv2.subtract(b_ch, int(temp_factor * 20))
                else:
                    b_ch = cv2.add(b_ch, int(abs(temp_factor) * 40))
                    r_ch = cv2.subtract(r_ch, int(abs(temp_factor) * 20))
                frame = cv2.merge([b_ch, g_ch, r_ch])

            # 3. Saturation (HSV S-channel scaling)
            if s != 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
                sat_factor = 1.0 + (s / 100.0)
                hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_factor, 0, 255)
                frame = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

            # 4. Denoise / Smooth
            if dn > 0:
                k = int(dn / 25) * 2 + 1
                if k >= 3:
                    frame = cv2.GaussianBlur(frame, (k, k), 0)

            # 5. Sharpness (Unsharp Masking)
            if sh > 0:
                amount = sh / 50.0
                blurred = cv2.GaussianBlur(frame, (0, 0), 3)
                frame = cv2.addWeighted(frame, 1.0 + amount, blurred, -amount, 0)

            # Convert BGR OpenCV image to QPixmap
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
            return QPixmap.fromImage(qimg)
        except Exception:
            return None
