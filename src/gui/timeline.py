from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from pathlib import Path
from core.project import Project, Track, Clip

PIXELS_PER_SECOND = 20
TRACK_HEIGHT = 60
HEADER_WIDTH = 100

MAX_CACHE_SIZE = 200
THUMBNAIL_CACHE = {}

import threading

def _cache_set(key, val):
    if len(THUMBNAIL_CACHE) >= MAX_CACHE_SIZE and key not in THUMBNAIL_CACHE:
        first_key = next(iter(THUMBNAIL_CACHE))
        THUMBNAIL_CACHE.pop(first_key, None)
    THUMBNAIL_CACHE[key] = val

def get_clip_thumbnail(file_path: str):
    if file_path in THUMBNAIL_CACHE:
        val = THUMBNAIL_CACHE[file_path]
        # Worker threads store QImage (QPixmap is not allowed off the GUI thread);
        # convert to QPixmap here, on the GUI thread, on first access.
        if isinstance(val, QImage):
            val = QPixmap.fromImage(val)
            _cache_set(file_path, val)
        return val
        
    ext = Path(file_path).suffix.lower()
    if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.webp']:
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(120, 50, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            _cache_set(file_path, scaled)
            return scaled
    elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        # Run background thread for thumbnail extraction to avoid UI freezing
        if file_path not in THUMBNAIL_CACHE:
            _cache_set(file_path, None)
            def _async_extract():
                try:
                    import subprocess, os, tempfile
                    from utils.ffmpeg_wrapper import FFmpegWrapper
                    ffmpeg_path = FFmpegWrapper().ffmpeg_path
                    temp_img = os.path.join(tempfile.gettempdir(), f"thumb_{abs(hash(file_path))}.jpg")
                    if not os.path.exists(temp_img):
                        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        cmd = [ffmpeg_path, '-ss', '0.5', '-i', file_path, '-vframes', '1', '-s', '120x67', '-y', temp_img]
                        subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=2, creationflags=creationflags)
                    if os.path.exists(temp_img):
                        img = QImage(temp_img)
                        if not img.isNull():
                            _cache_set(file_path, img)
                except Exception:
                    pass
            threading.Thread(target=_async_extract, daemon=True).start()
    return THUMBNAIL_CACHE.get(file_path)

class ClipItem(QGraphicsRectItem):
    def __init__(self, clip: Clip, track_idx: int, scene, track_type: str = "video"):
        super().__init__()
        self.clip = clip
        self.track_idx = track_idx
        self.timeline_scene = scene
        self.track_type = track_type
        
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        
        self._dragging_edge = None
        self._drag_start_x = 0
        self._original_clip_start = 0
        self._original_source_start = 0
        self._original_duration = 0
        
        if track_type == "subtitle":
            self.color = QColor(140, 60, 200, 220) # Purple for subtitles
        elif track_type == "audio":
            self.color = QColor(40, 160, 90, 220) # Emerald green for audio
        else:
            self.color = QColor(60, 100, 180, 220) # Deep blue for video
            
        self.setBrush(QBrush(self.color))
        self.setPen(QPen(Qt.black, 1))
        
        display_text = getattr(clip, 'text', '') or Path(clip.file_path).name
        self.setToolTip(display_text)
        
        self.update_rect()

    def update_rect(self):
        self.setRect(0, 0, self.clip.duration * PIXELS_PER_SECOND, TRACK_HEIGHT - 10)
        self.setPos(HEADER_WIDTH + self.clip.start_time * PIXELS_PER_SECOND, self.track_idx * TRACK_HEIGHT + 5)
        self.update()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        
        if self.track_type == "video" and self.track_idx == 0:
            thumb = get_clip_thumbnail(self.clip.file_path)
            if thumb and not thumb.isNull():
                painter.setOpacity(0.35)
                painter.drawPixmap(self.rect().adjusted(2, 2, -2, -2).toRect(), thumb)
                painter.setOpacity(1.0)

        if self.isSelected():
            self.setPen(QPen(Qt.white, 2))
        else:
            self.setPen(QPen(Qt.black, 1))
            
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        display_text = getattr(self.clip, 'text', '') or Path(self.clip.file_path).name
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(display_text, Qt.ElideRight, int(self.rect().width()) - 10)
        painter.drawText(self.rect().adjusted(5, 2, -5, -2), Qt.AlignLeft | Qt.AlignVCenter, elided)

    def hoverMoveEvent(self, event):
        pos = event.pos()
        rect = self.rect()
        margin = 10
        if pos.x() < margin or pos.x() > rect.width() - margin:
            self.setCursor(Qt.SizeHorCursor)
        else:
            if getattr(self.timeline_scene, 'drag_mode_enabled', False):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        pos = event.pos()
        rect = self.rect()
        margin = 10
        self._target_track_idx = None
        
        if pos.x() < margin:
            self._dragging_edge = 'left'
        elif pos.x() > rect.width() - margin:
            self._dragging_edge = 'right'
        else:
            if getattr(self.timeline_scene, 'drag_mode_enabled', False):
                self._dragging_edge = 'center'
            else:
                self._dragging_edge = None
            
        if self._dragging_edge:
            if self._dragging_edge == 'center':
                self.setCursor(Qt.ClosedHandCursor)
            self._drag_start_x = event.scenePos().x()
            self._original_clip_start = self.clip.start_time
            self._original_source_start = self.clip.source_start
            self._original_duration = self.clip.duration
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_edge:
            dx = event.scenePos().x() - self._drag_start_x
            dt = dx / PIXELS_PER_SECOND
            
            # Vertical Y position to target track index
            mouse_y = event.scenePos().y()
            if self.timeline_scene.project and self.timeline_scene.project.tracks:
                num_tracks = len(self.timeline_scene.project.tracks)
                target_idx = int(mouse_y // TRACK_HEIGHT)
                target_idx = max(0, min(num_tracks - 1, target_idx))
                self._target_track_idx = target_idx

            # Find magnetic snap targets across timeline
            snap_targets = [0.0]
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                snap_targets.append(v.get_position())
                
            if self.timeline_scene.project:
                for tr in self.timeline_scene.project.tracks:
                    for c in tr.clips:
                        if c is not self.clip:
                            snap_targets.append(c.start_time)
                            snap_targets.append(c.end_time)

            snap_threshold = 0.25 # seconds (magnetic snapping range)
            
            if self._dragging_edge == 'left':
                dt = max(-self._original_source_start, dt)
                dt = min(self._original_duration - 0.1, dt)
                
                target_start = self._original_clip_start + dt
                best_snap = None
                for st in snap_targets:
                    if abs(target_start - st) < snap_threshold:
                        best_snap = st
                        break
                if best_snap is not None:
                    target_start = best_snap
                    
                dt_final = target_start - self._original_clip_start
                self.clip.start_time = target_start
                self.clip.source_start = max(0.0, self._original_source_start + dt_final)
                self.clip.duration = max(0.1, self._original_duration - dt_final)
                
            elif self._dragging_edge == 'right':
                dt = max(-self._original_duration + 0.1, dt)
                target_end = self._original_clip_start + self._original_duration + dt
                best_snap = None
                for st in snap_targets:
                    if abs(target_end - st) < snap_threshold:
                        best_snap = st
                        break
                if best_snap is not None:
                    target_end = best_snap
                    
                self.clip.duration = max(0.1, target_end - self.clip.start_time)
                
            elif self._dragging_edge == 'center':
                new_start = max(0.0, self._original_clip_start + dt)
                best_snap = None
                for st in snap_targets:
                    if abs(new_start - st) < snap_threshold:
                        best_snap = st
                        break
                    target_end = new_start + self.clip.duration
                    if abs(target_end - st) < snap_threshold:
                        best_snap = st - self.clip.duration
                        break
                if best_snap is not None:
                    new_start = max(0.0, best_snap)
                    
                self.clip.start_time = new_start
                
            self.update_rect()
            event.accept()
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event):
        if self._dragging_edge:
            if self._dragging_edge == 'center':
                self.setCursor(Qt.OpenHandCursor)
            self._dragging_edge = None
            
            # Vertical track transfer
            if hasattr(self, '_target_track_idx') and self._target_track_idx is not None and self._target_track_idx != self.track_idx:
                if self.timeline_scene.project and self._target_track_idx < len(self.timeline_scene.project.tracks):
                    old_track = self.timeline_scene.project.tracks[self.track_idx]
                    new_track = self.timeline_scene.project.tracks[self._target_track_idx]
                    if self.clip in old_track.clips:
                        old_track.clips.remove(self.clip)
                        new_track.clips.append(self.clip)
                        self.track_idx = self._target_track_idx
                        self.clip.layer = self._target_track_idx
            self._target_track_idx = None

            # Sort the clips just in case they were dragged past each other
            if self.timeline_scene.project and self.track_idx < len(self.timeline_scene.project.tracks):
                track = self.timeline_scene.project.tracks[self.track_idx]
                track.clips.sort(key=lambda c: c.start_time)
            
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                mw = v.window()
                if hasattr(mw, '_last_active_clip'):
                    mw._last_active_clip = None
                v.load_project(self.timeline_scene.project, maintain_position=True)
                if hasattr(mw, '_sync_media_player'):
                    mw._sync_media_player(v.get_position(), force_seek=True)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.setStyleSheet("QMenu { background-color: #2b2b2b; color: white; border: 1px solid #444; padding: 4px; } QMenu::item:selected { background-color: #007acc; }")
        
        split_act = menu.addAction("✂️ Split Clip at Playhead (S)")
        delete_act = menu.addAction("🗑️ Delete Clip (Del)")
        dup_act = menu.addAction("📋 Duplicate Clip")
        speed_act = menu.addAction("⚡ Set 1.5x Speed")
        sub_act = menu.addAction("🔤 Generate Auto Subtitles")
        
        action = menu.exec_(event.screenPos())
        if action == split_act:
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                ph_t = v.get_position()
                self.timeline_scene.split_selected_clip(ph_t)
        elif action == delete_act:
            track = self.timeline_scene.project.tracks[self.track_idx]
            if self.clip in track.clips:
                track.clips.remove(self.clip)
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                mw = v.window()
                if hasattr(mw, '_last_active_clip'):
                    mw._last_active_clip = None
                v.load_project(self.timeline_scene.project, maintain_position=True)
                if hasattr(mw, '_sync_media_player'):
                    mw._sync_media_player(v.get_position(), force_seek=True)
        elif action == dup_act:
            track = self.timeline_scene.project.tracks[self.track_idx]
            dup_c = Clip(self.clip.file_path, self.clip.end_time + 0.1, self.clip.duration, self.clip.source_start, speed=self.clip.speed, text=getattr(self.clip, 'text', ''))
            track.add_clip(dup_c)
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                mw = v.window()
                if hasattr(mw, '_last_active_clip'):
                    mw._last_active_clip = None
                v.load_project(self.timeline_scene.project, maintain_position=True)
                if hasattr(mw, '_sync_media_player'):
                    mw._sync_media_player(v.get_position(), force_seek=True)
        elif action == speed_act:
            self.clip.speed = 1.5
            QMessageBox.information(None, "Speed Ramping", "Clip speed set to 1.5x!")
        elif action == sub_act:
            if self.timeline_scene.views():
                v = self.timeline_scene.views()[0]
                mw = v.window()
                if hasattr(mw, 'generate_auto_subtitles'):
                    mw.generate_auto_subtitles()

class PlayheadItem(QGraphicsLineItem):
    def __init__(self, scene_height: float):
        super().__init__()
        self.setLine(0, 0, 0, scene_height)
        pen = QPen(Qt.red, 2)
        self.setPen(pen)
        self.setZValue(1000)

class TimelineScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.project: Project = None
        self.setBackgroundBrush(QBrush(QColor(40, 40, 40)))
        
    def load_project(self, project: Project):
        self.project = project
        self.clear()
        
        if not project or not project.tracks:
            return
            
        scene_width = HEADER_WIDTH + (project.get_duration() + 60) * PIXELS_PER_SECOND
        scene_height = max(120, len(project.tracks) * TRACK_HEIGHT)
        self.setSceneRect(0, 0, scene_width, scene_height)
        
        # Draw background lines for tracks
        for idx in range(len(project.tracks) + 1):
            line = QGraphicsLineItem(0, idx * TRACK_HEIGHT, scene_width, idx * TRACK_HEIGHT)
            line.setPen(QPen(QColor(80, 80, 80)))
            line.setZValue(-1)
            self.addItem(line)
        
        # Draw Time Ruler Ticks at top of timeline
        tot_dur = max(60, int(project.get_duration() + 60))
        for s in range(0, tot_dur, 5):
            x = HEADER_WIDTH + s * PIXELS_PER_SECOND
            tick = QGraphicsLineItem(x, 0, x, 6)
            tick.setPen(QPen(QColor(160, 160, 160), 1))
            tick.setZValue(10)
            self.addItem(tick)
            
            lbl = QGraphicsTextItem(f"{s//60:02d}:{s%60:02d}")
            lbl.setDefaultTextColor(QColor(170, 170, 170))
            font = lbl.font()
            font.setPointSize(7)
            lbl.setFont(font)
            lbl.setPos(x - 8, -4)
            lbl.setZValue(10)
            self.addItem(lbl)

        for idx, track in enumerate(project.tracks):
            header = QGraphicsRectItem(0, idx * TRACK_HEIGHT, HEADER_WIDTH, TRACK_HEIGHT)
            header.setBrush(QBrush(QColor(50, 50, 50)))
            header.setPen(QPen(Qt.black))
            self.addItem(header)
            
            text = QGraphicsTextItem(track.name)
            text.setDefaultTextColor(Qt.white)
            text.setPos(2, idx * TRACK_HEIGHT + 2)
            font = text.font()
            font.setPointSize(7)
            font.setBold(True)
            text.setFont(font)
            self.addItem(text)

            # Mute (M) Button
            mute_btn = QPushButton("M")
            mute_btn.setToolTip(f"Mute {track.name} Track")
            mute_btn.setFixedSize(18, 18)
            mute_btn.setStyleSheet("QPushButton { background-color: #d9534f; color: white; border: none; border-radius: 2px; font-size: 9px; font-weight: bold; }" if track.is_muted else "QPushButton { background-color: #444; color: #ccc; border: none; border-radius: 2px; font-size: 9px; }")
            def _make_mute_cb(t=track):
                def _cb():
                    t.is_muted = not t.is_muted
                    if self.views():
                        self.views()[0].load_project(self.project, maintain_position=True)
                return _cb
            mute_btn.clicked.connect(_make_mute_cb(track))
            
            mute_proxy = QGraphicsProxyWidget()
            mute_proxy.setWidget(mute_btn)
            mute_proxy.setPos(5, idx * TRACK_HEIGHT + 28)
            self.addItem(mute_proxy)

            # Solo (S) Button
            solo_btn = QPushButton("S")
            solo_btn.setToolTip(f"Solo {track.name} Track")
            solo_btn.setFixedSize(18, 18)
            solo_btn.setStyleSheet("QPushButton { background-color: #f0ad4e; color: black; border: none; border-radius: 2px; font-size: 9px; font-weight: bold; }" if track.is_solo else "QPushButton { background-color: #444; color: #ccc; border: none; border-radius: 2px; font-size: 9px; }")
            def _make_solo_cb(t=track):
                def _cb():
                    t.is_solo = not t.is_solo
                    if self.views():
                        self.views()[0].load_project(self.project, maintain_position=True)
                return _cb
            solo_btn.clicked.connect(_make_solo_cb(track))

            solo_proxy = QGraphicsProxyWidget()
            solo_proxy.setWidget(solo_btn)
            solo_proxy.setPos(26, idx * TRACK_HEIGHT + 28)
            self.addItem(solo_proxy)
            
            line = QGraphicsLineItem(HEADER_WIDTH, (idx + 1) * TRACK_HEIGHT, scene_width, (idx + 1) * TRACK_HEIGHT)
            line.setPen(QPen(QColor(80, 80, 80)))
            self.addItem(line)
            
            
            for clip in track.clips:
                item = ClipItem(clip, idx, self, track.track_type)
                self.addItem(item)
                
    def split_selected_clip(self, playhead_time: float):
        selected_items = self.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        if not isinstance(item, ClipItem):
            return
            
        clip = item.clip
        track = self.project.tracks[item.track_idx]
        
        if playhead_time <= clip.start_time or playhead_time >= clip.end_time:
            return
            
        split_point_local = playhead_time - clip.start_time
        
        clip2_start = playhead_time
        clip2_duration = clip.duration - split_point_local
        clip2_source_start = clip.source_start + split_point_local
        
        clip.duration = split_point_local
        
        clip2 = Clip(clip.file_path, clip2_start, clip2_duration, clip2_source_start, speed=clip.speed, text=getattr(clip, 'text', ''))
        track.add_clip(clip2)
        
        if self.views():
            view = self.views()[0]
            mw = view.window()
            if hasattr(mw, '_last_active_clip'):
                mw._last_active_clip = None
            view.load_project(self.project, maintain_position=True)
            if hasattr(mw, '_sync_media_player'):
                mw._sync_media_player(playhead_time, force_seek=True)


class TimelineWidget(QGraphicsView):
    position_changed = Signal(float)
    
    def __init__(self):
        super().__init__()
        self.timeline_scene = TimelineScene()
        self.setScene(self.timeline_scene)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHint(QPainter.Antialiasing)
        
        self._is_scrubbing = False
        
        self.playhead = PlayheadItem(TRACK_HEIGHT * 2)
        self.timeline_scene.addItem(self.playhead)
        self.playhead.setPos(HEADER_WIDTH, 0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setMinimumHeight(150)
        
    def is_playhead_valid(self) -> bool:
        if not hasattr(self, 'playhead') or self.playhead is None:
            return False
        try:
            return bool(self.playhead.scene())
        except (RuntimeError, AttributeError):
            return False

    def load_project(self, project: Project, maintain_position: bool = False):
        pos = 0.0
        if maintain_position and self.is_playhead_valid():
            try:
                pos = (self.playhead.x() - HEADER_WIDTH) / PIXELS_PER_SECOND
            except (RuntimeError, AttributeError):
                pos = 0.0
            
        self.timeline_scene.load_project(project)
        scene_height = max(120, len(project.tracks) * TRACK_HEIGHT) if (project and project.tracks) else TRACK_HEIGHT * 2
        
        self.playhead = PlayheadItem(scene_height)
        self.timeline_scene.addItem(self.playhead)
        self.set_position(max(0.0, pos))
        
    def set_position(self, time_sec: float):
        if self.is_playhead_valid():
            try:
                x = HEADER_WIDTH + time_sec * PIXELS_PER_SECOND
                self.playhead.setPos(x, 0)
                self.ensureVisible(self.playhead)
            except (RuntimeError, AttributeError):
                pass

    def get_position(self) -> float:
        if self.is_playhead_valid():
            try:
                return max(0.0, (self.playhead.x() - HEADER_WIDTH) / PIXELS_PER_SECOND)
            except (RuntimeError, AttributeError):
                return 0.0
        return 0.0
        
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        
        item = self.itemAt(event.pos())
        if isinstance(item, ClipItem) and getattr(item, '_dragging_edge', None):
            self._is_scrubbing = False
            return
            
        self._is_scrubbing = True
        scene_pos = self.mapToScene(event.pos())
        if scene_pos.x() >= HEADER_WIDTH:
            time_sec = (scene_pos.x() - HEADER_WIDTH) / PIXELS_PER_SECOND
            time_sec = max(0.0, time_sec)
            self.set_position(time_sec)
            self.position_changed.emit(time_sec)
            
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._is_scrubbing and (event.buttons() & Qt.LeftButton):
            scene_pos = self.mapToScene(event.pos())
            if scene_pos.x() >= HEADER_WIDTH:
                time_sec = (scene_pos.x() - HEADER_WIDTH) / PIXELS_PER_SECOND
                time_sec = max(0.0, time_sec)
                self.set_position(time_sec)
                self.position_changed.emit(time_sec)
                
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._is_scrubbing = False
            
    def set_drag_mode(self, enabled: bool):
        self.timeline_scene.drag_mode_enabled = enabled
