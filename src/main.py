import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from gui.main_window import MainWindow
from utils.logger import setup_logger
import os

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def main():
    setup_logger()

    app = QApplication(sys.argv)
    app.setApplicationName("Video Editor Lite")
    app.setOrganizationName("VideoEditorLite")
    
    icon_path = get_resource_path("LOGO.ico")
    app.setWindowIcon(QIcon(icon_path))

    try:
        from utils.ffmpeg_wrapper import FFmpegWrapper
        wrapper = FFmpegWrapper()
        import subprocess
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run([wrapper.ffmpeg_path, '-version'], capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, creationflags=creationflags)
    except Exception:
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText("FFmpeg not found!")
        msg.setInformativeText("Please install FFmpeg and add it to your PATH, or extract it into the 'ffmpeg' directory.")
        msg.exec()
        sys.exit(1)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == '__main__':
    main()
