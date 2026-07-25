from dataclasses import dataclass, field
from typing import List
from utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class EffectStack:
    brightness: float = 0.0      # -100.0 to 100.0
    contrast: float = 0.0        # -100.0 to 100.0
    saturation: float = 0.0      # -100.0 to 100.0
    temperature: float = 0.0     # -100.0 to 100.0
    exposure: float = 0.0        # -100.0 to 100.0
    gamma: float = 1.0           # 0.1 to 3.0
    denoise: float = 0.0         # 0.0 to 100.0
    sharpness: float = 0.0       # 0.0 to 100.0
    preset_filters: List[str] = field(default_factory=list)

    def set_parameter(self, param: str, value: float):
        if hasattr(self, param):
            setattr(self, param, float(value))
            logger.info(f"[EFFECT STACK] Param updated: {param} = {value:.2f}")

    def to_ffmpeg_vf(self) -> str:
        """Generates the unified FFmpeg video filtergraph string for both Preview and Export."""
        filters = []

        # 1. Custom/Preset Filters first
        for pf in self.preset_filters:
            if pf and pf.strip():
                filters.append(pf.strip())

        # 2. EQ Filter (Brightness, Contrast, Saturation, Exposure, Gamma)
        # Normalized parameters to prevent duplicate brightness application or white-level shift
        c_factor = max(0.1, 1.0 + (self.contrast / 100.0))
        b_offset = (self.brightness / 200.0) + (self.exposure / 100.0)
        s_factor = max(0.0, 1.0 + (self.saturation / 100.0))
        g_factor = max(0.1, self.gamma)

        if b_offset != 0.0 or c_factor != 1.0 or s_factor != 1.0 or g_factor != 1.0:
            filters.append(f"eq=brightness={b_offset:.3f}:contrast={c_factor:.3f}:saturation={s_factor:.3f}:gamma={g_factor:.3f}")

        # 3. Temperature / Colorbalance
        if self.temperature != 0.0:
            t_val = self.temperature / 200.0
            filters.append(f"colorbalance=rs={t_val:.3f}:bs={-t_val:.3f}")

        # 4. Denoise (hqdn3d)
        if self.denoise > 0.0:
            luma = 1.5 + (self.denoise / 100.0) * 8.0
            chroma = 1.2 + (self.denoise / 100.0) * 6.0
            filters.append(f"hqdn3d={luma:.1f}:{chroma:.1f}:{luma*1.2:.1f}:{chroma*1.2:.1f}")

        # 5. Sharpness (unsharp)
        if self.sharpness > 0.0:
            sh_val = self.sharpness / 50.0
            filters.append(f"unsharp=5:5:{sh_val:.2f}:5:5:0.0")

        vf_str = ",".join(filters) if filters else ""
        logger.info(f"[EFFECT STACK] Generated Unified VF: '{vf_str}'")
        return vf_str
