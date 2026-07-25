import subprocess
import psutil
import json
import os
from typing import Dict, Optional

class HardwareInfo:
    def __init__(self):
        self.cpu_cores = psutil.cpu_count(logical=True) or 4
        self.ram_gb = psutil.virtual_memory().total / (1024**3)
        self.gpu_info = self._detect_gpu()
        self.is_low_end = self._check_if_low_end()

    def _detect_gpu(self) -> Dict:
        gpu = {
            'type': 'cpu',
            'name': 'CPU Only',
            'memory_mb': 0,
            'available': False,
            'encoder': 'libx264'
        }
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        # 1. NVIDIA SMI Check (Highest Priority for Dedicated GPUs)
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=2, creationflags=creationflags
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('\n')[0].split(',')
                gpu.update({
                    'type': 'nvidia',
                    'name': parts[0].strip(),
                    'memory_mb': int(parts[1].strip().split()[0]),
                    'available': True,
                    'encoder': 'h264_nvenc'
                })
                return gpu
        except Exception:
            pass

        # 2. Query Windows PowerShell Get-CimInstance for GPUs
        try:
            p = subprocess.run(
                ['powershell', '-Command', 'Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json'],
                capture_output=True, text=True, timeout=3, creationflags=creationflags
            )
            if p.returncode == 0 and p.stdout.strip():
                data = json.loads(p.stdout)
                if isinstance(data, dict):
                    data = [data]
                
                # Check for NVIDIA dedicated GPU first
                for item in data:
                    g_name = item.get('Name', '')
                    g_ram = item.get('AdapterRAM', 0) or 0
                    vram_mb = int(g_ram / (1024 * 1024)) if g_ram else 4096
                    if 'NVIDIA' in g_name.upper():
                        gpu.update({'type': 'nvidia', 'name': g_name, 'memory_mb': vram_mb, 'available': True, 'encoder': 'h264_nvenc'})
                        return gpu

                # Check for AMD dedicated GPU second
                for item in data:
                    g_name = item.get('Name', '')
                    g_ram = item.get('AdapterRAM', 0) or 0
                    vram_mb = int(g_ram / (1024 * 1024)) if g_ram else 4096
                    if 'AMD' in g_name.upper() or 'RADEON' in g_name.upper():
                        gpu.update({'type': 'amd', 'name': g_name, 'memory_mb': vram_mb, 'available': True, 'encoder': 'h264_amf'})
                        return gpu

                # Check for Intel iGPU third
                for item in data:
                    g_name = item.get('Name', '')
                    g_ram = item.get('AdapterRAM', 0) or 0
                    vram_mb = int(g_ram / (1024 * 1024)) if g_ram else 2048
                    if 'INTEL' in g_name.upper():
                        gpu.update({'type': 'intel', 'name': g_name, 'memory_mb': vram_mb, 'available': True, 'encoder': 'h264_qsv'})
                        return gpu
        except Exception:
            pass

        # 3. Check FFmpeg Hardware Acceleration Encoders (NVENC -> AMF -> QSV -> MF)
        try:
            from pathlib import Path
            ffmpeg_dir = Path(__file__).parent.parent.parent / "ffmpeg"
            ffmpeg_exe = "ffmpeg"
            if ffmpeg_dir.exists():
                for f in ffmpeg_dir.rglob("ffmpeg.exe"):
                    ffmpeg_exe = str(f)
                    break

            res = subprocess.run([ffmpeg_exe, '-encoders'], capture_output=True, text=True, timeout=2, creationflags=creationflags)
            stdout = res.stdout if res.returncode == 0 else ""

            if 'h264_nvenc' in stdout:
                gpu.update({'type': 'nvidia', 'name': 'NVIDIA NVENC Hardware Acceleration', 'memory_mb': 4096, 'available': True, 'encoder': 'h264_nvenc'})
            elif 'h264_amf' in stdout:
                gpu.update({'type': 'amd', 'name': 'AMD Radeon AMF Hardware Acceleration', 'memory_mb': 4096, 'available': True, 'encoder': 'h264_amf'})
            elif 'h264_qsv' in stdout:
                gpu.update({'type': 'intel', 'name': 'Intel QuickSync iGPU Acceleration', 'memory_mb': 2048, 'available': True, 'encoder': 'h264_qsv'})
            elif 'h264_mf' in stdout:
                gpu.update({'type': 'windows_mf', 'name': 'Windows MediaFoundation Acceleration', 'memory_mb': 2048, 'available': True, 'encoder': 'h264_mf'})
        except Exception:
            pass

        return gpu

    def _check_if_low_end(self) -> bool:
        return (self.cpu_cores < 2 or self.ram_gb < 4)

    def get_optimal_settings(self) -> Dict:
        encoder = self.gpu_info.get('encoder', 'libx264')
        use_gpu = self.gpu_info.get('available', False)

        return {
            'threads': self.cpu_cores,
            'preview_scale': 0.5,
            'use_gpu': use_gpu,
            'encoder': encoder if use_gpu else 'libx264',
            'quality_preset': 'medium' if use_gpu else 'fast',
            'max_memory_mb': int(self.ram_gb * 512)
        }
