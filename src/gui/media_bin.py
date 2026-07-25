import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon
from gui.timeline import get_clip_thumbnail

class MediaBinWidget(QWidget):
    media_double_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.media_paths = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        group = QGroupBox("Media Library")
        group_layout = QVBoxLayout(group)

        btn_layout = QHBoxLayout()
        self.import_files_btn = QPushButton("Import Files")
        self.import_files_btn.clicked.connect(self.import_files)
        btn_layout.addWidget(self.import_files_btn)

        self.import_folder_btn = QPushButton("Import Folder")
        self.import_folder_btn.clicked.connect(self.import_folder)
        btn_layout.addWidget(self.import_folder_btn)

        group_layout.addLayout(btn_layout)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(60, 40))
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        group_layout.addWidget(self.list_widget)

        bin_action_layout = QHBoxLayout()
        add_timeline_btn = QPushButton("➕ Add to Timeline")
        add_timeline_btn.clicked.connect(self._on_add_to_timeline_clicked)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)

        bin_action_layout.addWidget(add_timeline_btn)
        bin_action_layout.addWidget(remove_btn)
        group_layout.addLayout(bin_action_layout)

        layout.addWidget(group)

    def set_media_paths(self, paths: list):
        self.media_paths = list(paths)
        self.refresh_library()

    def refresh_library(self):
        # Silently purge non-existent file paths automatically with zero warnings or popups
        valid_paths = [p for p in self.media_paths if os.path.exists(p)]
        self.media_paths = valid_paths

        self.list_widget.clear()
        for path in self.media_paths:
            name = Path(path).name
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)

            thumb = get_clip_thumbnail(path)
            if thumb and not thumb.isNull():
                item.setIcon(QIcon(thumb))

            self.list_widget.addItem(item)

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Media Files",
            "",
            "Media Files (*.mp4 *.mov *.avi *.mkv *.webm *.png *.jpg *.jpeg *.bmp *.webp *.mp3 *.wav);;All Files (*.*)"
        )
        if files:
            for f in files:
                if f not in self.media_paths and os.path.exists(f):
                    self.media_paths.append(f)
            self.refresh_library()

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Import Media Folder")
        if folder:
            valid_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.png', '.jpg', '.jpeg', '.bmp', '.webp', '.mp3', '.wav'}
            for root, _, files in os.walk(folder):
                for f in files:
                    if Path(f).suffix.lower() in valid_exts:
                        full_path = os.path.join(root, f)
                        if full_path not in self.media_paths and os.path.exists(full_path):
                            self.media_paths.append(full_path)
            self.refresh_library()

    def remove_selected(self):
        current_item = self.list_widget.currentItem()
        if current_item:
            path = current_item.data(Qt.UserRole)
            if path in self.media_paths:
                self.media_paths.remove(path)
            self.refresh_library()

    def _on_item_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self.media_double_clicked.emit(path)

    def _on_add_to_timeline_clicked(self):
        current_item = self.list_widget.currentItem()
        if current_item:
            path = current_item.data(Qt.UserRole)
            if path and os.path.exists(path):
                self.media_double_clicked.emit(path)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self.media_double_clicked.emit(path)
        else:
            self.refresh_library()
