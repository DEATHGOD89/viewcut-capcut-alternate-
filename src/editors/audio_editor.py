from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

from utils.ffmpeg_wrapper import FFmpegWrapper
from core.hardware import HardwareInfo
from utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class AudioSegment:
    start: float
    end: float
    volume: float
    fade_in: float = 0
    fade_out: float = 0

class AudioEditor:
    def __init__(self):
        self.hardware = HardwareInfo()
        self.settings = self.hardware.get_optimal_settings()
        self.ffmpeg = FFmpegWrapper(self.settings)

    def extract_audio(self, input_path: str, output_path: str = None) -> str:
        if not output_path:
            output_path = f"{Path(input_path).stem}_audio.mp3"

        cmd = self.ffmpeg.build_extract_audio(input_path, output_path)
        return self._execute(cmd)

    def adjust_volume(self, input_path: str, output_path: str,
                     gain: float, apply_to: str = 'all') -> str:
        if apply_to == 'all':
            cmd = self.ffmpeg.build_volume(input_path, output_path, gain)
        else:
            start, end = map(float, apply_to.split('-'))
            cmd = self.ffmpeg.build_volume_segment(input_path, output_path,
                                                  gain, start, end)
        return self._execute(cmd)

    def adjust_multiple_segments(self, input_path: str, output_path: str,
                                segments: List[Dict]) -> str:
        cmd = self.ffmpeg.build_complex_volume(input_path, output_path, segments)
        return self._execute(cmd)

    def fade_audio(self, input_path: str, output_path: str,
                  fade_in: float = 0, fade_out: float = 0) -> str:
        cmd = self.ffmpeg.build_fade(input_path, output_path, fade_in, fade_out)
        return self._execute(cmd)

    def normalize_audio(self, input_path: str, output_path: str,
                       target_lufs: float = -16.0) -> str:
        cmd = self.ffmpeg.build_normalize(input_path, output_path, target_lufs)
        return self._execute(cmd)

    def voice_boost(self, input_path: str, output_path: str,
                   voice_gain: float = 2.0, music_gain: float = 0.5) -> str:
        cmd = self.ffmpeg.build_voice_boost(input_path, output_path,
                                           voice_gain, music_gain)
        return self._execute(cmd)

    def extract_voice(self, input_path: str, output_path: str) -> str:
        cmd = self.ffmpeg.build_vocal_extract(input_path, output_path)
        return self._execute(cmd)

    def mix_audio(self, video_path: str, audio_path: str,
                 output_path: str, volume: float = 1.0) -> str:
        cmd = self.ffmpeg.build_audio_mix(video_path, audio_path,
                                         output_path, volume)
        return self._execute(cmd)

    def _execute(self, cmd: List[str]) -> str:
        cb = getattr(self, 'progress_callback', None)
        cc = getattr(self, 'cancel_check', None)
        return self.ffmpeg.execute(cmd, cb, cc)
