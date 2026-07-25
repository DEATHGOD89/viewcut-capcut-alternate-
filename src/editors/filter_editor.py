import os
from typing import Dict, List

from utils.ffmpeg_wrapper import FFmpegWrapper
from core.hardware import HardwareInfo
from utils.logger import get_logger

logger = get_logger(__name__)

class FilterEditor:
    def __init__(self, settings: Dict = None):
        if settings is None:
            hw = HardwareInfo()
            settings = hw.get_optimal_settings()
        self.ffmpeg = FFmpegWrapper(settings)

    def get_filter_string(self, filter_type: str, intensity: float) -> str:
        key = filter_type.lower().replace(' ', '_')

        filters = {
            # 1. Basic Adjustments
            'brightness': f"eq=brightness={(intensity - 1.0) * 0.5:.2f}",
            'contrast': f"eq=contrast={intensity:.2f}",
            'saturation': f"eq=saturation={intensity:.2f}",
            'exposure': f"eq=exposure={(intensity - 1.0) * 1.5:.2f}",
            'gamma': f"eq=gamma={intensity:.2f}",
            'highlights': f"colorbalance=rh={(intensity - 1.0) * 0.3:.2f}:gh={(intensity - 1.0) * 0.3:.2f}:bh={(intensity - 1.0) * 0.3:.2f}",
            'shadows': f"colorbalance=rs={(intensity - 1.0) * 0.3:.2f}:gs={(intensity - 1.0) * 0.3:.2f}:bs={(intensity - 1.0) * 0.3:.2f}",
            'whites': f"eq=brightness={(intensity - 1.0) * 0.3:.2f}:contrast={intensity:.2f}",
            'blacks': f"eq=brightness=-{(intensity - 1.0) * 0.3:.2f}:contrast={intensity:.2f}",
            
            # 2. Color Correction & Balance
            'temperature': f"colorbalance=rs={(intensity - 1.0) * 0.2:.2f}:bs=-{(intensity - 1.0) * 0.2:.2f}",
            'tint': f"colorbalance=gs={(intensity - 1.0) * 0.2:.2f}:rs=-{(intensity - 1.0) * 0.2:.2f}",
            'vibrance': f"eq=saturation={1.0 + (intensity - 1.0) * 1.3:.2f}",
            'hue': f"hue=h={(intensity - 1.0) * 90:.1f}",
            'white_balance': f"colorbalance=rs={(intensity - 1.0) * 0.15:.2f}:bs=-{(intensity - 1.0) * 0.15:.2f}",
            'warm': f"colorbalance=rs={intensity * 0.1:.2f}:bs=-{intensity * 0.1:.2f}",
            'cool': f"colorbalance=bs={intensity * 0.1:.2f}:rs=-{intensity * 0.1:.2f}",

            # 3. Professional Color Grading & Presets
            'teal_orange': f"colorbalance=rs={0.15*intensity:.2f}:gs={0.02*intensity:.2f}:bs=-{0.12*intensity:.2f}:rh=-{0.1*intensity:.2f}:gh={0.05*intensity:.2f}:bh={0.2*intensity:.2f},eq=contrast={1.18*intensity:.2f}:saturation={1.25*intensity:.2f}",
            'vivid': f"eq=contrast={1.15*intensity:.2f}:brightness=0.03:saturation={1.4*intensity:.2f}:gamma=1.05",
            'warm_glow': f"colorbalance=rs={0.12*intensity:.2f}:gs={0.05*intensity:.2f}:bs=-{0.1*intensity:.2f},eq=contrast={1.1*intensity:.2f}:saturation={1.15*intensity:.2f}",
            'cyberpunk': f"colorbalance=rs=-{0.1*intensity:.2f}:gs={0.05*intensity:.2f}:bs={0.2*intensity:.2f}:rh={0.15*intensity:.2f}:gh=-{0.05*intensity:.2f}:bh={0.1*intensity:.2f},eq=contrast={1.25*intensity:.2f}:saturation={1.35*intensity:.2f}",
            'soft_skin': f"colorbalance=rs={0.06*intensity:.2f}:gs={0.02*intensity:.2f}:bs=-{0.04*intensity:.2f},unsharp=5:5:{0.6*intensity:.2f}:5:5:0.0",
            'film_noir': f"hue=s=0,eq=contrast={1.3*intensity:.2f}:brightness=-0.05",
            'cinematic': self._cinematic_filter(intensity),
            'vintage': self._vintage_filter(intensity),
            'black_white': self._black_white_filter(intensity),

            # 4. AI Enhancement & Reconstruction
            'ai_enhance': self.get_auto_enhance_filter_string(intensity, intensity, intensity),
            'ai_denoise': f"hqdn3d={3.0*intensity:.1f}:{2.5*intensity:.1f}:{4.0*intensity:.1f}:{3.5*intensity:.1f}",
            'ai_deblur': f"unsharp=7:7:{1.2*intensity:.2f}:7:7:0.0",
            'ai_skin_smooth': f"colorbalance=rs={0.05*intensity:.2f}:gs={0.01*intensity:.2f}:bs=-{0.03*intensity:.2f},unsharp=5:5:{0.5*intensity:.2f}:5:5:0.0",
            'ai_dehaze': f"eq=contrast={1.2*intensity:.2f}:brightness=-{0.05*intensity:.2f}:saturation={1.15*intensity:.2f}",

            # 5. Detail & Sharpness Controls
            'sharpness': f"unsharp=5:5:{intensity * 0.5:.2f}:5:5:0.0",
            'edge_sharpen': f"unsharp=7:7:{intensity * 1.2:.2f}:7:7:0.0",
            'clarity': f"eq=contrast={1.0 + intensity * 0.2:.2f},unsharp=5:5:{intensity * 0.6:.2f}:5:5:0.0",
            'texture': f"unsharp=3:3:{intensity * 0.8:.2f}:3:3:0.0",

            # 6. Blur & Optics Controls
            'gaussian_blur': f"gblur=sigma={intensity * 5.0:.1f}",
            'box_blur': f"boxblur=luma_radius={max(1, int(intensity * 10))}:luma_power=2",
            'bokeh': f"gblur=sigma={intensity * 8.0:.1f}",

            # 7. Lighting, Lens & Grain Effects
            'vignette': f"vignette=angle=PI/{(max(0.1, intensity) * 4):.2f}",
            'film_grain': f"noise=alls={int(intensity * 20)}:allf=t+u",
            'bloom': f"eq=brightness={0.05*intensity:.2f}:contrast={1.1*intensity:.2f},colorbalance=rs={0.05*intensity:.2f}:gs={0.05*intensity:.2f}:bs={0.08*intensity:.2f}",
            'glow': f"eq=brightness={0.03*intensity:.2f}:saturation={1.2*intensity:.2f}",

            # 8. High-End Commercial AMV & CapCut Effects (Inspected from Telegram Desktop Samples)
            'super_anime_hdr_glow': f"unsharp=7:7:{2.2*intensity:.2f}:7:7:0.0,eq=contrast={1.35*intensity:.2f}:saturation={1.5*intensity:.2f}:gamma=1.1,colorbalance=rs={0.08*intensity:.2f}:gs={0.15*intensity:.2f}:bs={0.08*intensity:.2f}",
            'spiderverse_anime': f"unsharp=9:9:{2.5*intensity:.2f}:9:9:0.0,colorbalance=rs={0.2*intensity:.2f}:gs={0.08*intensity:.2f}:bs=-{0.1*intensity:.2f}:rh={0.15*intensity:.2f}:gh={0.05*intensity:.2f}:bh=-{0.05*intensity:.2f},eq=contrast={1.28*intensity:.2f}:saturation={1.45*intensity:.2f}",
            'pop_art_comic': f"unsharp=11:11:{3.0*intensity:.2f}:11:11:0.0,eq=contrast={1.4*intensity:.2f}:saturation={1.8*intensity:.2f}:brightness=0.03",
            'cyberpunk_neon_hologram': f"colorbalance=rs={0.25*intensity:.2f}:gs=-{0.1*intensity:.2f}:bs={0.3*intensity:.2f}:rh=-{0.1*intensity:.2f}:gh={0.1*intensity:.2f}:bh={0.25*intensity:.2f},eq=contrast={1.3*intensity:.2f}:saturation={1.6*intensity:.2f}:brightness=0.04",
            'anime': f"hqdn3d=1.5:1.5:3.0:3.0,eq=contrast={1.15*intensity:.2f}:saturation={1.25*intensity:.2f},unsharp=7:7:{1.2*intensity:.2f}:7:7:0.0",
            'cartoon': f"hqdn3d=2.0:2.0:4.0:4.0,eq=contrast={1.2*intensity:.2f}:saturation={1.3*intensity:.2f},unsharp=9:9:{1.5*intensity:.2f}:9:9:0.0"
        }

        return filters.get(key, "")

    def apply_filter(self, input_path: str, output_path: str,
                    filter_type: str, intensity: float = 1.0) -> str:
        filter_str = self.get_filter_string(filter_type, intensity)
        if not filter_str:
            raise ValueError(f"Unsupported filter: {filter_type}")

        cmd = self.ffmpeg.build_filter(input_path, output_path, filter_str)
        return self._execute(cmd)
        
    def apply_filters(self, input_path: str, output_path: str, filter_list: List) -> str:
        filter_strs = []
        for item in filter_list:
            if isinstance(item, tuple) and len(item) == 2:
                f_type, intensity = item
                fs = self.get_filter_string(f_type, intensity)
                if fs:
                    filter_strs.append(fs)
            elif isinstance(item, str) and item.strip():
                filter_strs.append(item.strip())
                
        if not filter_strs:
            import shutil
            shutil.copy2(input_path, output_path)
            return output_path
            
        combined_filter = ",".join(filter_strs)
        cmd = self.ffmpeg.build_filter(input_path, output_path, combined_filter)
        return self._execute(cmd)

    def _vintage_filter(self, intensity: float) -> str:
        return f"colorbalance=rs={intensity*0.05:.2f}:bs={intensity*0.08:.2f},eq=saturation={0.7*intensity:.2f}"

    def _cinematic_filter(self, intensity: float) -> str:
        return f"colorbalance=bs={intensity*0.1:.2f}:rs=-{intensity*0.05:.2f},eq=contrast={1.2*intensity:.2f}"

    def _black_white_filter(self, intensity: float) -> str:
        sat = max(0.0, 1.0 - intensity)
        return f"hue=s={sat:.2f}"

    def get_auto_enhance_filter_string(self, denoise: float = 0.5, sharpen: float = 0.5, color: float = 0.5, upscale_res: str = "auto", mode: str = "real_life") -> str:
        filters = []
        res_key = str(upscale_res).lower().strip()
        res_map = {
            '720p': (1280, 720),
            '1080p': (1920, 1080),
            '1440p': (2560, 1440),
            '2k': (2560, 1440),
            '2160p': (3840, 2160),
            '4k': (3840, 2160),
            '8k': (7680, 4320)
        }

        target_dim = None
        for k, v in res_map.items():
            if k in res_key:
                target_dim = v
                break

        # 1. High-Speed Denoise & Skin Smooth FIRST (at source resolution before upscaling)
        if "heavy" in str(mode).lower() or "studio" in str(mode).lower():
            dn_luma = 3.2 + denoise * 2.0
            dn_chroma = 2.8 + denoise * 1.8
            filters.append(f"hqdn3d={dn_luma:.1f}:{dn_chroma:.1f}:{dn_luma*1.2:.1f}:{dn_chroma*1.2:.1f}")
        elif "anime" in str(mode).lower() or "cartoon" in str(mode).lower():
            filters.append("hqdn3d=2.2:2.2:3.5:3.5")
        else:
            dn_luma = 2.2 + denoise * 1.8
            dn_chroma = 2.0 + denoise * 1.5
            filters.append(f"hqdn3d={dn_luma:.1f}:{dn_chroma:.1f}:{dn_luma*1.2:.1f}:{dn_chroma*1.2:.1f}")

        # 2. Super-Resolution High-Precision Upscaling SECOND
        if target_dim:
            tw, th = target_dim
            filters.append(f"scale={tw}:{th}:flags=lanczos+accurate_rnd+full_chroma_int+full_chroma_inp:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2")

        # 3. Crisp Edge Sharpening & Dynamic Tone Balancing THIRD (at target resolution)
        if "heavy" in str(mode).lower() or "studio" in str(mode).lower():
            c_val = 1.12 + color * 0.10
            b_val = 0.01 + color * 0.01
            s_val = 1.20 + color * 0.12
            g_val = 1.03 + color * 0.02
            filters.append(f"eq=contrast={c_val:.2f}:brightness={b_val:.2f}:saturation={s_val:.2f}:gamma={g_val:.2f}")
            filters.append(f"colorbalance=rs={color*0.04:.2f}:gs={color*0.02:.2f}:bs=-{color*0.03:.2f}")
            sh_macro = 0.45 + sharpen * 0.35
            filters.append(f"unsharp=5:5:{sh_macro:.2f}:5:5:0.0")
        elif "anime" in str(mode).lower() or "cartoon" in str(mode).lower():
            filters.append(f"eq=contrast={1.10+color*0.05:.2f}:brightness=0.01:saturation={1.20+color*0.10:.2f}:gamma=1.02")
            sh_anime = 0.35 + sharpen * 0.35
            filters.append(f"unsharp=5:5:{sh_anime:.2f}:5:5:0.0")
        else:
            c_val = 1.05 + color * 0.08
            b_val = 0.01 + color * 0.01
            s_val = 1.08 + color * 0.10
            g_val = 1.01 + color * 0.02
            filters.append(f"eq=contrast={c_val:.2f}:brightness={b_val:.2f}:saturation={s_val:.2f}:gamma={g_val:.2f}")
            filters.append(f"colorbalance=rs={color*0.03:.2f}:gs={color*0.01:.2f}:bs=-{color*0.02:.2f}")
            sh_cinema = 0.35 + sharpen * 0.35
            filters.append(f"unsharp=5:5:{sh_cinema:.2f}:5:5:0.0")

        return ",".join(filters)

    def _sanitize_drawtext_text(self, text: str) -> str:
        if not text:
            return ""
        clean = "".join(c for c in text if (ord(c) < 1000 and (c.isalnum() or c in " .,!?-+()[]:;/_\"\n")))
        clean = clean.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
        return clean.strip()

    def _get_font_file_arg(self) -> str:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/segoeui.ttf"
        ]
        for font_p in candidates:
            if os.path.exists(font_p):
                safe_p = font_p.replace("\\", "/").replace(":", "\\:")
                return f"fontfile='{safe_p}':"
        return ""

    def get_drawtext_filter_string(self, text: str, fontsize: int = 36, fontcolor: str = "white", y_pos: str = "h-text_h-50") -> str:
        clean_text = self._sanitize_drawtext_text(text)
        if not clean_text:
            return ""
        ff_arg = self._get_font_file_arg()
        return f"drawtext={ff_arg}text='{clean_text}':fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.5:boxborderw=5"

    def get_subtitle_filter_string(self, srt_path: str) -> str:
        if not srt_path or not srt_path.strip():
            return ""
        safe_path = srt_path.replace("\\", "/").replace(":", "\\:")
        return f"subtitles='{safe_path}'"

    def get_styled_drawtext_filter_string(self, text: str, style_name: str = "Minimalist", fontsize: int = 36, y_pos: str = "h-text_h-50") -> str:
        clean_text = self._sanitize_drawtext_text(text)
        if not clean_text:
            return ""
        ff_arg = self._get_font_file_arg()
        style = style_name.lower().strip()
        if "horror" in style:
            return f"drawtext={ff_arg}text='{clean_text}':fontsize={fontsize}:fontcolor=red:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.9:boxborderw=8"
        elif "cool" in style or "neon" in style:
            return f"drawtext={ff_arg}text='{clean_text}':fontsize={fontsize}:fontcolor=yellow:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=0x0d1b2a@0.8:boxborderw=6"
        elif "minimalist" in style:
            return f"drawtext={ff_arg}text='{clean_text}':fontsize={fontsize}:fontcolor=white:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.4:boxborderw=4"
        else:
            return f"drawtext={ff_arg}text='{clean_text}':fontsize={fontsize}:fontcolor=white:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.7:boxborderw=5"

    def get_delogo_filter_string(self, x: int, y: int, width: int, height: int,
                                 video_width: int = 0, video_height: int = 0) -> str:
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

        return f"delogo=x={x}:y={y}:w={width}:h={height}"

    def apply_lut(self, input_path: str, output_path: str,
                 lut_path: str, intensity: float = 1.0) -> str:
        cmd = self.ffmpeg.build_lut(input_path, output_path, lut_path, intensity)
        return self._execute(cmd)

    def color_grade(self, input_path: str, output_path: str,
                   shadows: float = 0, midtones: float = 0,
                   highlights: float = 0) -> str:
        filter_str = f"colorbalance=rs={shadows*0.1:.2f}:bs={highlights*0.1:.2f}"
        cmd = self.ffmpeg.build_filter(input_path, output_path, filter_str)
        return self._execute(cmd)

    def _execute(self, cmd: List[str]) -> str:
        cb = getattr(self, 'progress_callback', None)
        cc = getattr(self, 'cancel_check', None)
        return self.ffmpeg.execute(cmd, cb, cc)
