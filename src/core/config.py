import json
from pathlib import Path

class LightConfig:
    def __init__(self):
        self.app_name = "Video Editor Lite"
        self.version = "1.0.0"
        self.settings = {
            'threads': self._get_optimal_threads(),
            'memory_limit_mb': 1024,
            'preview_fps': 15,
            'use_hardware_accel': True,
            'cache_enabled': True,
            'max_cache_mb': 512,
            'auto_save_interval': 30,
            'render_preset': 'balanced'
        }

    def _get_optimal_threads(self) -> int:
        import multiprocessing
        cores = multiprocessing.cpu_count()
        return max(1, int(cores * 0.75))

    def save(self):
        config_path = Path.home() / '.video_editor_lite' / 'config.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(self.settings, f, indent=2)

    def load(self):
        config_path = Path.home() / '.video_editor_lite' / 'config.json'
        if config_path.exists():
            with open(config_path, 'r') as f:
                self.settings.update(json.load(f))
