from typing import List, Dict
from utils.ffmpeg_wrapper import FFmpegWrapper
from core.hardware import HardwareInfo
from utils.logger import get_logger

logger = get_logger(__name__)

class TransitionEditor:
    """
    Video Transition Editor supporting Fade, Dissolve, Wipe, and Slide transitions
    using FFmpeg hardware-accelerated xfade filter graphs.
    """
    TRANSITIONS = {
        'fade': 'fade',
        'dissolve': 'dissolve',
        'wipe_left': 'wipeleft',
        'wipe_right': 'wiperight',
        'slide_left': 'slideleft',
        'slide_right': 'slideright',
        'circle_crop': 'circlecrop',
        'rect_crop': 'rectcrop'
    }

    def __init__(self, settings: Dict = None):
        if settings is None:
            hw = HardwareInfo()
            settings = hw.get_optimal_settings()
        self.ffmpeg = FFmpegWrapper(settings)

    def get_xfade_filter_string(self, transition_type: str = 'fade', duration: float = 1.0, offset: float = 0.0) -> str:
        key = transition_type.lower().replace(' ', '_')
        expr = self.TRANSITIONS.get(key, 'fade')
        return f"xfade=transition={expr}:duration={duration:.2f}:offset={offset:.2f}"

    def build_transition_between_clips(self, clip1_path: str, clip2_path: str, output_path: str,
                                         transition_type: str = 'dissolve', duration: float = 1.0) -> List[str]:
        info1 = self.ffmpeg.get_video_info(clip1_path)
        dur1 = info1.get('duration', 5.0)
        offset = max(0.0, dur1 - duration)

        xfade_str = self.get_xfade_filter_string(transition_type, duration, offset)
        filter_str = f"[0:v][1:v]{xfade_str}[outv];[0:a][1:a]acrossfade=d={duration:.2f}[outa]"

        cmd = [
            self.ffmpeg.ffmpeg_path,
            '-i', clip1_path,
            '-i', clip2_path,
            '-filter_complex', filter_str,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',
            '-crf', '18',
            '-c:a', 'aac',
            '-y', output_path
        ]
        return cmd
