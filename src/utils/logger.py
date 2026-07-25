import logging
import sys

def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.getLogger('ffmpeg').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)

def get_logger(name):
    return logging.getLogger(name)
