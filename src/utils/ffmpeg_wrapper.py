import subprocess
import json
import os
import logging
from typing import List, Dict

class FFmpegWrapper:
    def __init__(self, settings: Dict = None):
        self.settings = settings or {}
        self.ffmpeg_path = self._find_ffmpeg()
        self.ffprobe_path = self._find_ffprobe()

    def _find_ffmpeg(self) -> str:
        from pathlib import Path
        import sys, subprocess, os
        if getattr(sys, 'frozen', False):
            base_path = Path(sys.executable).parent
        else:
            base_path = Path(__file__).parent.parent.parent
            
        ffmpeg_dir = base_path / "ffmpeg"
        if ffmpeg_dir.exists():
            for p in ffmpeg_dir.rglob("ffmpeg.exe"):
                if p.is_file():
                    return str(p)
            
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(['ffmpeg', '-version'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, creationflags=creationflags)
            return 'ffmpeg'
        except:
            raise RuntimeError("FFmpeg not found! Please install FFmpeg or extract it into the 'ffmpeg' directory.")

    def _find_ffprobe(self) -> str:
        from pathlib import Path
        import sys
        if getattr(sys, 'frozen', False):
            base_path = Path(sys.executable).parent
        else:
            base_path = Path(__file__).parent.parent.parent
            
        ffmpeg_dir = base_path / "ffmpeg"
        if ffmpeg_dir.exists():
            for p in ffmpeg_dir.rglob("ffprobe.exe"):
                if p.is_file():
                    return str(p)
            
        return 'ffprobe'

    @staticmethod
    def execute(cmd: List[str], progress_callback=None, cancel_check=None) -> str:
        logger = logging.getLogger(__name__)
        logger.debug(f"Executing: {' '.join(cmd)}")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            if os.name == 'nt' and hasattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS'):
                creationflags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags
            )
            
            error_output = []
            for line in process.stderr:
                error_output.append(line)
                if progress_callback:
                    progress_callback(line)
                if cancel_check and cancel_check():
                    process.terminate()
                    process.wait()
                    raise RuntimeError("Cancelled by user")
            
            process.wait()
            
            if process.returncode != 0:
                stderr = "".join(error_output)
                raise RuntimeError(f"FFmpeg command failed: {stderr}")
            if '-y' in cmd:
                idx = cmd.index('-y')
                if idx + 1 < len(cmd):
                    return cmd[idx + 1]
            return ''
        except Exception as e:
            logger.error(f"Execution error: {e}")
            raise

    def get_video_info(self, input_path: str) -> Dict:
        if not input_path or not os.path.exists(input_path):
            return {'error': 'File not found', 'width': 0, 'height': 0, 'fps': 0, 'duration': 0}

        ext = os.path.splitext(input_path)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.webp']:
            try:
                from PySide6.QtGui import QImage
                qimg = QImage(input_path)
                if not qimg.isNull() and qimg.width() > 0 and qimg.height() > 0:
                    return {
                        'width': qimg.width(),
                        'height': qimg.height(),
                        'fps': 30.0,
                        'duration': 5.0,
                        'codec': 'image',
                        'bitrate': 0,
                        'size_mb': os.path.getsize(input_path) / (1024 * 1024)
                    }
            except Exception:
                pass

        cmd = [
            self.ffprobe_path,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            input_path
        ]

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags
            )
        except Exception as e:
            logger.error(f"ffprobe subprocess error: {e}")
            return {'error': str(e), 'width': 1920, 'height': 1080, 'fps': 30.0, 'duration': 5.0}

        if not result or result.returncode != 0 or not result.stdout or not result.stdout.strip():
            return {'error': 'Probe failed', 'width': 1920, 'height': 1080, 'fps': 30.0, 'duration': 5.0}

        try:
            data = json.loads(result.stdout)
        except Exception:
            return {'error': 'JSON parse failed', 'width': 1920, 'height': 1080, 'fps': 30.0, 'duration': 5.0}

        info = {
            'width': 1920,
            'height': 1080,
            'fps': 30.0,
            'duration': 5.0,
            'codec': '',
            'bitrate': 0,
            'size_mb': 0
        }

        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                info['width'] = int(stream.get('width', 1920))
                info['height'] = int(stream.get('height', 1080))
                info['codec'] = stream.get('codec_name', '')

                if 'r_frame_rate' in stream:
                    fps_parts = stream['r_frame_rate'].split('/')
                    if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                        info['fps'] = int(fps_parts[0]) / int(fps_parts[1])

        format_info = data.get('format', {})
        dur = float(format_info.get('duration', 0))
        if dur > 0:
            info['duration'] = dur
        info['bitrate'] = int(format_info.get('bit_rate', 0))
        try:
            info['size_mb'] = os.path.getsize(input_path) / (1024 * 1024)
        except Exception:
            info['size_mb'] = 0

        return info

    def build_lossless_trim(self, input_path: str, output_path: str,
                           start: float, duration: float) -> List[str]:
        cmd = [
            self.ffmpeg_path,
            '-ss', str(start),
            '-i', input_path,
        ]
        if duration > 0:
            cmd.extend(['-t', str(duration)])
        cmd.extend(['-c', 'copy', '-avoid_negative_ts', '1', '-y', output_path])
        return cmd

    def build_trim(self, input_path: str, output_path: str,
                   start: float, duration: float) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')
        cmd = [self.ffmpeg_path, '-ss', str(start), '-i', input_path]

        if duration > 0:
            cmd.extend(['-t', str(duration)])

        if encoder == 'h264_nvenc':
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc:v', 'vbr', '-cq', '18', '-b:v', '0'])
        elif encoder == 'h264_amf':
            cmd.extend(['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '18'])
        elif encoder == 'h264_qsv':
            cmd.extend(['-c:v', 'h264_qsv', '-preset', 'veryfast', '-global_quality', '20'])
        elif encoder == 'h264_mf':
            cmd.extend(['-c:v', 'h264_mf', '-rate_control', 'vbr'])
        else:
            cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '0'])

        cmd.extend(['-c:a', 'copy', '-y', output_path])
        return cmd

    def build_filter(self, input_path: str, output_path: str,
                    filter_str: str) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')

        cmd = [self.ffmpeg_path, '-i', input_path, '-vf', filter_str]

        if encoder == 'h264_nvenc':
            cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc:v', 'vbr', '-cq', '18', '-b:v', '0'])
        elif encoder == 'h264_amf':
            cmd.extend(['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '18'])
        elif encoder == 'h264_qsv':
            cmd.extend(['-c:v', 'h264_qsv', '-preset', 'veryfast', '-global_quality', '20'])
        elif encoder == 'h264_mf':
            cmd.extend(['-c:v', 'h264_mf', '-rate_control', 'vbr'])
        else:
            cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '0'])

        cmd.extend(['-c:a', 'copy', '-y', output_path])
        return cmd

    def build_resize(self, input_path: str, output_path: str,
                    width: int, height: int) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')

        filter_str = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-vf', filter_str
        ]

        if encoder != 'libx264':
            cmd.extend(['-c:v', encoder])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '18'])

        cmd.extend(['-c:a', 'copy', '-y', output_path])
        return cmd

    def build_aspect_convert(self, input_path: str, output_path: str,
                            width: int, height: int) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')

        filter_str = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-vf', filter_str
        ]

        if encoder != 'libx264':
            cmd.extend(['-c:v', encoder])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '18'])

        cmd.extend(['-c:a', 'copy', '-y', output_path])
        return cmd

    def build_reverse(self, input_path: str, output_path: str) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')

        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-vf', 'reverse',
            '-af', 'areverse'
        ]

        if encoder != 'libx264':
            cmd.extend(['-c:v', encoder])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '18'])

        cmd.extend(['-c:a', 'aac', '-y', output_path])
        return cmd

    def build_speed_change(self, input_path: str, output_path: str,
                          speed: float) -> List[str]:
        if speed <= 0:
            raise ValueError(f"Speed must be positive, got {speed}")

        encoder = self.settings.get('encoder', 'libx264')
        video_speed = 1.0 / speed

        atempo_filters = []
        remaining = speed
        while remaining > 2.0:
            atempo_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_filters.append("atempo=0.5")
            remaining /= 0.5
        atempo_filters.append(f"atempo={remaining:.2f}")

        audio_filter = ",".join(atempo_filters)

        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-filter_complex',
            f"[0:v]setpts={video_speed:.2f}*PTS[v];[0:a]{audio_filter}[a]",
            '-map', '[v]',
            '-map', '[a]'
        ]

        if encoder != 'libx264':
            cmd.extend(['-c:v', encoder])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '18'])

        cmd.extend(['-c:a', 'aac', '-y', output_path])
        return cmd

    def build_extract_audio(self, input_path: str, output_path: str) -> List[str]:
        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-vn',
            '-acodec', 'mp3',
            '-ab', '192k',
            '-y', output_path
        ]

    def build_mute(self, input_path: str, output_path: str) -> List[str]:
        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-c', 'copy',
            '-an',
            '-y', output_path
        ]

    def build_volume(self, input_path: str, output_path: str,
                    gain: float) -> List[str]:
        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', f"volume={gain:.2f}",
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_volume_segment(self, input_path: str, output_path: str,
                            gain: float, start: float, end: float) -> List[str]:
        filter_str = f"volume={gain:.2f}:enable='between(t,{start},{end})'"

        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', filter_str,
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_complex_volume(self, input_path: str, output_path: str,
                            segments: List[Dict]) -> List[str]:
        filters = []
        for seg in segments:
            filters.append(f"volume={seg['volume']:.2f}:enable='between(t,{seg['start']},{seg['end']})'")

        filter_str = ",".join(filters)

        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', filter_str,
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_voice_boost(self, input_path: str, output_path: str,
                         voice_gain: float, music_gain: float) -> List[str]:
        filters = [
            f"equalizer=f=300:width_type=h:width=400:gain={voice_gain:.2f}",
            f"equalizer=f=1000:width_type=h:width=800:gain={voice_gain*0.7:.2f}",
            f"equalizer=f=3000:width_type=h:width=2000:gain={voice_gain*0.5:.2f}",
        ]
        if music_gain < 1.0:
            filters.append(f"volume={music_gain:.2f}")
        filter_str = ",".join(filters)

        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', filter_str,
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_fade(self, input_path: str, output_path: str,
                  fade_in: float, fade_out: float) -> List[str]:
        filter_parts = []

        if fade_in > 0:
            filter_parts.append(f"afade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            duration = self.get_video_info(input_path).get('duration', 0)
            start = max(0, duration - fade_out)
            filter_parts.append(f"afade=t=out:st={start}:d={fade_out}")

        filter_str = ",".join(filter_parts) if filter_parts else "null"

        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', filter_str,
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_normalize(self, input_path: str, output_path: str,
                       target_lufs: float) -> List[str]:
        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', f"loudnorm=I={target_lufs}:LRA=11:TP=-1.5",
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_audio_mix(self, video_path: str, audio_path: str,
                         output_path: str, volume: float = 1.0) -> List[str]:
        has_audio = False
        cmd_probe = [
            self.ffprobe_path,
            '-v', 'quiet',
            '-select_streams', 'a',
            '-show_entries', 'stream=codec_type',
            '-of', 'csv=p=0',
            video_path
        ]
        try:
            res = subprocess.run(cmd_probe, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if res.stdout and 'audio' in res.stdout.lower():
                has_audio = True
        except Exception:
            has_audio = False

        if has_audio:
            filter_str = f"[1:a]volume={volume:.2f}[a];[0:a][a]amix=inputs=2:duration=first:dropout_transition=2[outa]"
            return [
                self.ffmpeg_path,
                '-i', video_path,
                '-i', audio_path,
                '-filter_complex', filter_str,
                '-map', '0:v',
                '-map', '[outa]',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-y', output_path
            ]
        else:
            filter_str = f"volume={volume:.2f}"
            return [
                self.ffmpeg_path,
                '-i', video_path,
                '-i', audio_path,
                '-filter_complex', f"[1:a]{filter_str}[outa]",
                '-map', '0:v',
                '-map', '[outa]',
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-y', output_path
            ]

    def build_lut(self, input_path: str, output_path: str,
                 lut_path: str, intensity: float) -> List[str]:
        encoder = self.settings.get('encoder', 'libx264')

        filter_str = f"lut3d=file={lut_path}:interp=trilinear:scale={intensity:.2f}"

        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-vf', filter_str
        ]

        if encoder != 'libx264':
            cmd.extend(['-c:v', encoder])
        else:
            cmd.extend(['-c:v', 'libx264', '-crf', '18'])

        cmd.extend(['-c:a', 'copy', '-y', output_path])
        return cmd

    def build_delogo(self, input_path: str, output_path: str,
                     x: int, y: int, width: int, height: int,
                     video_width: int = 0, video_height: int = 0) -> List[str]:
        if video_width > 0 and video_height > 0:
            x = max(0, min(x, video_width - 2))
            y = max(0, min(y, video_height - 2))
            width = max(2, min(width, video_width - x))
            height = max(2, min(height, video_height - y))
        else:
            x = max(0, x)
            y = max(0, y)
            width = max(2, width)
            height = max(2, height)

        filter_str = f"delogo=x={x}:y={y}:w={width}:h={height}"
        return self.build_filter(input_path, output_path, filter_str)

    def build_image_render(self, input_path: str, output_path: str,
                           start_time: float = 0.0, filter_str: str = "",
                           width: int = 0, height: int = 0) -> List[str]:
        is_image = input_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))
        cmd = [self.ffmpeg_path]

        if not is_image and start_time > 0:
            cmd.extend(['-ss', str(start_time)])

        cmd.extend(['-i', input_path])

        filters = []
        if filter_str:
            filters.append(filter_str)

        if width > 0 and height > 0:
            filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")

        if filters:
            cmd.extend(['-vf', ",".join(filters)])

        cmd.extend(['-vframes', '1', '-y', output_path])
        return cmd

    def build_render(self, input_path: str, output_path: str,
                    start: float, end: float,
                    width: int, height: int,
                    fps: int, codec: str, speed: float = 1.0,
                    volume: float = 1.0, is_muted: bool = False) -> List[str]:
                    
        is_image = input_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))
        
        cmd = [self.ffmpeg_path]
        
        if is_image:
            cmd.extend(['-loop', '1'])
            
        cmd.extend(['-i', input_path])

        if is_image:
            cmd.extend(['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100'])
            duration = end - start if end is not None else 5.0
            cmd.extend(['-t', str(duration)])
        else:
            if start > 0:
                cmd.extend(['-ss', str(start)])
            if end is not None:
                cmd.extend(['-to', str(end)])

        if (codec == 'copy' or codec == 'source') and (is_image or start > 0 or (end is not None and end > 0) or width > 0 or height > 0 or speed != 1.0 or volume != 1.0 or is_muted):
            codec = 'libx264'

        filters = []
        if (codec != 'copy' and codec != 'source') and width > 0 and height > 0:
            filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")

        if speed != 1.0 and speed > 0:
            pts_mult = 1.0 / speed
            filters.append(f"setpts={pts_mult:.4f}*PTS")

        if filters:
            cmd.extend(['-vf', ",".join(filters)])

        if is_muted or volume <= 0.0:
            cmd.extend(['-an'])
        else:
            if speed != 1.0 and speed > 0 and not is_image:
                if volume != 1.0:
                    cmd.extend(['-af', f"atempo={speed:.2f},volume={volume:.2f}"])
                else:
                    cmd.extend(['-af', f"atempo={speed:.2f}"])
            else:
                if volume != 1.0:
                    cmd.extend(['-af', f"volume={volume:.2f}"])

        threads = str(self.settings.get('threads', 4))
        cmd.extend(['-threads', threads])

        if codec == 'copy' or codec == 'source':
            cmd.extend(['-c:v', 'copy'])
        else:
            if codec == 'h264_nvenc':
                cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p6', '-cq', '14'])
            elif codec == 'h264_qsv':
                cmd.extend(['-c:v', 'h264_qsv', '-preset', 'medium', '-global_quality', '20'])
            elif codec == 'h264_amf':
                cmd.extend(['-c:v', 'h264_amf', '-quality', 'quality'])
            elif codec == 'h264_mf':
                cmd.extend(['-c:v', 'h264_mf', '-rate_control', 'vbr'])
            else:
                cmd.extend(['-c:v', 'libx264', '-preset', 'slow', '-crf', '18'])
            cmd.extend(['-pix_fmt', 'yuv420p'])

        if is_image:
            cmd.extend(['-c:a', 'aac', '-b:a', '192k', '-map', '0:v', '-map', '1:a', '-shortest'])
        else:
            if codec == 'copy':
                cmd.extend(['-c:a', 'copy'])
            else:
                cmd.extend(['-c:a', 'aac', '-b:a', '192k'])

        if fps > 0 and codec != 'copy':
            cmd.extend(['-r', str(fps)])

        if output_path.lower().endswith(('.mp4', '.mov')):
            cmd.extend(['-movflags', '+faststart'])

        cmd.extend(['-y', output_path])
        return cmd

    def build_vocal_extract(self, input_path: str, output_path: str) -> List[str]:
        filter_str = "pan=mono|c0=0.5*c0+0.5*c1,bandpass=f=1000:width_type=h:width=2000"

        return [
            self.ffmpeg_path,
            '-i', input_path,
            '-af', filter_str,
            '-c:v', 'copy',
            '-y', output_path
        ]

    def build_concat(self, text_file_path: str, output_path: str) -> List[str]:
        return [
            self.ffmpeg_path,
            '-f', 'concat',
            '-safe', '0',
            '-i', text_file_path,
            '-c', 'copy',
            '-y', output_path
        ]

    def build_drawtext(self, input_path: str, output_path: str,
                       text: str, fontsize: int = 36, fontcolor: str = "white",
                       y_pos: str = "h-text_h-50") -> List[str]:
        safe_text = text.replace(":", "\\:").replace("'", "'\\''")
        ff_arg = ""
        for fp in ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf"]:
            if os.path.exists(fp):
                safe_fp = fp.replace("\\", "/").replace(":", "\\:")
                ff_arg = f"fontfile='{safe_fp}':"
                break
        filter_str = f"drawtext={ff_arg}text='{safe_text}':fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.5:boxborderw=5"
        return self.build_filter(input_path, output_path, filter_str)
