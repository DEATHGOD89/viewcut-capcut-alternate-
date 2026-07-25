from typing import List, Dict, Tuple
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class Keyframe:
    time: float
    position_x: float = 0.0  # Center offset X (-1.0 to 1.0)
    position_y: float = 0.0  # Center offset Y (-1.0 to 1.0)
    zoom: float = 1.0        # Scale multiplier (0.5 to 3.0)
    opacity: float = 1.0     # Opacity (0.0 to 1.0)

class KeyframeEditor:
    """
    Keyframe Animation Engine supporting position, zoom/scale, and opacity interpolation
    over timeline clip duration.
    """
    def __init__(self):
        self.keyframes: List[Keyframe] = []

    def add_keyframe(self, time: float, position_x: float = 0.0, position_y: float = 0.0, zoom: float = 1.0, opacity: float = 1.0):
        # Insert sorted by time
        kf = Keyframe(time, position_x, position_y, zoom, opacity)
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.time)

    def interpolate_at_time(self, time: float) -> Tuple[float, float, float, float]:
        """
        Returns (position_x, position_y, zoom, opacity) linearly interpolated at playhead time t.
        """
        if not self.keyframes:
            return (0.0, 0.0, 1.0, 1.0)
        if len(self.keyframes) == 1 or time <= self.keyframes[0].time:
            k = self.keyframes[0]
            return (k.position_x, k.position_y, k.zoom, k.opacity)
        if time >= self.keyframes[-1].time:
            k = self.keyframes[-1]
            return (k.position_x, k.position_y, k.zoom, k.opacity)

        # Find adjacent keyframe interval
        for i in range(len(self.keyframes) - 1):
            k1 = self.keyframes[i]
            k2 = self.keyframes[i + 1]
            if k1.time <= time <= k2.time:
                span = max(0.001, k2.time - k1.time)
                factor = (time - k1.time) / span
                px = k1.position_x + (k2.position_x - k1.position_x) * factor
                py = k1.position_y + (k2.position_y - k1.position_y) * factor
                zm = k1.zoom + (k2.zoom - k1.zoom) * factor
                op = k1.opacity + (k2.opacity - k1.opacity) * factor
                return (px, py, zm, op)

        return (0.0, 0.0, 1.0, 1.0)

    def get_zoompan_filter_string(self, duration: float, fps: float = 30.0) -> str:
        """
        Generates FFmpeg zoompan filter string from keyframe list.
        """
        if len(self.keyframes) < 2:
            return ""
        z1 = self.keyframes[0].zoom
        z2 = self.keyframes[-1].zoom
        frames = max(1, int(duration * fps))
        return f"zoompan=z='min(max(zoom+({z2:.2f}-{z1:.2f})/{frames:.1f},{z1:.2f}),{z2:.2f})':d={frames}:s=1920x1080"
