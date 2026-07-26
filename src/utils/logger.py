import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logger():
    handlers = [logging.StreamHandler(sys.stdout)]

    # Persistent rotating log file — stdout is invisible in the windowed .exe build,
    # so without this, production runs produce no logs at all.
    log_dir = None
    try:
        log_dir = Path.home() / '.video_editor_lite' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_dir / 'app.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8'
        ))
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    logging.getLogger('ffmpeg').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)

    # Capture hard crashes (segfaults, aborts) with a traceback file.
    try:
        import faulthandler
        if log_dir is not None:
            crash_file = open(log_dir / 'crash.log', 'a', encoding='utf-8')
            faulthandler.enable(file=crash_file)
    except Exception:
        pass

def get_logger(name):
    return logging.getLogger(name)
