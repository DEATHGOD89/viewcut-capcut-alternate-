from typing import Dict, List

from utils.ffmpeg_wrapper import FFmpegWrapper
from utils.logger import get_logger

logger = get_logger(__name__)

class RenderEngine:
    def __init__(self, settings: Dict = None):
        self.settings = settings or {}
        self.ffmpeg = FFmpegWrapper(self.settings)

    def render(self, input_path: str, output_path: str,
               start_time: float = 0, end_time: float = None,
               width: int = None, height: int = None,
               fps: int = None, codec: str = None,
               quality: str = 'source') -> str:
        if quality == 'source':
            info = self.ffmpeg.get_video_info(input_path)
            width = width or info.get('width')
            height = height or info.get('height')
            fps = fps or info.get('fps', 30)
            codec = codec or 'libx264'
        elif quality == 'lossless':
            width = width or 0
            height = height or 0
            codec = codec or 'libx264'

        cmd = self.ffmpeg.build_render(
            input_path, output_path,
            start_time, end_time,
            width or 0, height or 0,
            fps or 0, codec or 'libx264'
        )

        return self._execute(cmd)

    def _execute(self, cmd: List[str]) -> str:
        cb = getattr(self, 'progress_callback', None)
        cc = getattr(self, 'cancel_check', None)
        return self.ffmpeg.execute(cmd, cb, cc)
