import os
import subprocess
import logging
from pathlib import Path
from PySide6.QtCore import QThread, Signal

logger = get_logger = logging.getLogger(__name__)

class ProxyGeneratorThread(QThread):
    finished_proxy = Signal(str, str)  # (original_path, proxy_path)
    failed_proxy = Signal(str, str)    # (original_path, error_msg)

    def __init__(self, ffmpeg_path: str, source_path: str, proxy_dir: str, encoder: str = 'libx264'):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.source_path = source_path
        self.proxy_dir = proxy_dir
        self.encoder = encoder

    def run(self):
        try:
            os.makedirs(self.proxy_dir, exist_ok=True)
            stem = Path(self.source_path).stem
            proxy_path = os.path.join(self.proxy_dir, f"{stem}_proxy540p.mp4")

            if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 1024:
                self.finished_proxy.emit(self.source_path, proxy_path)
                return

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            enc = self.encoder if self.encoder in ['h264_qsv', 'h264_nvenc', 'h264_amf', 'h264_mf'] else 'libx264'

            cmd = [
                self.ffmpeg_path,
                '-y',
                '-i', self.source_path,
                '-vf', 'scale=-2:540',
                '-c:v', enc,
                '-preset', 'fast',
                '-c:a', 'aac',
                '-b:a', '128k',
                proxy_path
            ]

            logger.info(f"[PROXY ENGINE] Generating proxy: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=creationflags)

            if res.returncode == 0 and os.path.exists(proxy_path):
                logger.info(f"[PROXY ENGINE] Proxy created successfully: {proxy_path}")
                self.finished_proxy.emit(self.source_path, proxy_path)
            else:
                # Fallback to libx264 if hardware encoder fails
                fallback_cmd = [
                    self.ffmpeg_path, '-y', '-i', self.source_path,
                    '-vf', 'scale=-2:540', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-c:a', 'aac', proxy_path
                ]
                res2 = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=600, creationflags=creationflags)
                if res2.returncode == 0 and os.path.exists(proxy_path):
                    self.finished_proxy.emit(self.source_path, proxy_path)
                else:
                    self.failed_proxy.emit(self.source_path, res.stderr or res2.stderr or "Unknown error")
        except Exception as e:
            logger.error(f"[PROXY ENGINE] Failed proxy creation for {self.source_path}: {e}")
            self.failed_proxy.emit(self.source_path, str(e))

class ProxyEngine:
    def __init__(self, ffmpeg_path: str, proxy_dir: str = None, encoder: str = 'libx264'):
        self.ffmpeg_path = ffmpeg_path
        self.proxy_dir = proxy_dir or os.path.join(os.path.expanduser("~"), ".videoeditor", "proxies")
        self.encoder = encoder
        self.proxies = {}  # {original_path: proxy_path}
        self.active_threads = []

    def get_preview_path(self, original_path: str) -> str:
        """Returns the proxy file path if available, otherwise original_path."""
        return self.proxies.get(original_path, original_path)

    def generate_proxy_async(self, source_path: str, callback=None):
        if not source_path or not os.path.exists(source_path):
            return

        if source_path in self.proxies and os.path.exists(self.proxies[source_path]):
            if callback:
                callback(source_path, self.proxies[source_path])
            return

        thread = ProxyGeneratorThread(self.ffmpeg_path, source_path, self.proxy_dir, self.encoder)

        def _on_finished(orig, proxy):
            self.proxies[orig] = proxy
            if callback:
                callback(orig, proxy)
            if thread in self.active_threads:
                self.active_threads.remove(thread)

        def _on_failed(orig, err):
            if thread in self.active_threads:
                self.active_threads.remove(thread)

        thread.finished_proxy.connect(_on_finished)
        thread.failed_proxy.connect(_on_failed)
        self.active_threads.append(thread)
        thread.start()
