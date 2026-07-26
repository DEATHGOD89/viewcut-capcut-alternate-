from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
import os
import json
import subprocess
from pathlib import Path

from editors.video_editor import VideoEditor
from editors.audio_editor import AudioEditor
from editors.filter_editor import FilterEditor
from core.config import LightConfig
from core.hardware import HardwareInfo
from core.project import Project, Track, Clip
from gui.worker import FFmpegWorker
from gui.timeline import TimelineWidget
from gui.aspect_ratio_container import AspectRatioContainer
from gui.canvas_frame import CanvasFrame
from gui.media_bin import MediaBinWidget
from gui.fullscreen_dialog import FullscreenPreviewDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.config = LightConfig()
        self.config.load()
        self.hardware = HardwareInfo()
        self.video_editor = VideoEditor()
        self.audio_editor = AudioEditor()
        settings = self.hardware.get_optimal_settings()
        self.filter_editor = FilterEditor(settings)

        self.project = Project("My Project")
        self.sub_track = Track("🔤 Subtitles & Text", "subtitle")
        self.overlay_track = Track("🖼️ Image / PiP Overlay", "overlay")
        self.video_track = Track("🎬 Video Track 1", "video")
        self.audio_track = Track("🎵 Audio Track 1", "audio")

        self.project.add_track(self.sub_track)
        self.project.add_track(self.overlay_track)
        self.project.add_track(self.video_track)
        self.project.add_track(self.audio_track)

        self.current_file = None
        self.export_path = None
        self.clip_start = 0
        self.clip_end = 0
        self._temp_files = []
        self._undo_stack = []
        self._redo_stack = []
        self.worker = None
        self._sub_worker = None
        self._current_video_source = None

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)

        self.timeline_audio_player = QMediaPlayer()
        self.timeline_audio_output = QAudioOutput()
        self.timeline_audio_player.setAudioOutput(self.timeline_audio_output)
        
        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self._playback_tick)

        # Debounce timer so slider drags don't decode+render a frame on every tick
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(75)
        self._preview_debounce.timeout.connect(self._render_live_preview_now)

        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.positionChanged.connect(self._on_player_position_changed)

        self.init_ui()
        self.setup_shortcuts()
        self.apply_styles()
        self.show_hardware_info()

        from editors.proxy_engine import ProxyEngine
        self.proxy_engine = ProxyEngine(self.video_editor.ffmpeg.ffmpeg_path, encoder=self.video_editor.hardware.gpu_info.get('encoder', 'libx264'))

    def _guard_typing(self, fn):
        """Ignore single-letter shortcuts while the user is typing in a text field."""
        def _cb():
            w = QApplication.focusWidget()
            if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return
            fn()
        return _cb

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_project)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_project)
        QShortcut(QKeySequence("Space"), self, self._guard_typing(self.toggle_playback))
        QShortcut(QKeySequence("Delete"), self, self._guard_typing(self.delete_selected_clip))
        QShortcut(QKeySequence("S"), self, self._guard_typing(self.split_video))
        QShortcut(QKeySequence("V"), self, self._guard_typing(self._toggle_move_clip_mode))
        QShortcut(QKeySequence("F"), self, self._guard_typing(self.toggle_fullscreen_preview))
        QShortcut(QKeySequence("C"), self, self._guard_typing(lambda: self.canvas_frame.set_roi_selection_mode(True)))

    def _save_undo_state(self):
        import copy
        if len(self._undo_stack) >= 30:
            self._undo_stack.pop(0)
        self._undo_stack.append(copy.deepcopy(self.project))
        self._redo_stack.clear()

    def _rebind_default_tracks(self):
        """Point the convenience track references at the current project's tracks,
        creating any that are missing (e.g. older project files)."""
        def _find_or_create(ttype, name):
            tr = next((t for t in self.project.tracks if t.track_type == ttype), None)
            if tr is None:
                tr = Track(name, ttype)
                self.project.add_track(tr)
            return tr
        self.sub_track = _find_or_create('subtitle', "🔤 Subtitles & Text")
        self.overlay_track = _find_or_create('overlay', "🖼️ Image / PiP Overlay")
        self.video_track = _find_or_create('video', "🎬 Video Track 1")
        self.audio_track = _find_or_create('audio', "🎵 Audio Track 1")

    def undo(self):
        if not self._undo_stack:
            return
        import copy
        self._redo_stack.append(copy.deepcopy(self.project))
        self.project = self._undo_stack.pop()
        self._rebind_default_tracks()
        self._last_active_clip = None
        self.timeline.load_project(self.project)

    def redo(self):
        if not self._redo_stack:
            return
        import copy
        self._undo_stack.append(copy.deepcopy(self.project))
        self.project = self._redo_stack.pop()
        self._rebind_default_tracks()
        self._last_active_clip = None
        self.timeline.load_project(self.project)

    def save_project(self):
        default_dir = os.path.join(os.path.expanduser("~"), "Videos")
        os.makedirs(default_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As...",
            os.path.join(default_dir, f"{self.project.name or 'project'}.veproj.json"),
            "Video Editor Project (*.veproj.json *.json);;All Files (*.*)")
        if not path:
            return
        try:
            data = {
                'app': 'VideoEditorLite',
                'version': 1,
                'project': self.project.to_dict(),
                'media_library': list(getattr(self.media_bin, 'media_paths', [])),
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.statusBar().showMessage(f"💾 Project saved: {path}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save project:\n{e}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project...", os.path.join(os.path.expanduser("~"), "Videos"),
            "Video Editor Project (*.veproj.json *.json);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            proj_data = data.get('project', data)
            self._save_undo_state()
            self.project = Project.from_dict(proj_data)
            self._rebind_default_tracks()
            self._last_active_clip = None
            self._current_video_source = None
            media_paths = data.get('media_library', [])
            if media_paths:
                self.media_bin.set_media_paths(media_paths)
            self.timeline.load_project(self.project)
            self._sync_media_player(0.0, force_seek=True)
            self.update_time_label()
            self.statusBar().showMessage(f"📁 Project loaded: {Path(path).name}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Open Failed", f"Could not open project:\n{e}")

    def toggle_playback(self):
        if self.playback_timer.isActive():
            self.stop_preview()
        else:
            self.play_preview()

    def init_ui(self):
        self.setWindowTitle("Video Editor Lite")
        self.setGeometry(100, 100, 1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.create_toolbar()
        layout.addWidget(self.toolbar)

        content = QHBoxLayout()

        preview_widget = QWidget()
        self.preview_layout = QVBoxLayout(preview_widget)
        preview_layout = self.preview_layout

        self.canvas_frame = CanvasFrame()
        self.media_player.setVideoOutput(self.canvas_frame.video_widget)
        
        self.aspect_container = AspectRatioContainer(self.canvas_frame, 16/9)
        preview_layout.addWidget(self.aspect_container)

        self.preview_label = QLabel("")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(30)
        preview_layout.addWidget(self.preview_label)

        control_panel = self.create_controls()
        preview_layout.addWidget(control_panel)

        self.media_bin = MediaBinWidget()
        self.media_bin.setMinimumWidth(250)
        self.media_bin.media_double_clicked.connect(self.add_media_from_bin)
        self.media_bin.set_media_paths(self.config.settings.get('media_library', []))

        self.settings_panel = self.create_settings_panel()
        self.settings_panel.setMinimumWidth(340)

        content.addWidget(self.media_bin, 2)
        content.addWidget(preview_widget, 5)
        content.addWidget(self.settings_panel, 3)

        layout.addLayout(content)

    def create_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QSize(24, 24))

        self.toggle_left_action = QAction("◀ Media Library", self)
        self.toggle_left_action.triggered.connect(self.toggle_left_sidebar)
        self.toolbar.addAction(self.toggle_left_action)

        self.toggle_right_action = QAction("Tools Panel ▶", self)
        self.toggle_right_action.triggered.connect(self.toggle_right_sidebar)
        self.toolbar.addAction(self.toggle_right_action)

        self.toolbar.addSeparator()

        open_action = QAction("📂 Import Files", self)
        open_action.triggered.connect(self.open_file)
        self.toolbar.addAction(open_action)

        save_proj_action = QAction("💾 Save Project", self)
        save_proj_action.triggered.connect(self.save_project)
        self.toolbar.addAction(save_proj_action)

        open_proj_action = QAction("📁 Open Project", self)
        open_proj_action.triggered.connect(self.open_project)
        self.toolbar.addAction(open_proj_action)

        self.toolbar.addSeparator()

        magic_ai_action = QAction("🪄 Magic AI Auto-Enhance", self)
        magic_ai_action.setToolTip("Smart 1-Click AI Auto-Enhancement & Super-Resolution")
        magic_ai_action.triggered.connect(self.run_magic_ai_auto_enhance)
        self.toolbar.addAction(magic_ai_action)

        self.toolbar.addSeparator()

        export_action = QAction("📤 Export Video", self)
        export_action.triggered.connect(self.export_video)
        self.toolbar.addAction(export_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        gpu_name = self.hardware.gpu_info.get('name', 'iGPU')
        enc = self.hardware.gpu_info.get('encoder', 'libx264')
        self.hw_label = QLabel(f"🚀 Active GPU: {gpu_name} ({enc}) | CPU: --% | RAM: --%")
        self.hw_label.setStyleSheet("color: #00ffcc; font-weight: bold; font-size: 11px; margin-right: 10px;")
        self.toolbar.addWidget(self.hw_label)
        self._start_hw_monitor_timer()

    def create_controls(self):
        control_container = QWidget()
        main_layout = QVBoxLayout(control_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        play_btn = QPushButton("Play")
        play_btn.clicked.connect(self.play_preview)
        btn_layout.addWidget(play_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self.stop_preview)
        btn_layout.addWidget(stop_btn)

        btn_layout.addStretch()

        self.time_label = QLabel("Pos: 00:00 / 00:00")
        btn_layout.addWidget(self.time_label)

        main_layout.addWidget(btn_widget)

        # Timeline Action Bar
        action_bar = QWidget()
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 4, 0, 4)

        split_btn = QPushButton("✂️ Split (S)")
        split_btn.setToolTip("Split selected clip at playhead position (Shortcut: S)")
        split_btn.clicked.connect(self.split_video)

        del_btn = QPushButton("🗑️ Delete (Del)")
        del_btn.setToolTip("Remove selected clip from timeline (Shortcut: Delete)")
        del_btn.clicked.connect(self.delete_selected_clip)

        self.speed_btn = QPushButton("⚡ Speed (Custom)")
        self.speed_btn.setToolTip("Set custom clip playback speed (0.1x to 10.0x)")
        self.speed_btn.clicked.connect(self.open_custom_speed_dialog)

        sub_shortcut_btn = QPushButton("🔤 Auto Subtitles")
        sub_shortcut_btn.setToolTip("Generate instant AI voice subtitles")
        sub_shortcut_btn.clicked.connect(self.generate_auto_subtitles)

        undo_btn = QPushButton("↩️ Undo")
        undo_btn.setToolTip("Undo last edit action (Shortcut: Ctrl+Z)")
        undo_btn.clicked.connect(self.undo)

        redo_btn = QPushButton("↪️ Redo")
        redo_btn.setToolTip("Redo last edit action (Shortcut: Ctrl+Y)")
        redo_btn.clicked.connect(self.redo)

        self.drag_clip_mode_btn = QPushButton("🖐️ Move Clip Mode: OFF")
        self.drag_clip_mode_btn.setCheckable(True)
        self.drag_clip_mode_btn.setToolTip("Toggle Move Mode ON to drag clips across timeline tracks and layers")
        self.drag_clip_mode_btn.clicked.connect(self._toggle_move_clip_mode)

        fullscreen_btn = QPushButton("📺 Fullscreen (F)")
        fullscreen_btn.setToolTip("Expand video preview canvas to full screen (Shortcut: F)")
        fullscreen_btn.clicked.connect(self.toggle_fullscreen_preview)

        action_layout.addWidget(split_btn)
        action_layout.addWidget(del_btn)
        action_layout.addWidget(self.drag_clip_mode_btn)
        action_layout.addWidget(self.speed_btn)
        action_layout.addWidget(sub_shortcut_btn)
        action_layout.addWidget(undo_btn)
        action_layout.addWidget(redo_btn)
        action_layout.addWidget(fullscreen_btn)
        action_layout.addStretch()

        main_layout.addWidget(action_bar)

        self.timeline = TimelineWidget()
        self.timeline.position_changed.connect(self._on_timeline_scrub)
        main_layout.addWidget(self.timeline)

        return control_container

    def open_custom_speed_dialog(self):
        items = self.timeline.timeline_scene.selectedItems()
        if not items or not hasattr(items[0], 'clip'):
            QMessageBox.warning(self, "Speed Ramping", "Please click on a clip in the timeline to select it first.")
            return

        clip = items[0].clip
        current_speed = getattr(clip, 'speed', 1.0)

        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QSlider, QDoubleSpinBox, QLabel, QPushButton, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("⚡ Custom Clip Playback Speed")
        dlg.setMinimumWidth(360)
        dlg.setStyleSheet("""
            QDialog { background-color: #18181c; color: #ffffff; }
            QLabel { color: #ffffff; font-size: 13px; }
            QSlider::groove:horizontal { height: 6px; background: #2b2b36; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00ffcc; width: 16px; margin: -5px 0; border-radius: 8px; }
            QDoubleSpinBox { background: #22222a; color: #00ffcc; border: 1px solid #00ffcc; border-radius: 4px; padding: 4px; font-weight: bold; }
        """)

        layout = QVBoxLayout(dlg)
        lbl = QLabel(f"Set Speed for selected clip: <b>{current_speed:.2f}x</b>")
        lbl.setStyleSheet("font-size: 13px; color: #00ffcc;")
        layout.addWidget(lbl)

        speed_h = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(1, 100) # 0.1x to 10.0x
        slider.setValue(int(current_speed * 10))

        spin = QDoubleSpinBox()
        spin.setRange(0.1, 10.0)
        spin.setValue(current_speed)
        spin.setSingleStep(0.1)
        spin.setSuffix("x")

        slider.valueChanged.connect(lambda v: (spin.setValue(v / 10.0), lbl.setText(f"Speed: <b>{v / 10.0:.2f}x</b>")))
        spin.valueChanged.connect(lambda v: (slider.setValue(int(v * 10)), lbl.setText(f"Speed: <b>{v:.2f}x</b>")))

        speed_h.addWidget(slider)
        speed_h.addWidget(spin)
        layout.addLayout(speed_h)

        # Quick Presets
        presets_h = QHBoxLayout()
        for p_val, p_text in [(0.25, "0.25x"), (0.5, "0.5x"), (1.0, "1.0x Normal"), (1.5, "1.5x"), (2.0, "2.0x Fast"), (4.0, "4.0x")]:
            btn = QPushButton(p_text)
            btn.setStyleSheet("background: #25252d; color: #ffffff; border-radius: 4px; padding: 5px;")
            btn.clicked.connect(lambda _, v=p_val: spin.setValue(v))
            presets_h.addWidget(btn)
        layout.addLayout(presets_h)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            new_speed = spin.value()
            self._save_undo_state()
            clip.speed = new_speed
            if hasattr(self, 'speed_btn'):
                self.speed_btn.setText(f"⚡ Speed {new_speed:.1f}x")
            QMessageBox.information(self, "Speed Updated", f"Clip speed set to {new_speed:.2f}x!")

    def create_settings_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setUsesScrollButtons(True)
        tabs = self.settings_tabs

        def _make_scroll_tab(widget):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            return scroll

        # TAB 1: 🪄 Magic AI Auto-Enhance
        filter_tab = QWidget()
        filter_layout = QVBoxLayout(filter_tab)
        filter_group = QGroupBox("🪄 Magic AI Auto-Enhance & Super-Resolution")
        filter_g_layout = QVBoxLayout(filter_group)

        magic_btn = QPushButton("🪄 1-Click Magic AI Auto-Enhance")
        magic_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7b2cbf, stop:1 #00ffcc);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9d4edd, stop:1 #33ffe6);
            }
        """)
        magic_btn.clicked.connect(self.run_magic_ai_auto_enhance)
        filter_g_layout.addWidget(magic_btn)

        upscale_layout = QFormLayout()
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.addItems([
            '💎 Heavy-Duty Studio Mode (Maximum Quality)',
            '🎥 Real Video (Live-Action & People)',
            '🎨 Anime & Cartoon (Line-Art & Cell-Shading)'
        ])
        self.ai_model_combo.currentTextChanged.connect(self._update_live_filter_preview)
        upscale_layout.addRow("AI Model Preset:", self.ai_model_combo)

        self.ai_upscale_combo = QComboBox()
        self.ai_upscale_combo.addItems(['2160p 4K (Ultra HD)', '1080p Full HD', '1440p 2K', '4320p 8K', 'Auto (Original)'])
        upscale_layout.addRow("AI Super-Res Target:", self.ai_upscale_combo)

        self.ai_strength_slider = QSlider(Qt.Horizontal)
        self.ai_strength_slider.setRange(0, 100)
        self.ai_strength_slider.setValue(0)
        self.ai_strength_slider.valueChanged.connect(self._update_live_filter_preview)
        upscale_layout.addRow("AI Detail Intensity:", self.ai_strength_slider)

        filter_g_layout.addLayout(upscale_layout)
        filter_g_layout.addStretch()

        filter_layout.addWidget(filter_group)
        tabs.addTab(_make_scroll_tab(filter_tab), "🪄 Magic AI")

        # TAB 2: 🎛️ Color & Pro Tuning
        color_tab = QWidget()
        color_layout_tab = QVBoxLayout(color_tab)
        color_group = QGroupBox("Professional Video Color Balancing & Tuning")
        color_layout = QFormLayout(color_group)

        def _make_color_slider(name, min_v, max_v, default_v, unit="%"):
            h_layout = QHBoxLayout()
            sl = QSlider(Qt.Horizontal)
            sl.setRange(min_v, max_v)
            sl.setValue(default_v)
            lbl = QLabel(f"{default_v}{unit}")
            lbl.setFixedWidth(50)
            lbl.setStyleSheet("color: #00ffcc; font-weight: bold;")
            sl.valueChanged.connect(lambda v: (lbl.setText(f"{v}{unit}"), self._update_live_filter_preview()))
            h_layout.addWidget(sl)
            h_layout.addWidget(lbl)
            color_layout.addRow(f"{name}:", h_layout)
            return sl, lbl

        self.bright_slider, self.bright_lbl = _make_color_slider("☀️ Brightness", -100, 100, 0)
        self.contrast_slider, self.contrast_lbl = _make_color_slider("🌓 Contrast", -100, 100, 0)
        self.sat_slider, self.sat_lbl = _make_color_slider("🎨 Saturation", -100, 100, 0)
        self.denoise_slider, self.denoise_lbl = _make_color_slider("🧹 Denoise / Smooth", 0, 100, 0)
        self.sharp_slider, self.sharp_lbl = _make_color_slider("🔪 Sharpness", 0, 100, 0)
        self.temp_slider, self.temp_lbl = _make_color_slider("🌡️ Temperature", -100, 100, 0)
        self.exp_slider, self.exp_lbl = _make_color_slider("💡 Exposure", -100, 100, 0)

        color_layout_tab.addWidget(color_group)

        from gui.color_scopes import ColorScopesWidget
        self.color_scopes_widget = ColorScopesWidget(self)
        color_layout_tab.addWidget(self.color_scopes_widget)

        color_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(color_tab), "🎛️ Color Pro Tuning")

        # TAB 2: ✂️ Watermark
        wm_tab = QWidget()
        wm_layout_tab = QVBoxLayout(wm_tab)
        wm_group = QGroupBox("Watermark Remover")
        wm_layout = QFormLayout(wm_group)

        self.enable_wm_cb = QCheckBox("Enable Watermark Removal")
        self.enable_wm_cb.setChecked(self.config.settings.get('enable_wm', False))
        self.enable_wm_cb.toggled.connect(self._update_wm_overlay)
        wm_layout.addRow("", self.enable_wm_cb)

        select_wm_area_btn = QPushButton("Select Area on Video")
        select_wm_area_btn.clicked.connect(lambda: self.canvas_frame.set_roi_selection_mode(True))
        wm_layout.addRow("", select_wm_area_btn)

        self.wm_x_spin = QSpinBox()
        self.wm_x_spin.setRange(0, 7680)
        self.wm_x_spin.setValue(self.config.settings.get('wm_x', 50))
        self.wm_x_spin.valueChanged.connect(self._update_wm_overlay)
        wm_layout.addRow("Position X:", self.wm_x_spin)

        self.wm_y_spin = QSpinBox()
        self.wm_y_spin.setRange(0, 7680)
        self.wm_y_spin.setValue(self.config.settings.get('wm_y', 50))
        self.wm_y_spin.valueChanged.connect(self._update_wm_overlay)
        wm_layout.addRow("Position Y:", self.wm_y_spin)

        self.wm_w_spin = QSpinBox()
        self.wm_w_spin.setRange(2, 7680)
        self.wm_w_spin.setValue(self.config.settings.get('wm_w', 150))
        self.wm_w_spin.valueChanged.connect(self._update_wm_overlay)
        wm_layout.addRow("Width:", self.wm_w_spin)

        self.wm_h_spin = QSpinBox()
        self.wm_h_spin.setRange(2, 7680)
        self.wm_h_spin.setValue(self.config.settings.get('wm_h', 80))
        self.wm_h_spin.valueChanged.connect(self._update_wm_overlay)
        wm_layout.addRow("Height:", self.wm_h_spin)

        self.canvas_frame.region_selected.connect(self._on_wm_region_selected)

        wm_layout_tab.addWidget(wm_group)
        wm_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(wm_tab), "✂️ Watermark")

        # TAB 3: 🎵 Audio
        audio_tab = QWidget()
        audio_layout_tab = QVBoxLayout(audio_tab)
        audio_group = QGroupBox("Audio Settings")
        audio_layout = QFormLayout(audio_group)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setValue(self.config.settings.get('last_volume', 100))
        self.volume_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100.0))
        self.audio_output.setVolume(self.volume_slider.value() / 100.0)
        audio_layout.addRow("Volume:", self.volume_slider)

        self.voice_boost_btn = QCheckBox("Voice Boost")
        self.voice_boost_btn.setChecked(self.config.settings.get('voice_boost', False))
        audio_layout.addRow("", self.voice_boost_btn)

        clip_audio_group = QGroupBox("Selected Clip Volume & Mute Controls")
        clip_audio_layout = QFormLayout(clip_audio_group)

        self.clip_volume_slider = QSlider(Qt.Horizontal)
        self.clip_volume_slider.setRange(0, 200)
        self.clip_volume_slider.setValue(100)
        self.clip_volume_val_label = QLabel("100%")
        self.clip_volume_val_label.setStyleSheet("color: #00ffcc; font-weight: bold;")
        
        clip_vol_h = QHBoxLayout()
        clip_vol_h.addWidget(self.clip_volume_slider)
        clip_vol_h.addWidget(self.clip_volume_val_label)
        
        self.clip_volume_slider.valueChanged.connect(self._on_clip_volume_changed)
        clip_audio_layout.addRow("Clip Volume:", clip_vol_h)

        self.clip_mute_btn = QPushButton("🔇 Mute Selected Clip Audio (OFF)")
        self.clip_mute_btn.setCheckable(True)
        self.clip_mute_btn.clicked.connect(self._on_clip_mute_toggled)
        clip_audio_layout.addRow("", self.clip_mute_btn)

        audio_layout_tab.addWidget(audio_group)
        audio_layout_tab.addWidget(clip_audio_group)
        audio_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(audio_tab), "🎵 Audio")

        # TAB 4: ⚙️ Export & Canvas
        export_tab = QWidget()
        export_layout_tab = QVBoxLayout(export_tab)

        canvas_group = QGroupBox("Canvas Settings")
        canvas_layout = QFormLayout(canvas_group)

        self.aspect_ratio_combo = QComboBox()
        self.aspect_ratio_combo.addItems(['16:9', '9:16', '1:1', '4:5', '21:9'])
        self.aspect_ratio_combo.currentTextChanged.connect(self._on_aspect_ratio_changed)
        canvas_layout.addRow("Canvas Ratio:", self.aspect_ratio_combo)

        self.scale_mode_combo = QComboBox()
        self.scale_mode_combo.addItems(['Fit', 'Fill', 'Stretch'])
        self.scale_mode_combo.currentTextChanged.connect(self.canvas_frame.set_scale_mode)
        canvas_layout.addRow("Scale Mode:", self.scale_mode_combo)

        self.canvas_zoom_combo = QComboBox()
        self.canvas_zoom_combo.addItems(['Fit (Auto)', '50%', '75%', '100% (1:1)', '150%', '200%', '300%', '400%'])
        self.canvas_zoom_combo.currentTextChanged.connect(self._on_canvas_zoom_changed)
        canvas_layout.addRow("🔍 Live Zoom:", self.canvas_zoom_combo)

        export_layout_tab.addWidget(canvas_group)

        export_group = QGroupBox("Export Settings")
        export_layout = QFormLayout(export_group)

        self.res_combo = QComboBox()
        self.res_combo.addItems(['Source', '720p', '1080p', '1440p', '4K', '8K'])
        self.res_combo.setCurrentText(self.config.settings.get('last_resolution', 'Source'))
        export_layout.addRow("Resolution:", self.res_combo)

        self.format_combo = QComboBox()
        self.format_combo.addItems(['MP4', 'MOV', 'AVI', 'MKV', 'MP3', 'PNG', 'JPG', 'BMP', 'WEBP'])
        self.format_combo.setCurrentText(self.config.settings.get('last_format', 'MP4'))
        export_layout.addRow("Format:", self.format_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['Source Quality', 'High', 'Medium', 'Low'])
        self.quality_combo.setCurrentText(self.config.settings.get('last_quality', 'Source Quality'))
        export_layout.addRow("Quality:", self.quality_combo)

        export_layout_tab.addWidget(export_group)
        export_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(export_tab), "⚙️ Canvas & Export")

        # TAB 5: 🔤 Subtitles & Text
        text_tab = QWidget()
        text_layout_tab = QVBoxLayout(text_tab)
        text_group = QGroupBox("Text Overlays & Auto Subtitles")
        text_layout = QFormLayout(text_group)

        self.enable_text_cb = QCheckBox("Enable Title Text Overlay")
        self.enable_text_cb.toggled.connect(self._update_live_text_preview)
        text_layout.addRow("", self.enable_text_cb)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Enter Title / Text Overlay...")
        self.text_input.textChanged.connect(self._update_live_text_preview)
        text_layout.addRow("Title:", self.text_input)

        add_text_clip_btn = QPushButton("➕ Add Text Title to Timeline at Playhead")
        add_text_clip_btn.setToolTip("Create a purple text clip on the timeline at current playhead position")
        add_text_clip_btn.clicked.connect(self.add_text_title_to_timeline)
        text_layout.addRow("", add_text_clip_btn)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 150)
        self.font_size_spin.setValue(36)
        self.font_size_spin.valueChanged.connect(self._update_live_text_preview)
        text_layout.addRow("Font Size:", self.font_size_spin)

        self.font_color_combo = QComboBox()
        self.font_color_combo.addItems(['white', 'yellow', 'red', 'cyan', 'green', 'black'])
        self.font_color_combo.currentTextChanged.connect(self._update_live_text_preview)
        text_layout.addRow("Color:", self.font_color_combo)

        self.text_bg_style_combo = QComboBox()
        self.text_bg_style_combo.addItems([
            'Transparent (Clean Glow)',
            '✨ Yellow Highlight',
            '💎 Cyberpunk Neon',
            '⬛ Dark Translucent Box',
            '🔴 Red Action Box'
        ])
        self.text_bg_style_combo.currentTextChanged.connect(self._update_live_text_preview)
        text_layout.addRow("Background Style:", self.text_bg_style_combo)

        self.sub_lang_combo = QComboBox()
        self.sub_lang_combo.addItems(['Auto Detect (Hindi / English)', 'Romanized Hindi (Hinglish - Namaste)', 'Hindi (Devanagari)', 'English', 'Spanish', 'French'])
        text_layout.addRow("Voice Language:", self.sub_lang_combo)

        self.sub_model_combo = QComboBox()
        self.sub_model_combo.addItems([
            'High Precision (Base Model - Recommended 95% Acc)',
            'Ultra Precision (Small Model - 97% Acc)',
            'Studio Broadcast (Medium Model - 99% Acc)',
            'Ultra-Fast Preview (Tiny Model - 1-2s Speed)'
        ])
        text_layout.addRow("AI Engine Accuracy:", self.sub_model_combo)

        self.sub_translate_cb = QCheckBox("Translate Hindi Speech to English Subtitles")
        self.sub_translate_cb.setChecked(True)
        text_layout.addRow("", self.sub_translate_cb)

        self.enable_auto_sub_cb = QCheckBox("Enable Auto Subtitles (burn into export)")
        text_layout.addRow("", self.enable_auto_sub_cb)

        generate_sub_btn = QPushButton("✨ Auto Subtitles (Voice-to-Text)")
        generate_sub_btn.clicked.connect(self.generate_auto_subtitles)
        text_layout.addRow("", generate_sub_btn)

        text_layout_tab.addWidget(text_group)
        text_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(text_tab), "🔤 Subtitles & Text")

        # TAB 6: ⚡ Motion & Transitions
        motion_tab = QWidget()
        motion_layout_tab = QVBoxLayout(motion_tab)
        motion_group = QGroupBox("Speed Ramping & Transitions")
        motion_layout = QFormLayout(motion_group)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(['0.25x (Super Slow)', '0.5x (Slow)', '0.75x', '1.0x (Normal)', '1.25x', '1.5x (Fast)', '2.0x (Double)', '4.0x (Fast Mo)'])
        self.speed_combo.setCurrentText('1.0x (Normal)')
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        motion_layout.addRow("Playback Speed:", self.speed_combo)

        self.transition_combo = QComboBox()
        self.transition_combo.addItems(['None', 'Fade', 'Dissolve', 'Wipe Left', 'Wipe Right', 'Slide Left', 'Slide Right'])
        motion_layout.addRow("Transition:", self.transition_combo)

        self.trans_dur_spin = QDoubleSpinBox()
        self.trans_dur_spin.setRange(0.2, 5.0)
        self.trans_dur_spin.setValue(1.0)
        self.trans_dur_spin.setSingleStep(0.1)
        motion_layout.addRow("Transition Duration (s):", self.trans_dur_spin)

        kf_group = QGroupBox("Keyframe Motion")
        kf_layout = QFormLayout(kf_group)

        self.kf_zoom_spin = QDoubleSpinBox()
        self.kf_zoom_spin.setRange(0.5, 3.0)
        self.kf_zoom_spin.setValue(1.0)
        self.kf_zoom_spin.setSingleStep(0.1)
        kf_layout.addRow("Zoom Level:", self.kf_zoom_spin)

        add_kf_btn = QPushButton("➕ Add Keyframe at Playhead")
        add_kf_btn.clicked.connect(self.add_keyframe_at_playhead)
        kf_layout.addRow("", add_kf_btn)

        motion_layout_tab.addWidget(motion_group)
        motion_layout_tab.addWidget(kf_group)
        motion_layout_tab.addStretch()
        tabs.addTab(_make_scroll_tab(motion_tab), "⚡ Motion & Transitions")

        layout.addWidget(tabs)
        return panel

    def apply_styles(self):
        style = """
        QMainWindow {
            background: #121214;
        }
        QWidget {
            color: #e1e1e6;
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 12px;
        }
        QTabWidget::pane {
            border: 1px solid #2d2d38;
            background: #18181c;
            border-radius: 8px;
        }
        QTabBar::tab {
            background: #22222a;
            color: #a0a0b0;
            padding: 8px 14px;
            font-weight: bold;
            font-size: 11px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 3px;
            border: 1px solid #2d2d38;
        }
        QTabBar::tab:selected {
            background: #0088cc;
            color: #ffffff;
            border-bottom: 2px solid #00ffcc;
        }
        QTabBar::tab:hover {
            background: #2a2a36;
            color: #ffffff;
        }
        QGroupBox {
            color: #00ffcc;
            font-weight: bold;
            border: 1px solid #2d2d38;
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            background: #1a1a20;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px 0 6px;
            background: #121214;
        }
        QLabel {
            color: #c4c4d0;
        }
        QPushButton {
            background: #282834;
            color: #ffffff;
            border: 1px solid #3a3a4c;
            padding: 7px 14px;
            border-radius: 5px;
            font-weight: bold;
        }
        QPushButton:hover {
            background: #00b386;
            color: #ffffff;
            border-color: #00ffcc;
        }
        QPushButton:pressed {
            background: #008060;
        }
        QComboBox {
            background: #22222a;
            color: #ffffff;
            border: 1px solid #3a3a4c;
            border-radius: 4px;
            padding: 5px 8px;
        }
        QComboBox:hover {
            border-color: #00ffcc;
        }
        QComboBox QAbstractItemView {
            background: #1e1e24;
            color: #ffffff;
            selection-background-color: #0088cc;
        }
        QSlider::groove:horizontal {
            height: 5px;
            background: #2d2d38;
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #00ffcc;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #ffffff;
            border: 2px solid #00ffcc;
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
        }
        QSlider::handle:horizontal:hover {
            background: #00ffcc;
        }
        QLineEdit, QSpinBox, QDoubleSpinBox {
            background: #22222a;
            color: #ffffff;
            border: 1px solid #3a3a4c;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #00ffcc;
        }
        QToolBar {
            background: #18181c;
            border-bottom: 1px solid #2d2d38;
            spacing: 6px;
            padding: 4px;
        }
        """
        self.setStyleSheet(style)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        if self._sub_worker is not None and self._sub_worker.isRunning():
            self._sub_worker.wait(1500)
        if hasattr(self, 'hw_timer'):
            self.hw_timer.stop()
        self.playback_timer.stop()
        self.media_player.stop()
        self.timeline_audio_player.stop()
        try:
            from editors.unified_renderer import UnifiedRenderer
            UnifiedRenderer.release_captures()
        except Exception:
            pass
        if hasattr(self, 'proxy_engine'):
            for th in list(getattr(self.proxy_engine, 'active_threads', [])):
                th.wait(200)

        self.config.settings['last_format'] = self.format_combo.currentText()
        self.config.settings['last_quality'] = self.quality_combo.currentText()
        self.config.settings['last_resolution'] = self.res_combo.currentText()
        self.config.settings['last_volume'] = self.volume_slider.value()
        self.config.settings['voice_boost'] = self.voice_boost_btn.isChecked()
        self.config.settings['enable_wm'] = self.enable_wm_cb.isChecked()
        self.config.settings['wm_x'] = self.wm_x_spin.value()
        self.config.settings['wm_y'] = self.wm_y_spin.value()
        self.config.settings['wm_w'] = self.wm_w_spin.value()
        self.config.settings['wm_h'] = self.wm_h_spin.value()
        self.config.settings['media_library'] = getattr(self.media_bin, 'media_paths', [])
        self.config.save()
        super().closeEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                local_path = url.toLocalFile()
                if local_path and os.path.exists(local_path):
                    self.add_media_from_bin(local_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def toggle_fullscreen_preview(self):
        if getattr(self, '_in_fullscreen_dlg', False):
            return

        self._in_fullscreen_dlg = True
        from gui.fullscreen_dialog import FullscreenPreviewDialog
        dlg = FullscreenPreviewDialog(self.canvas_frame, self)
        dlg.showFullScreen()
        dlg.exec()

        if hasattr(self, 'aspect_container'):
            self.aspect_container.layout().addWidget(self.canvas_frame, 1, 1)
            self.canvas_frame.setMinimumSize(0, 0)
            self.canvas_frame.setMaximumSize(16777215, 16777215)
            self.canvas_frame.show()
            self.aspect_container._resize_child(self.aspect_container.size())
            self.canvas_frame.update_video_layout()

        self._in_fullscreen_dlg = False
        if self.isMaximized():
            self.showMaximized()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self.update()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        
        # Don't hijack typing if user is editing text inputs
        focus_w = QApplication.focusWidget()
        if focus_w and isinstance(focus_w, (QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox)):
            super().keyPressEvent(event)
            return

        if key == Qt.Key_Space:
            self.play_pause_toggle()
            event.accept()
        elif key == Qt.Key_S and not mods:
            self.split_video()
            event.accept()
        elif key == Qt.Key_C and not mods:
            self.canvas_frame.set_roi_selection_mode(True)
            event.accept()
        elif key == Qt.Key_F and not mods:
            self.toggle_fullscreen_preview()
            event.accept()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_clip()
            event.accept()
        elif key == Qt.Key_Z and (mods & Qt.ControlModifier):
            self.undo()
            event.accept()
        elif key == Qt.Key_Y and (mods & Qt.ControlModifier):
            self.redo()
            event.accept()
        elif key == Qt.Key_Left:
            pos = max(0.0, self.timeline.get_position() - 0.033)
            self.timeline.set_position(pos)
            self._sync_media_player(pos, force_seek=True)
            event.accept()
        elif key == Qt.Key_Right:
            pos = self.timeline.get_position() + 0.033
            self.timeline.set_position(pos)
            self._sync_media_player(pos, force_seek=True)
            event.accept()
        else:
            super().keyPressEvent(event)

    def generate_auto_subtitles(self):
        if not self.video_track.clips:
            QMessageBox.warning(self, "Warning", "Please add a video clip to the timeline first.")
            return

        if self._sub_worker is not None and self._sub_worker.isRunning():
            QMessageBox.information(self, "Auto Subtitles", "Subtitle generation is already running — please wait for it to finish.")
            return

        from utils.speech_engine import SpeechToTextEngine
        from gui.worker import SubtitleWorker
        from PySide6.QtWidgets import QProgressDialog

        engine = SpeechToTextEngine(self.video_editor.ffmpeg.ffmpeg_path)
        srt_path = self._get_output_path("captions", ".srt", is_temp=True)
        lang = self.sub_lang_combo.currentText()
        trans = self.sub_translate_cb.isChecked()

        progress_dlg = QProgressDialog("✨ Whisper AI Voice Subtitles Generating...\nPlease wait...", None, 0, 0, self)
        progress_dlg.setWindowTitle("Auto Subtitles")
        progress_dlg.setCancelButton(None)
        progress_dlg.setWindowModality(Qt.WindowModal)
        progress_dlg.show()

        m_size = self.sub_model_combo.currentText()
        self._sub_worker = SubtitleWorker(engine, list(self.video_track.clips), lang, trans, srt_path, model_size=m_size)

        def on_subtitles_finished(all_segments, srt_file_path):
            progress_dlg.close()
            self._current_srt_path = srt_file_path
            self._live_subtitles = all_segments
            self.enable_auto_sub_cb.setChecked(True)

            # Reuse the existing subtitle track (matching by type — matching by a
            # different name used to create a duplicate track every project)
            sub_track = next((t for t in self.project.tracks if t.track_type == 'subtitle'), None)
            if not sub_track:
                sub_track = Track("🔤 Subtitles & Text", "subtitle")
                self.project.add_track(sub_track)

            sub_track.clips.clear()
            for seg in all_segments:
                c_dur = max(0.5, seg['end'] - seg['start'])
                c = Clip(self.current_file or "", seg['start'], c_dur, text=seg['text'], clip_type="text")
                sub_track.add_clip(c)

            self.timeline.load_project(self.project, maintain_position=True)

            if all_segments:
                self.canvas_frame.set_live_subtitle_overlay(all_segments[0]['text'], 32, 'yellow', True)

            preview_sample = " | ".join(seg['text'] for seg in all_segments[:3]) if all_segments else "No voice detected"
            QMessageBox.information(
                self,
                "Auto Subtitles Generated",
                f"Voice subtitles generated successfully!\n\nTimed Subtitle Lines: {len(all_segments)}\nPreview Sample: '{preview_sample}'"
            )
            self._update_live_text_preview()

        def on_subtitles_error(err_msg):
            progress_dlg.close()
            QMessageBox.critical(self, "Error", f"Failed to generate subtitles: {err_msg}")

        self._sub_worker.finished.connect(on_subtitles_finished)
        self._sub_worker.error.connect(on_subtitles_error)
        self._sub_worker.start()

    def _update_live_text_preview(self):
        txt = self.text_input.text().strip()
        vis = self.enable_text_cb.isChecked()
        fsz = self.font_size_spin.value()
        col = self.font_color_combo.currentText()
        bg_style = getattr(self, 'text_bg_style_combo', None) and self.text_bg_style_combo.currentText() or 'Transparent (Clean Glow)'
        self.canvas_frame.set_live_title_overlay(txt, fsz, col, bg_style, vis)

    def add_text_title_to_timeline(self):
        txt = self.text_input.text().strip()
        if not txt:
            QMessageBox.warning(self, "Warning", "Please enter a title / text overlay in the box above first.")
            return

        self._save_undo_state()
        playhead_time = self.timeline.get_position()

        # Find or create Subtitle/Text track
        sub_track = None
        for t in self.project.tracks:
            if t.track_type == 'subtitle' or t.name == "🔤 Subtitles":
                sub_track = t
                break

        if not sub_track:
            sub_track = Track("🔤 Subtitles", "subtitle")
            self.project.add_track(sub_track)

        c_dur = 4.0 # default duration 4 seconds
        new_clip = Clip(self.current_file or "", playhead_time, c_dur, text=txt)
        sub_track.add_clip(new_clip)

        self.timeline.load_project(self.project, maintain_position=True)
        self.enable_text_cb.setChecked(True)
        self._update_live_text_preview()
        QMessageBox.information(self, "Text Title Added", f"Added Text Title '{txt}' to timeline at {playhead_time:.2f}s!")

    def toggle_left_sidebar(self):
        if self.media_bin.isVisible():
            self.media_bin.hide()
            self.toggle_left_action.setText("▶ Media Library")
        else:
            self.media_bin.show()
            self.toggle_left_action.setText("◀ Media Library")

    def toggle_right_sidebar(self):
        if self.settings_panel.isVisible():
            self.settings_panel.hide()
            self.toggle_right_action.setText("◀ Tools Panel")
        else:
            self.settings_panel.show()
            self.toggle_right_action.setText("Tools Panel ▶")

    def add_video_track(self):
        self._save_undo_state()
        idx = len([t for t in self.project.tracks if t.track_type == 'video']) + 1
        t = Track(f"Video {idx}", "video")
        self.project.add_track(t)
        self.timeline.load_project(self.project, maintain_position=True)

    def add_audio_track(self):
        self._save_undo_state()
        idx = len([t for t in self.project.tracks if t.track_type == 'audio']) + 1
        t = Track(f"Audio {idx}", "audio")
        self.project.add_track(t)
        self.timeline.load_project(self.project, maintain_position=True)

    def _on_speed_changed(self, speed_str: str):
        val_str = speed_str.split('x')[0].strip()
        try:
            sp = float(val_str)
        except ValueError:
            sp = 1.0
        if self.video_track.clips:
            self._save_undo_state()
            self.video_track.clips[0].speed = sp
            self.timeline.load_project(self.project, maintain_position=True)

    def add_keyframe_at_playhead(self):
        if not self.video_track.clips:
            return
        playhead_time = self.timeline.get_position()
        clip = self.video_track.clips[0]
        from editors.keyframe_editor import Keyframe
        zoom_val = self.kf_zoom_spin.value()
        clip.keyframes.append(Keyframe(playhead_time, 0.0, 0.0, zoom_val, 1.0))
        QMessageBox.information(self, "Keyframe Added", f"Keyframe added at {playhead_time:.2f}s with Zoom {zoom_val:.1f}x")

    def add_media_from_bin(self, file_path: str):
        if not os.path.exists(file_path):
            self.media_bin.refresh_library()
            return

        self._save_undo_state()
        if file_path not in self.media_bin.media_paths:
            self.media_bin.media_paths.append(file_path)
            self.media_bin.refresh_library()

        ext = Path(file_path).suffix.lower()
        is_audio = ext in ['.mp3', '.wav', '.aac', '.m4a', '.flac']
        is_image = ext in ['.png', '.jpg', '.jpeg', '.bmp', '.webp']

        info = self.video_editor.get_video_info(file_path)
        playhead_time = self.timeline.get_position()

        if is_audio:
            a_tr = self.audio_track
            end_t = max((c.end_time for c in a_tr.clips), default=playhead_time)
            a_dur = info.get('duration', 10.0)
            a_tr.add_clip(Clip(file_path, end_t, a_dur, clip_type="audio"))
            self.timeline.load_project(self.project, maintain_position=True)
            self.statusBar().showMessage(f"🎵 Added audio '{Path(file_path).name}' to Audio Track", 4000)
            return

        if is_image:
            img_dur = 5.0
            self.overlay_track.add_clip(Clip(file_path, playhead_time, img_dur, clip_type="image"))
            self.timeline.load_project(self.project, maintain_position=True)
            self._sync_media_player(playhead_time, force_seek=True)
            self.statusBar().showMessage(f"🖼️ Added image overlay '{Path(file_path).name}' at {playhead_time:.2f}s", 4000)
            return

        w = info.get('width', 1920)
        h = info.get('height', 1080)
        if w > 0 and h > 0:
            if h > w * 1.2:
                self.aspect_ratio_combo.setCurrentText('9:16')
            elif w > h * 1.2:
                self.aspect_ratio_combo.setCurrentText('16:9')
            elif abs(w - h) < 50:
                self.aspect_ratio_combo.setCurrentText('1:1')
            self.canvas_frame.set_media_size(w, h)

        self.preview_label.setText(f"{Path(file_path).name}  |  {w}x{h}  |  {info.get('fps', 0):.1f} fps")

        duration = info.get('duration', 5.0)
        end_time = max((clip.end_time for clip in self.video_track.clips), default=0.0)
        self.video_track.add_clip(Clip(file_path, end_time, duration))
        self.timeline.load_project(self.project, maintain_position=True)
        self.statusBar().showMessage(f"🎬 Added '{Path(file_path).name}' to timeline", 4000)

        # Background 540p proxy for smooth preview scrubbing (export uses the original)
        if hasattr(self, 'proxy_engine'):
            self.proxy_engine.generate_proxy_async(file_path)

        self.current_file = file_path
        self._current_video_source = None  # force proxy-aware source re-resolve
        self.media_player.setSource(QUrl.fromLocalFile(file_path))

        self._sync_media_player(end_time, force_seek=True)
        self.update_time_label()

    def _on_canvas_zoom_changed(self, text: str):
        mapping = {
            'Fit (Auto)': 1.0,
            '50%': 0.5,
            '75%': 0.75,
            '100% (1:1)': 1.0,
            '150%': 1.5,
            '200%': 2.0,
            '300%': 3.0,
            '400%': 4.0
        }
        scale = mapping.get(text, 1.0)
        self.canvas_frame.set_zoom_level(scale)

    def show_hardware_info(self):
        hw = self.hardware
        gpu = hw.gpu_info

        info = f"CPU: {hw.cpu_cores} cores | RAM: {hw.ram_gb:.1f}GB"
        if gpu['available']:
            info += f" | GPU: {gpu['name']}"
        else:
            info += " | GPU: None (CPU mode)"

        self.hw_label.setText(info)

    def _on_wm_region_selected(self, x: int, y: int, w: int, h: int):
        self.enable_wm_cb.setChecked(True)
        self.wm_x_spin.blockSignals(True)
        self.wm_y_spin.blockSignals(True)
        self.wm_w_spin.blockSignals(True)
        self.wm_h_spin.blockSignals(True)

        self.wm_x_spin.setValue(x)
        self.wm_y_spin.setValue(y)
        self.wm_w_spin.setValue(w)
        self.wm_h_spin.setValue(h)

        self.wm_x_spin.blockSignals(False)
        self.wm_y_spin.blockSignals(False)
        self.wm_w_spin.blockSignals(False)
        self.wm_h_spin.blockSignals(False)
        self._update_wm_overlay()

    def _update_wm_overlay(self):
        enabled = self.enable_wm_cb.isChecked()
        if enabled:
            x = self.wm_x_spin.value()
            y = self.wm_y_spin.value()
            w = self.wm_w_spin.value()
            h = self.wm_h_spin.value()
            self.canvas_frame.update_roi_overlay(x, y, w, h, visible=True)
        else:
            self.canvas_frame.update_roi_overlay(0, 0, 0, 0, visible=False)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Media File",
            "",
            "Media Files (*.mp4 *.mov *.avi *.mkv *.webm *.png *.jpg *.jpeg *.bmp *.webp);;Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;Image Files (*.png *.jpg *.jpeg *.bmp *.webp)"
        )

        if file_path:
            self.add_media_from_bin(file_path)

    def _update_live_filter_preview(self):
        if not hasattr(self, 'effect_stack'):
            from editors.effect_stack import EffectStack
            self.effect_stack = EffectStack()

        # 1. Update EffectStack parameters directly from sliders
        b = getattr(self, 'bright_slider', None) and self.bright_slider.value() or 0.0
        c = getattr(self, 'contrast_slider', None) and self.contrast_slider.value() or 0.0
        s = getattr(self, 'sat_slider', None) and self.sat_slider.value() or 0.0
        t = getattr(self, 'temp_slider', None) and self.temp_slider.value() or 0.0
        e = getattr(self, 'exp_slider', None) and self.exp_slider.value() or 0.0
        dn = getattr(self, 'denoise_slider', None) and self.denoise_slider.value() or 0.0
        sh = getattr(self, 'sharp_slider', None) and self.sharp_slider.value() or 0.0

        self.effect_stack.brightness = float(b)
        self.effect_stack.contrast = float(c)
        self.effect_stack.saturation = float(s)
        self.effect_stack.temperature = float(t)
        self.effect_stack.exposure = float(e)
        self.effect_stack.denoise = float(dn)
        self.effect_stack.sharpness = float(sh)

        # 2. Collect Magic AI Auto-Enhance & Super-Resolution filters
        proc_filters = []
        ai_strength = (self.ai_strength_slider.value() / 100.0) if hasattr(self, 'ai_strength_slider') else 0.0
        ai_mode = self.ai_model_combo.currentText() if hasattr(self, 'ai_model_combo') else 'real_life'
        upscale_target = self.ai_upscale_combo.currentText() if hasattr(self, 'ai_upscale_combo') else '2160p 4K (Ultra HD)'

        if ai_strength > 0.0:
            ai_str = self.filter_editor.get_auto_enhance_filter_string(ai_strength, ai_strength, ai_strength, upscale_target, mode=ai_mode)
            if ai_str:
                proc_filters.append(ai_str)

        self.effect_stack.preset_filters = proc_filters

        # 3. Store unified filtergraph for export
        self._active_live_filter_str = self.effect_stack.to_ffmpeg_vf()

        # 4. Canvas tint overlay
        self.canvas_frame.apply_live_color_tuning(b, c, s, t, e, dn, sh)

        # 5. Debounced heavy render — decoding a frame per slider tick froze the UI
        self._preview_debounce.start()

    def _render_live_preview_now(self):
        """The expensive half of the live preview: decode a frame and shade it."""
        if not self.current_file:
            return
        es = getattr(self, 'effect_stack', None)
        if es is None:
            return
        from editors.unified_renderer import UnifiedRenderer
        pos_sec = self.timeline.get_position()
        preview_src = self.proxy_engine.get_preview_path(self.current_file) if hasattr(self, 'proxy_engine') else self.current_file
        pix, raw_frame = UnifiedRenderer.render_preview_frame(preview_src, pos_sec, es)
        has_active_effects = bool(
            es.brightness or es.contrast or es.saturation or es.temperature
            or es.exposure or es.denoise or es.sharpness or es.preset_filters
        )
        self.canvas_frame.set_image_overlay(pix if (has_active_effects and pix is not None) else None)
        if hasattr(self, 'color_scopes_widget') and raw_frame is not None:
            self.color_scopes_widget.update_frame(raw_frame)

    def run_magic_ai_auto_enhance(self):
        """1-Click Magic AI Auto-Enhance & Ultra-Master Engine."""
        self.contrast_slider.setValue(15)
        self.exp_slider.setValue(10)
        self.sharp_slider.setValue(0)
        self.denoise_slider.setValue(0)
        if hasattr(self, 'ai_model_combo'):
            self.ai_model_combo.setCurrentText('💎 Heavy-Duty Studio Mode (Maximum Quality)')
        if hasattr(self, 'ai_strength_slider'):
            self.ai_strength_slider.setValue(85)
        if hasattr(self, 'ai_upscale_combo'):
            self.ai_upscale_combo.setCurrentText('2160p 4K (Ultra HD)')
        self._update_live_filter_preview()
        QMessageBox.information(
            self,
            "Magic AI Auto-Enhance",
            "🪄 1-Click Studio 95%+ Quality Enhancement Engaged!\n\n"
            "• Contrast Adaptive Dual-Kernel Sharpening + HDR S-Curve Active!\n"
            "• 4K Ultra HD Super-Resolution High-Precision AI Active!"
        )

    def _on_aspect_ratio_changed(self, text):
        ratios = {
            '16:9': 16/9,
            '9:16': 9/16,
            '1:1': 1/1,
            '4:5': 4/5,
            '21:9': 21/9
        }
        self.aspect_container.set_aspect_ratio(ratios.get(text, 16/9))

    def delete_selected_clip(self):
        items = self.timeline.timeline_scene.selectedItems()
        if not items:
            QMessageBox.warning(self, "Error", "No clip selected to delete.")
            return
            
        self._save_undo_state()
        item = items[0]
        track = self.project.tracks[item.track_idx]
        if item.clip in track.clips:
            track.clips.remove(item.clip)
        
        self._last_active_clip = None
        self.timeline.load_project(self.project, maintain_position=True)
        self._sync_media_player(self.timeline.get_position(), force_seek=True)

    def split_video(self):
        if not self.current_file and not self.video_track.clips:
            QMessageBox.warning(self, "Error", "Please open a video first")
            return

        playhead_time = self.timeline.get_position()
        
        if not self.timeline.timeline_scene.selectedItems():
            QMessageBox.warning(self, "Error", "Please click on a clip in the timeline to select it first.")
            return
            
        self._save_undo_state()
        self._last_active_clip = None
        self.timeline.timeline_scene.split_selected_clip(playhead_time)
        self._sync_media_player(playhead_time, force_seek=True)

    def export_video(self):
        if not self.current_file and not self.video_track.clips:
            QMessageBox.warning(self, "Error", "Please open a video first")
            return

        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Export", "An export is already running — please wait for it to finish or cancel it first.")
            return

        format_ext = f".{self.format_combo.currentText().lower()}"
        is_audio_only = (format_ext == '.mp3')

        # Interactive File Save Dialog so user chooses exact destination folder
        default_dir = os.path.join(os.path.expanduser("~"), "Videos")
        os.makedirs(default_dir, exist_ok=True)
        raw_base = Path(self.current_file).stem if self.current_file else "project"
        base_clean = "".join(c for c in raw_base if c.isalnum() or c in (' ', '_', '-')).strip() or "exported_video"
        default_filename = os.path.join(default_dir, f"{base_clean}_enhanced{format_ext}")

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Exported Video As...",
            default_filename,
            f"Video Files (*{format_ext});;All Files (*.*)"
        )
        if not output_path:
            return  # User cancelled dialog

        # Make sure the EffectStack reflects the current slider state
        self._update_live_filter_preview()

        # Snapshot ALL UI + timeline state into plain data now, on the GUI
        # thread — the worker thread must never read Qt widgets directly.
        opts = self._snapshot_export_options(is_audio_only)
        opts['filtered_temp'] = self._get_output_path("filtered", ".mp4", is_temp=True)
        opts['audio_temp'] = self._get_output_path("audio_mod", ".mp4", is_temp=True)

        self.progress_dialog = QProgressDialog("Exporting video...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()

        self.worker = FFmpegWorker(
            self._run_export_sequence,
            opts, output_path,
            total_duration=self.project.get_duration(),
            editors=[self.video_editor, self.filter_editor, self.audio_editor]
        )

        def _update_progress_dialog(pct, msg):
            self.progress_dialog.setLabelText(msg)
            self.progress_dialog.setValue(pct)

        self.worker.status_updated.connect(_update_progress_dialog)

        def _clean_up_temps():
            for f in list(self._temp_files):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except OSError:
                    pass
            self._temp_files.clear()

        def on_finished(temp_files):
            self.progress_dialog.close()
            _clean_up_temps()
            # Auto-Highlight Exported Video in Windows File Explorer
            if os.path.exists(output_path):
                if os.name == 'nt':
                    try:
                        subprocess.Popen(['explorer', '/select,', os.path.abspath(output_path)])
                    except Exception:
                        pass
                QMessageBox.information(self, "Export Complete! 🎉", f"Video exported successfully!\n\nLocation:\n{output_path}")

        def on_error(err):
            self.progress_dialog.close()
            _clean_up_temps()
            if "Cancelled by user" in err:
                return
            QMessageBox.critical(self, "Export Error", f"Export failed: {err}")

        self.worker.finished.connect(on_finished)
        self.worker.error.connect(on_error)
        self.progress_dialog.canceled.connect(self.worker.cancel)
        self.worker.start()

    def _track_is_active(self, track) -> bool:
        """Mute/Solo resolution: any soloed track silences all non-soloed ones."""
        if track is None:
            return False
        if track.is_muted:
            return False
        any_solo = any(t.is_solo for t in self.project.tracks)
        if any_solo and not track.is_solo:
            return False
        return True

    def _snapshot_export_options(self, is_audio_only: bool) -> dict:
        """Copy every piece of UI + timeline state the export needs into plain
        data, so the worker thread never touches Qt objects."""
        video_clips = []
        if self._track_is_active(self.video_track):
            for c in self.video_track.clips:
                video_clips.append({
                    'path': c.file_path,
                    'start_time': float(c.start_time),
                    'source_start': float(c.source_start),
                    'duration': float(c.duration),
                    'speed': float(getattr(c, 'speed', 1.0) or 1.0),
                    'volume': float(getattr(c, 'volume', 1.0)),
                    'is_muted': bool(getattr(c, 'is_muted', False)),
                })

        audio_clips = []
        for t in self.project.tracks:
            if t.track_type != 'audio' or not self._track_is_active(t):
                continue
            for c in t.clips:
                if c.file_path and os.path.exists(c.file_path):
                    audio_clips.append({
                        'path': c.file_path,
                        'start': float(c.start_time),
                        'source_start': float(c.source_start),
                        'duration': float(c.duration),
                        'volume': float(getattr(c, 'volume', 1.0)),
                    })

        overlay_clips = []
        text_clips = []
        for t in self.project.tracks:
            if t.track_type == 'overlay' and self._track_is_active(t):
                for c in t.clips:
                    if c.file_path and os.path.exists(c.file_path):
                        overlay_clips.append({
                            'path': c.file_path,
                            'start': float(c.start_time),
                            'end': float(c.end_time),
                        })
            elif t.track_type == 'subtitle' and self._track_is_active(t):
                for c in t.clips:
                    txt = getattr(c, 'text', '')
                    if txt:
                        text_clips.append({
                            'text': txt,
                            'start': float(c.start_time),
                            'end': float(c.end_time),
                        })

        effect_vf = ''
        if hasattr(self, 'effect_stack'):
            effect_vf = self.effect_stack.to_ffmpeg_vf() or ''

        return {
            'is_audio_only': is_audio_only,
            'resolution': self.res_combo.currentText().lower(),
            # Use the detected hardware encoder — the old code read a config key
            # that never existed, silently forcing CPU-only libx264 exports.
            'codec': self.video_editor.settings.get('encoder', 'libx264'),
            'volume': self.volume_slider.value(),
            'voice_boost': self.voice_boost_btn.isChecked(),
            'wm_enabled': self.enable_wm_cb.isChecked(),
            'wm_rect': (self.wm_x_spin.value(), self.wm_y_spin.value(),
                        self.wm_w_spin.value(), self.wm_h_spin.value()),
            'title_enabled': self.enable_text_cb.isChecked(),
            'title_text': self.text_input.text().strip(),
            'title_font_size': self.font_size_spin.value(),
            'title_color': self.font_color_combo.currentText(),
            'auto_sub': hasattr(self, 'enable_auto_sub_cb') and self.enable_auto_sub_cb.isChecked(),
            'srt_path': getattr(self, '_current_srt_path', None),
            'effect_vf': effect_vf,
            'playhead': self.timeline.get_position(),
            'video_clips': video_clips,
            'audio_clips': audio_clips,
            'overlay_clips': overlay_clips,
            'text_clips': text_clips,
        }

    def _on_clip_volume_changed(self, val):
        self.clip_volume_val_label.setText(f"{val}%")
        items = self.timeline.timeline_scene.selectedItems()
        if items and hasattr(items[0], 'clip'):
            clip = items[0].clip
            clip.volume = val / 100.0
            clip.is_muted = (val == 0)

    def _on_clip_mute_toggled(self):
        items = self.timeline.timeline_scene.selectedItems()
        if items and hasattr(items[0], 'clip'):
            clip = items[0].clip
            clip.is_muted = not getattr(clip, 'is_muted', False)
            if clip.is_muted:
                self.clip_mute_btn.setText("🔇 Muted Clip Audio (ON)")
                self.clip_mute_btn.setStyleSheet("background: #d9534f; color: white;")
            else:
                self.clip_mute_btn.setText("🔊 Clip Audio Active (OFF)")
                self.clip_mute_btn.setStyleSheet("")

    def _toggle_move_clip_mode(self):
        is_on = self.drag_clip_mode_btn.isChecked()
        self.timeline.timeline_scene.drag_mode_enabled = is_on
        if is_on:
            self.drag_clip_mode_btn.setText("🖐️ Move Clip Mode: ON")
            self.drag_clip_mode_btn.setStyleSheet("background: #00b386; color: white; border-color: #00ffcc;")
        else:
            self.drag_clip_mode_btn.setText("🖐️ Move Clip Mode: OFF")
            self.drag_clip_mode_btn.setStyleSheet("")

    def _run_export_sequence(self, opts, output_path):
        """Runs on the FFmpegWorker thread. Reads ONLY the plain-data `opts`
        snapshot — never live Qt widgets or the live project."""
        filtered_temp = opts['filtered_temp']
        audio_temp = opts['audio_temp']
        self._temp_files.extend([filtered_temp, audio_temp])

        video_clips = opts['video_clips']
        if not video_clips:
            raise RuntimeError("No video clips to export (is the video track muted?)")

        resolution = opts['resolution']
        codec = opts['codec']
        is_audio_only = opts['is_audio_only']

        format_ext = Path(output_path).suffix.lower()
        is_image_export = format_ext in ['.png', '.jpg', '.jpeg', '.bmp', '.webp']

        # Resolve ONE concrete target geometry up front so every rendered piece
        # (clips AND black gap fillers) matches exactly for lossless concat.
        # Previously 'Source' resolution made gaps default to 1920x1080@30 while
        # clips kept their own size/fps — corrupting the concat output.
        first_info = self.video_editor.get_video_info(video_clips[0]['path'])
        target_fps = float(first_info.get('fps', 30.0) or 30.0)
        if resolution in ('source', 'auto', 'original', ''):
            tw = int(first_info.get('width', 1920) or 1920)
            th = int(first_info.get('height', 1080) or 1080)
        else:
            tw, th = self.video_editor._parse_resolution(resolution)
        tw -= tw % 2
        th -= th % 2
        res_str = f"{tw}x{th}"

        if is_image_export:
            playhead_time = opts['playhead']
            active = None
            for c in video_clips:
                footprint = c['duration'] / max(0.1, c['speed'])
                if c['start_time'] <= playhead_time <= c['start_time'] + footprint:
                    active = c
                    break
            if not active:
                active = video_clips[0]

            source_time = active['source_start'] + max(0.0, (playhead_time - active['start_time'])) * active['speed']
            input_file = active['path']

            img_filters = []
            if opts['wm_enabled']:
                x, y, w, h = opts['wm_rect']
                info = self.video_editor.get_video_info(input_file)
                img_filters.append(self.filter_editor.get_delogo_filter_string(
                    x, y, w, h, info.get('width', 0), info.get('height', 0)))
            if opts['effect_vf']:
                img_filters.append(opts['effect_vf'])

            self.video_editor.render_image_frame(
                input_file, output_path, start_time=source_time,
                filter_str=",".join(img_filters), resolution=resolution)
            return self._temp_files

        # 1. Render all clips individually and fill timeline gaps with black
        rendered_clips = []
        current_timeline_pos = 0.0

        for i, clip in enumerate(video_clips):
            if clip['start_time'] > current_timeline_pos + 0.05:
                gap_duration = clip['start_time'] - current_timeline_pos
                gap_temp = self._get_output_path(f"gap_{i}", ".mp4", is_temp=True)
                self._temp_files.append(gap_temp)
                self.video_editor.generate_black_video(gap_temp, gap_duration, res_str, codec, fps=target_fps)
                rendered_clips.append(gap_temp)

            # Watermark removal happens HERE, per clip, at the SOURCE resolution —
            # the rectangle was selected on the original frame, so applying it
            # after scaling (as before) pointed at the wrong pixels and could
            # fall outside the frame entirely.
            clip_extra_vf = ""
            if opts['wm_enabled']:
                x, y, w, h = opts['wm_rect']
                src_info = self.video_editor.get_video_info(clip['path'])
                clip_extra_vf = self.filter_editor.get_delogo_filter_string(
                    x, y, w, h, src_info.get('width', 0), src_info.get('height', 0))

            clip_temp = self._get_output_path(f"clip_{i}", ".mp4", is_temp=True)
            self._temp_files.append(clip_temp)
            self.video_editor.render_video(
                clip['path'],
                clip_temp,
                start_time=clip['source_start'],
                end_time=clip['source_start'] + clip['duration'],
                resolution=res_str,
                fps=target_fps,
                codec=codec,
                speed=clip['speed'],
                volume=clip['volume'],
                is_muted=clip['is_muted'],
                extra_vf=clip_extra_vf
            )
            rendered_clips.append(clip_temp)
            # Timeline footprint shrinks/grows with speed
            current_timeline_pos = clip['start_time'] + clip['duration'] / max(0.1, clip['speed'])

        # 2. Concat if multiple pieces
        if len(rendered_clips) > 1:
            concat_list = self._get_output_path("concat_list", ".txt", is_temp=True)
            self._temp_files.append(concat_list)

            with open(concat_list, "w", encoding="utf-8") as f:
                for rc in rendered_clips:
                    safe_path = os.path.abspath(rc).replace('\\', '/').replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            concatenated_temp = self._get_output_path("concatenated", ".mp4", is_temp=True)
            self._temp_files.append(concatenated_temp)
            self.video_editor.concat_clips(concat_list, concatenated_temp)
            current_source = concatenated_temp
        else:
            current_source = rendered_clips[0]

        # 3. Single filter pass: color grade → title → timeline text → subtitles
        # (watermark removal already happened per-clip at source resolution)
        if not is_audio_only:
            proc_filters = []

            if opts['effect_vf']:
                proc_filters.append(opts['effect_vf'])

            if opts['title_enabled'] and opts['title_text']:
                dt_str = self.filter_editor.get_drawtext_filter_string(
                    opts['title_text'], opts['title_font_size'], opts['title_color'])
                if dt_str:
                    proc_filters.append(dt_str)

            # Timeline text clips (titles/captions on the subtitle track) are now
            # burned into the export with their real timing windows.
            for tc in opts['text_clips']:
                dt = self.filter_editor.get_drawtext_filter_string(tc['text'], 30, 'white')
                if dt:
                    proc_filters.append(f"{dt}:enable='between(t,{tc['start']:.3f},{tc['end']:.3f})'")

            if opts['auto_sub']:
                srt_p = opts['srt_path']
                if not srt_p or not os.path.exists(srt_p):
                    from utils.speech_engine import SpeechToTextEngine
                    engine = SpeechToTextEngine(self.video_editor.ffmpeg.ffmpeg_path)
                    srt_p = self._get_output_path("captions", ".srt", is_temp=True)
                    engine.generate_subtitles(current_source, srt_p)
                sub_filter = self.filter_editor.get_subtitle_filter_string(srt_p)
                if sub_filter:
                    proc_filters.append(sub_filter)

            if proc_filters:
                combined_filter = ",".join(proc_filters)
                self.video_editor.apply_filter(current_source, filtered_temp, combined_filter, resolution)
                current_source = filtered_temp

            # 3b. Composite image/PiP overlay clips (needs extra inputs → own pass).
            # These previously showed in the preview but never exported at all.
            if opts['overlay_clips']:
                overlay_temp = self._get_output_path("overlaid", ".mp4", is_temp=True)
                self._temp_files.append(overlay_temp)
                cmd = self.video_editor.ffmpeg.build_overlay_pass(
                    current_source, opts['overlay_clips'], overlay_temp, tw, th)
                self.video_editor._execute(cmd)
                current_source = overlay_temp

        # 4. Mix ALL audio-track clips at their true timeline positions.
        # The old code mixed only the first clip, always starting at 0:00.
        if opts['audio_clips'] and not is_audio_only:
            mixed_temp = self._get_output_path("audio_mixed", ".mp4", is_temp=True)
            self._temp_files.append(mixed_temp)
            cmd = self.video_editor.ffmpeg.build_audio_mix_timeline(
                current_source, opts['audio_clips'], mixed_temp)
            self.video_editor._execute(cmd)
            current_source = mixed_temp

        # 5. Master audio adjustments / delivery
        volume = opts['volume']
        if is_audio_only:
            if opts['audio_clips']:
                mixed_temp = self._get_output_path("audio_mixed", ".mp4", is_temp=True)
                self._temp_files.append(mixed_temp)
                cmd = self.video_editor.ffmpeg.build_audio_mix_timeline(
                    current_source, opts['audio_clips'], mixed_temp)
                self.video_editor._execute(cmd)
                current_source = mixed_temp
            if volume != 100:
                # Never read+write the same file in one FFmpeg call (it corrupts output)
                tmp_mp3 = self._get_output_path("audio_only", ".mp3", is_temp=True)
                self._temp_files.append(tmp_mp3)
                self.audio_editor.extract_audio(current_source, tmp_mp3)
                self.audio_editor.adjust_volume(tmp_mp3, output_path, volume / 100.0)
            else:
                self.audio_editor.extract_audio(current_source, output_path)
        else:
            if volume != 100 or opts['voice_boost']:
                if opts['voice_boost']:
                    self.audio_editor.voice_boost(current_source, audio_temp, voice_gain=6.0, music_gain=0.5)
                    current_source = audio_temp
                elif volume != 100:
                    self.audio_editor.adjust_volume(current_source, audio_temp, volume / 100.0)
                    current_source = audio_temp

            import shutil
            shutil.copyfile(current_source, output_path)

        return self._temp_files

    def _get_output_path(self, suffix: str, ext: str = ".mp4", is_temp: bool = True) -> str:
        if is_temp:
            dir_path = self.video_editor.temp_dir
            base = "temp_render"
        else:
            dir_path = os.getcwd()
            raw_base = Path(self.current_file).stem if self.current_file else "project"
            base = "".join(c for c in raw_base if c.isalnum() or c in (' ', '_', '-')).strip()
            if not base:
                base = "exported_video"
            
        out_path = os.path.join(dir_path, f"{base}_{suffix}{ext}")
        counter = 1
        while os.path.exists(out_path):
            out_path = os.path.join(dir_path, f"{base}_{suffix}_{counter}{ext}")
            counter += 1
            
        return out_path

    def _format_time(self, seconds: float) -> str:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def play_preview(self):
        if not self.video_track.clips:
            QMessageBox.warning(self, "Error", "No clips on timeline")
            return
        if self.playback_timer.isActive():
            self.stop_preview()
        else:
            if self.timeline.get_position() >= self.project.get_duration():
                self.timeline.set_position(0.0)
                self._sync_media_player(0.0, force_seek=True)
            self.playback_timer.start(33)
            self.media_player.play()

    def play_pause_toggle(self):
        self.play_preview()

    def stop_preview(self):
        self.playback_timer.stop()
        self.media_player.pause()
        if hasattr(self, 'timeline_audio_player'):
            self.timeline_audio_player.pause()

    def _on_duration_changed(self, duration):
        pass

    def _on_player_position_changed(self, position_ms: int):
        position_sec = position_ms / 1000.0
        
        if hasattr(self, 'timeline') and self.timeline and self.playback_timer.isActive():
            self.timeline.set_position(position_sec)
            self.update_time_label()

        if hasattr(self, '_live_subtitles') and self._live_subtitles and hasattr(self, 'enable_auto_sub_cb') and self.enable_auto_sub_cb.isChecked():
            current_sub_text = ""
            for seg in self._live_subtitles:
                if seg['start'] <= position_sec <= seg['end']:
                    current_sub_text = seg['text']
                    break
            bg_style = getattr(self, 'text_bg_style_combo', None) and self.text_bg_style_combo.currentText() or 'Transparent (Clean Glow)'
            col = self.font_color_combo.currentText()
            self.canvas_frame.set_live_subtitle_overlay(current_sub_text, 28, col, bg_style, bool(current_sub_text))
        else:
            self.canvas_frame.set_live_subtitle_overlay("", 28, 'yellow', 'Transparent (Clean Glow)', False)

    def _on_timeline_scrub(self, position_sec):
        self._sync_media_player(position_sec, force_seek=True)
        self.update_time_label()

    def _sync_media_player(self, timeline_time, force_seek=False):
        # 1. Image / PiP Overlay Layer Lookup (honors track mute/solo)
        active_overlay_clip = None
        if getattr(self, 'overlay_track', None) is not None and self.overlay_track.clips and self._track_is_active(self.overlay_track):
            for c in self.overlay_track.clips:
                if c.start_time <= timeline_time < c.end_time:
                    active_overlay_clip = c
                    break

        if active_overlay_clip:
            self.canvas_frame.set_image_overlay(active_overlay_clip.file_path, True)
        else:
            self.canvas_frame.set_image_overlay(None, False)

        # 2. Main Video Layer Lookup (speed-aware: timeline footprint = duration / speed)
        active_video_clip = None
        if self.video_track and self.video_track.clips and self._track_is_active(self.video_track):
            for clip in self.video_track.clips:
                if clip.start_time <= timeline_time < clip.end_time:
                    active_video_clip = clip
                    break

            if not active_video_clip and timeline_time >= self.project.get_duration():
                active_video_clip = self.video_track.clips[-1]
                timeline_time = active_video_clip.end_time - 0.001

        last_clip = getattr(self, '_last_active_clip', None)
        if active_video_clip is not last_clip:
            force_seek = True
            self._last_active_clip = active_video_clip

        if active_video_clip:
            speed = max(0.1, float(getattr(active_video_clip, 'speed', 1.0) or 1.0))
            target_media_time = active_video_clip.source_start + (timeline_time - active_video_clip.start_time) * speed

            abs_path = os.path.abspath(active_video_clip.file_path)
            # Preview plays through the 540p proxy when ready (export uses the original)
            play_path = self.proxy_engine.get_preview_path(abs_path) if hasattr(self, 'proxy_engine') else abs_path
            if getattr(self, '_current_video_source', None) != play_path:
                self._current_video_source = play_path
                self.current_file = abs_path
                self.media_player.setSource(QUrl.fromLocalFile(play_path))
                force_seek = True

            if abs(self.media_player.playbackRate() - speed) > 0.01:
                self.media_player.setPlaybackRate(speed)

            current_pos = self.media_player.position() / 1000.0
            if force_seek or abs(current_pos - target_media_time) > 1.0:
                self.media_player.setPosition(int(target_media_time * 1000))

            if self.playback_timer.isActive() and self.media_player.playbackState() != QMediaPlayer.PlayingState:
                self.media_player.play()
        else:
            if self.media_player.playbackState() == QMediaPlayer.PlayingState:
                self.media_player.pause()

        # 2b. Audio Track Live Preview Lookup (honors track mute/solo)
        active_audio_clip = None
        if getattr(self, 'audio_track', None) is not None and self.audio_track.clips and self._track_is_active(self.audio_track):
            for clip in self.audio_track.clips:
                if clip.start_time <= timeline_time < clip.end_time:
                    active_audio_clip = clip
                    break

        if active_audio_clip and hasattr(self, 'timeline_audio_player'):
            target_aud_time = active_audio_clip.source_start + (timeline_time - active_audio_clip.start_time)
            aud_path = os.path.abspath(active_audio_clip.file_path)
            if getattr(self, '_current_audio_file', None) != aud_path:
                self._current_audio_file = aud_path
                self.timeline_audio_player.setSource(QUrl.fromLocalFile(aud_path))
            current_aud_pos = self.timeline_audio_player.position() / 1000.0
            if force_seek or abs(current_aud_pos - target_aud_time) > 0.5:
                self.timeline_audio_player.setPosition(int(target_aud_time * 1000))
            if self.playback_timer.isActive() and self.timeline_audio_player.playbackState() != QMediaPlayer.PlayingState:
                self.timeline_audio_player.play()
        else:
            if hasattr(self, 'timeline_audio_player') and self.timeline_audio_player.playbackState() == QMediaPlayer.PlayingState:
                self.timeline_audio_player.pause()

        # 3. Live Subtitles Layer Lookup
        if hasattr(self, '_live_subtitles') and self._live_subtitles and hasattr(self, 'enable_auto_sub_cb') and self.enable_auto_sub_cb.isChecked():
            sub_txt = ""
            for seg in self._live_subtitles:
                if seg['start'] <= timeline_time <= seg['end']:
                    sub_txt = seg['text']
                    break
            bg_style = getattr(self, 'text_bg_style_combo', None) and self.text_bg_style_combo.currentText() or 'Transparent (Clean Glow)'
            col = self.font_color_combo.currentText()
            self.canvas_frame.set_live_subtitle_overlay(sub_txt, 28, col, bg_style, bool(sub_txt))
        else:
            self.canvas_frame.set_live_subtitle_overlay("", 28, 'yellow', 'Transparent (Clean Glow)', False)

    def _playback_tick(self):
        active_clip = getattr(self, '_last_active_clip', None)
        
        if active_clip and self.media_player.playbackState() == QMediaPlayer.PlayingState:
            speed = max(0.1, float(getattr(active_clip, 'speed', 1.0) or 1.0))
            current_media_time = self.media_player.position() / 1000.0
            clip_progress = current_media_time - active_clip.source_start

            if clip_progress < 0:
                clip_progress = 0

            # Media time advances at `speed`× — divide to get timeline progress
            new_time = active_clip.start_time + clip_progress / speed

            if clip_progress >= active_clip.duration:
                new_time = active_clip.end_time
                self.timeline.set_position(new_time)
                self._sync_media_player(new_time, force_seek=True)
            else:
                self.timeline.set_position(new_time)
        else:
            new_time = self.timeline.get_position() + 0.033
            self.timeline.set_position(new_time)
            self._sync_media_player(new_time)
            
        if self.timeline.get_position() >= self.project.get_duration():
            new_time = self.project.get_duration()
            self.stop_preview()
            self.timeline.set_position(new_time)
            self._sync_media_player(new_time, force_seek=False)
            
        self.update_time_label()

    def update_time_label(self):
        pos = self.timeline.get_position()
        tot = self.project.get_duration()
        self.time_label.setText(
            f"Pos: {self._format_time(pos)} / {self._format_time(tot)}"
        )

    def _start_hw_monitor_timer(self):
        from PySide6.QtCore import QTimer
        self.hw_timer = QTimer(self)
        self.hw_timer.setInterval(2000)
        self.hw_timer.timeout.connect(self._update_hw_info)
        self.hw_timer.start()

    def _update_hw_info(self):
        try:
            import psutil
            cpu_pct = psutil.cpu_percent()
            ram_pct = psutil.virtual_memory().percent
            gpu_name = self.hardware.gpu_info.get('name', 'iGPU')
            enc = self.hardware.gpu_info.get('encoder', 'libx264')
            if hasattr(self, 'hw_label'):
                self.hw_label.setText(f"🚀 Active GPU: {gpu_name} ({enc}) | CPU: {cpu_pct:.0f}% | RAM: {ram_pct:.0f}%")
        except Exception:
            pass
