from PySide6.QtWidgets import QWidget, QGridLayout, QPushButton
from PySide6.QtCore import Qt

class AspectRatioContainer(QWidget):
    def __init__(self, child_widget, aspect_ratio=16/9):
        super().__init__()
        self.aspect_ratio = aspect_ratio
        self.child_widget = child_widget
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Use grid layout to perfectly center the child
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        layout.setRowStretch(0, 1)
        layout.setRowStretch(2, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(2, 1)
        
        self.setStyleSheet("background-color: #111111;")
        layout.addWidget(child_widget, 1, 1)

        # Floating Exit Fullscreen Button
        self.exit_fs_btn = QPushButton("✖ Exit Fullscreen (Esc)", self)
        self.exit_fs_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 180);
                color: #ffffff;
                border: 1px solid #00ffcc;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #d9534f;
                border-color: #ffffff;
            }
        """)
        self.exit_fs_btn.setVisible(False)
        self.exit_fs_btn.clicked.connect(self._on_exit_fs_clicked)
        
    def _on_exit_fs_clicked(self):
        main_win = self._find_main_window()
        if hasattr(main_win, 'toggle_fullscreen_preview'):
            main_win.toggle_fullscreen_preview()

    def _find_main_window(self):
        win = self.window()
        if hasattr(win, 'toggle_fullscreen_preview'):
            return win
        p = self.parent()
        while p:
            if hasattr(p, 'toggle_fullscreen_preview'):
                return p
            p = p.parent()
        return win

    def keyPressEvent(self, event):
        key = event.key()
        main_win = self._find_main_window()

        if key in (Qt.Key_Escape, Qt.Key_F):
            if hasattr(main_win, 'toggle_fullscreen_preview'):
                main_win.toggle_fullscreen_preview()
                event.accept()
                return
        elif key == Qt.Key_Space:
            if hasattr(main_win, 'play_pause_toggle'):
                main_win.play_pause_toggle()
                event.accept()
                return
        super().keyPressEvent(event)
        
    def set_aspect_ratio(self, ratio: float):
        if self.aspect_ratio != ratio:
            self.aspect_ratio = ratio
            self._resize_child(self.size())
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_child(event.size())
        if self.exit_fs_btn:
            self.exit_fs_btn.move(self.width() - self.exit_fs_btn.width() - 20, 20)
        
    def _resize_child(self, size):
        w = size.width()
        h = size.height()
        if h == 0 or w == 0:
            return
            
        if w / h > self.aspect_ratio:
            new_h = h
            new_w = h * self.aspect_ratio
        else:
            new_w = w
            new_h = w / self.aspect_ratio
            
        self.child_widget.setFixedSize(int(new_w), int(new_h))
