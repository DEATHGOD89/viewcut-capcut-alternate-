from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton
from PySide6.QtCore import Qt
from gui.aspect_ratio_container import AspectRatioContainer

class FullscreenPreviewDialog(QDialog):
    def __init__(self, canvas_frame, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.canvas_frame = canvas_frame
        self.main_window = parent
        self.setStyleSheet("background-color: #000000;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        aspect_ratio = getattr(parent, 'aspect_ratio', 16/9)
        self.aspect_container = AspectRatioContainer(canvas_frame, aspect_ratio)
        layout.addWidget(self.aspect_container)
        
        # Floating Exit Fullscreen Button
        self.exit_btn = QPushButton("✖ Exit Fullscreen (Esc / F)", self)
        self.exit_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 200);
                color: #ffffff;
                border: 1px solid #00ffcc;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #d9534f;
                border-color: #ffffff;
            }
        """)
        self.exit_btn.clicked.connect(self.accept)

        # Floating Play/Pause Button
        self.play_btn = QPushButton("▶ Play / ⏸ Pause (Space)", self)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 200);
                color: #00ffcc;
                border: 1px solid #00ffcc;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #00b386;
                color: #ffffff;
            }
        """)
        self.play_btn.clicked.connect(self._toggle_play)
        
    def _toggle_play(self):
        if self.main_window and hasattr(self.main_window, 'play_pause_toggle'):
            self.main_window.play_pause_toggle()
            if hasattr(self.main_window, 'playback_timer') and self.main_window.playback_timer.isActive():
                self.play_btn.setText("⏸ Pause (Space)")
            else:
                self.play_btn.setText("▶ Play (Space)")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'exit_btn'):
            self.exit_btn.move(self.width() - self.exit_btn.width() - 25, 25)
        if hasattr(self, 'play_btn'):
            self.play_btn.move((self.width() - self.play_btn.width()) // 2, self.height() - 65)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.accept()
            event.accept()
        elif key == Qt.Key_Space:
            self._toggle_play()
            event.accept()
        else:
            super().keyPressEvent(event)
