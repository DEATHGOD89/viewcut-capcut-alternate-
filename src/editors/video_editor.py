import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict
from dataclasses import dataclass

from utils.ffmpeg_wrapper import FFmpegWrapper
from core.hardware import HardwareInfo
from utils.logger import get_logger

logger = get_logger(__name__)



class VideoEditor:
    def __init__(self):
        self.hardware = HardwareInfo()
        self.settings = self.hardware.get_optimal_settings()
        self.ffmpeg = FFmpegWrapper(self.settings)
        self.temp_dir = tempfile.mkdtemp(prefix='vedit_')
        import atexit
        atexit.register(self.cleanup)
        self._sweep_stale_temp_dirs()
        self.project = {
            'clips': [],
            'audio_tracks': [],
            'timeline': [],
            'export_settings': {}
        }
        logger.info(f"VideoEditor initialized with settings: {self.settings}")

    def __del__(self):
        self.cleanup()

    def trim_video(self, input_path: str, output_path: str,
                  start_time: float, end_time: float) -> str:
        duration = end_time - start_time

        if self._can_trim_lossless(input_path):
            cmd = self.ffmpeg.build_lossless_trim(input_path, output_path, start_time, duration)
        else:
            cmd = self.ffmpeg.build_trim(input_path, output_path, start_time, duration)

        return self._execute(cmd)

    def _can_trim_lossless(self, input_path: str) -> bool:
        # Stream copy cutting on non-keyframes causes frozen/black initial frames.
        # Force frame-accurate re-encoding trim.
        return False

    def split_video(self, input_path: str, split_points: List[float]) -> List[str]:
        if not split_points:
            return [input_path]

        outputs = []
        prev_time = 0
        info = self.get_video_info(input_path)
        total_duration = info.get('duration', 0)

        for i, split_time in enumerate(split_points):
            split_time = min(split_time, total_duration)
            if split_time <= prev_time:
                continue
            output_path = f"{Path(input_path).stem}_part{i+1}{Path(input_path).suffix}"
            duration = split_time - prev_time
            if self._can_trim_lossless(input_path):
                cmd = self.ffmpeg.build_lossless_trim(input_path, output_path,
                                                     prev_time, duration)
            else:
                cmd = self.ffmpeg.build_trim(input_path, output_path,
                                            prev_time, duration)
            self._execute(cmd)
            outputs.append(output_path)
            prev_time = split_time

        if prev_time < total_duration:
            output_path = f"{Path(input_path).stem}_part{len(outputs)+1}{Path(input_path).suffix}"
            remaining = total_duration - prev_time
            if self._can_trim_lossless(input_path):
                cmd = self.ffmpeg.build_lossless_trim(input_path, output_path,
                                                     prev_time, remaining)
            else:
                cmd = self.ffmpeg.build_trim(input_path, output_path,
                                            prev_time, remaining)
            self._execute(cmd)
            outputs.append(output_path)

        return outputs

    def change_resolution(self, input_path: str, output_path: str,
                         target_width: int, target_height: int,
                         aspect_ratio: str = 'keep') -> str:
        if aspect_ratio == 'keep':
            info = self.ffmpeg.get_video_info(input_path)
            orig_width = info.get('width', 1920)
            orig_height = info.get('height', 1080)

            if target_width / target_height > orig_width / orig_height:
                target_width = int(orig_width * target_height / orig_height)
            else:
                target_height = int(orig_height * target_width / orig_width)

        if aspect_ratio == '9:16':
            cmd = self.ffmpeg.build_aspect_convert(input_path, output_path,
                                                  target_width, target_height)
        else:
            cmd = self.ffmpeg.build_resize(input_path, output_path,
                                          target_width, target_height)

        return self._execute(cmd)

    def reverse_video(self, input_path: str, output_path: str) -> str:
        cmd = self.ffmpeg.build_reverse(input_path, output_path)
        return self._execute(cmd)

    def change_speed(self, input_path: str, output_path: str, speed: float) -> str:
        cmd = self.ffmpeg.build_speed_change(input_path, output_path, speed)
        return self._execute(cmd)

    def extract_audio(self, input_path: str, output_path: str = None) -> str:
        if not output_path:
            output_path = f"{Path(input_path).stem}_audio.mp3"

        cmd = self.ffmpeg.build_extract_audio(input_path, output_path)
        return self._execute(cmd)

    def mute_video(self, input_path: str, output_path: str) -> str:
        cmd = self.ffmpeg.build_mute(input_path, output_path)
        return self._execute(cmd)

    def adjust_audio_volume(self, input_path: str, output_path: str,
                           gain: float, start_time: float = None,
                           end_time: float = None) -> str:
        if start_time is not None and end_time is not None:
            cmd = self.ffmpeg.build_volume_segment(input_path, output_path,
                                                  gain, start_time, end_time)
        else:
            cmd = self.ffmpeg.build_volume(input_path, output_path, gain)

        return self._execute(cmd)

    def adjust_audio_segment(self, input_path: str, output_path: str,
                            segments: List[Dict]) -> str:
        cmd = self.ffmpeg.build_complex_volume(input_path, output_path, segments)
        return self._execute(cmd)

    def separate_audio_tracks(self, input_path: str, output_path: str,
                             voice_boost: float = 1.0, music_cut: float = 1.0) -> str:
        cmd = self.ffmpeg.build_voice_boost(input_path, output_path,
                                           voice_boost, music_cut)
        return self._execute(cmd)

    def apply_brightness(self, input_path: str, output_path: str, value: float) -> str:
        cmd = self.ffmpeg.build_filter(input_path, output_path, f"eq=brightness={value:.2f}")
        return self._execute(cmd)

    def apply_contrast(self, input_path: str, output_path: str, value: float) -> str:
        cmd = self.ffmpeg.build_filter(input_path, output_path, f"eq=contrast={value:.2f}")
        return self._execute(cmd)

    def apply_warm(self, input_path: str, output_path: str, intensity: float = 1.0) -> str:
        r_boost = intensity * 0.1
        b_cut = intensity * 0.1
        cmd = self.ffmpeg.build_filter(input_path, output_path,
                                      f"colorbalance=rs={r_boost:.2f}:bs=-{b_cut:.2f}")
        return self._execute(cmd)

    def apply_cool(self, input_path: str, output_path: str, intensity: float = 1.0) -> str:
        b_boost = intensity * 0.1
        r_cut = intensity * 0.1
        cmd = self.ffmpeg.build_filter(input_path, output_path,
                                      f"colorbalance=bs={b_boost:.2f}:rs=-{r_cut:.2f}")
        return self._execute(cmd)

    def apply_sharpness(self, input_path: str, output_path: str, value: float) -> str:
        amount = value * 0.5
        cmd = self.ffmpeg.build_filter(input_path, output_path,
                                      f"unsharp=5:5:{amount:.2f}:5:5:0.0")
        return self._execute(cmd)

    def enhance_quality(self, input_path: str, output_path: str,
                       denoise: bool = True, sharpen: bool = True) -> str:
        filters = []
        if denoise:
            filters.append("hqdn3d=4:3:6:4.5")
        if sharpen:
            filters.append("unsharp=5:5:0.5:5:5:0.0")

        filter_str = ",".join(filters) if filters else "null"
        cmd = self.ffmpeg.build_filter(input_path, output_path, filter_str)
        return self._execute(cmd)

    def render_video(self, input_path: str, output_path: str,
                    start_time: float = 0, end_time: float = None,
                    resolution: str = 'source',
                    fps: int = None,
                    codec: str = None,
                    speed: float = 1.0,
                    volume: float = 1.0,
                    is_muted: bool = False,
                    extra_vf: str = "") -> str:
        info = self.ffmpeg.get_video_info(input_path)

        if not resolution or resolution.lower() in ('source', 'auto', 'original'):
            width = info.get('width') or 1920
            height = info.get('height') or 1080
        else:
            width, height = self._parse_resolution(resolution)

        if not width or not height or width <= 0 or height <= 0:
            width = info.get('width') or 1920
            height = info.get('height') or 1080

        if fps is None:
            fps = info.get('fps', 30)

        if codec is None:
            codec = self.settings.get('encoder', 'libx264')

        cmd = self.ffmpeg.build_render(input_path, output_path,
                                      start_time, end_time,
                                      width, height, fps, codec,
                                      speed=speed, volume=volume, is_muted=is_muted,
                                      extra_vf=extra_vf)

        logger.info(f"Rendering: {input_path} -> {output_path} at {width}x{height} (speed={speed}, vol={volume}, muted={is_muted})")
        return self._execute(cmd)

    def _parse_resolution(self, res: str) -> Tuple[int, int]:
        s = str(res).lower().strip()
        # Accept explicit "WxH" (used by the export pipeline for exact geometry)
        if 'x' in s:
            try:
                w_str, h_str = s.split('x', 1)
                w, h = int(w_str), int(h_str)
                if w > 0 and h > 0:
                    return (w - (w % 2), h - (h % 2))
            except (ValueError, TypeError):
                pass
        resolutions = {
            '720p': (1280, 720),
            '1080p': (1920, 1080),
            '1440p': (2560, 1440),
            '2k': (2048, 1080),
            '4k': (3840, 2160),
            '8k': (7680, 4320),
            '9:16': (1080, 1920),
        }
        return resolutions.get(str(res).lower(), (1920, 1080))

    def generate_black_video(self, output_path: str, duration: float, resolution: str, codec: str, fps: float = 30.0) -> str:
        width, height = self._parse_resolution(resolution)
        fps = fps if fps and fps > 0 else 30.0
        codec = codec if codec not in ('copy', 'source') else 'libx264'
        cmd = [
            self.ffmpeg.ffmpeg_path,
            '-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps:.3f}',
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-t', str(duration),
            '-c:v', codec,
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-ar', '44100',
            '-y', output_path
        ]
        logger.info(f"Generating black gap video: {duration}s -> {output_path}")
        return self._execute(cmd)

    def concat_clips(self, text_file_path: str, output_path: str) -> str:
        cmd = self.ffmpeg.build_concat(text_file_path, output_path)
        return self._execute(cmd)

    def apply_filter(self, input_path: str, output_path: str, filter_str: str, resolution: str = "1080p") -> str:
        if not filter_str or not filter_str.strip():
            shutil.copyfile(input_path, output_path)
            return output_path
            
        cmd = self.ffmpeg.build_filter(input_path, output_path, filter_str)
        return self._execute(cmd)

    def remove_watermark(self, input_path: str, output_path: str,
                         x: int, y: int, width: int, height: int) -> str:
        info = self.ffmpeg.get_video_info(input_path)
        vw = info.get('width', 0)
        vh = info.get('height', 0)
        cmd = self.ffmpeg.build_delogo(input_path, output_path, x, y, width, height, vw, vh)
        return self._execute(cmd)

    def render_image_frame(self, input_path: str, output_path: str,
                           start_time: float = 0.0, filter_str: str = "",
                           resolution: str = 'source') -> str:
        if resolution == 'source':
            info = self.ffmpeg.get_video_info(input_path)
            width = info.get('width', 0)
            height = info.get('height', 0)
        else:
            width, height = self._parse_resolution(resolution)

        cmd = self.ffmpeg.build_image_render(input_path, output_path, start_time, filter_str, width, height)
        return self._execute(cmd)

    def _execute(self, cmd: List[str]) -> str:
        cb = getattr(self, 'progress_callback', None)
        cc = getattr(self, 'cancel_check', None)
        return self.ffmpeg.execute(cmd, cb, cc)

    def get_video_info(self, input_path: str) -> Dict:
        return self.ffmpeg.get_video_info(input_path)

    def cleanup(self):
        if hasattr(self, 'temp_dir') and self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                logger.info("Cleaned up temporary files")
            except Exception:
                pass

    def _sweep_stale_temp_dirs(self):
        """Remove vedit_* temp dirs left behind by crashed sessions (>1 day old)."""
        import time
        base = Path(tempfile.gettempdir())
        cutoff = time.time() - 86400
        try:
            for d in base.glob('vedit_*'):
                if str(d) == self.temp_dir:
                    continue
                try:
                    if d.is_dir() and d.stat().st_mtime < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    continue
        except Exception:
            pass
