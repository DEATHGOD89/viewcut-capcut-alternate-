import os
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem, QGraphicsPixmapItem
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtCore import Qt, QSizeF, Signal, QRectF, QPointF
from PySide6.QtGui import QPen, QBrush, QColor

class CanvasFrame(QGraphicsView):
    region_selected = Signal(int, int, int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #000000; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.canvas_scene = QGraphicsScene(self)
        self.setScene(self.canvas_scene)
        
        self.video_item = QGraphicsVideoItem()
        self.canvas_scene.addItem(self.video_item)
        self.video_item.setAspectRatioMode(Qt.IgnoreAspectRatio)
        
        # Red translucent selection rectangle overlay
        self.roi_rect_item = QGraphicsRectItem()
        self.roi_rect_item.setPen(QPen(Qt.red, 2, Qt.DashLine))
        self.roi_rect_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
        self.roi_rect_item.setZValue(100)
        self.roi_rect_item.setVisible(False)
        self.canvas_scene.addItem(self.roi_rect_item)

        from PySide6.QtWidgets import QGraphicsPixmapItem
        self.image_item = QGraphicsPixmapItem()
        self.image_item.setZValue(10)
        self.image_item.setVisible(False)
        self.canvas_scene.addItem(self.image_item)

        # Live Color Balancing & 3-Pass Color Grading Canvas Overlays
        self.color_overlay_item = QGraphicsRectItem()
        self.color_overlay_item.setPen(QPen(Qt.NoPen))
        self.color_overlay_item.setZValue(9000)
        self.color_overlay_item.setVisible(False)
        self.canvas_scene.addItem(self.color_overlay_item)

        self.temp_overlay_item = QGraphicsRectItem()
        self.temp_overlay_item.setPen(QPen(Qt.NoPen))
        self.temp_overlay_item.setZValue(9001)
        self.temp_overlay_item.setVisible(False)
        self.canvas_scene.addItem(self.temp_overlay_item)

        self.contrast_overlay_item = QGraphicsRectItem()
        self.contrast_overlay_item.setPen(QPen(Qt.NoPen))
        self.contrast_overlay_item.setZValue(9002)
        self.contrast_overlay_item.setVisible(False)
        self.canvas_scene.addItem(self.contrast_overlay_item)
        self.live_title_item = QGraphicsTextItem()
        self.live_title_item.setZValue(200)
        self.live_title_item.setVisible(False)
        self.live_title_item.setFlag(QGraphicsTextItem.ItemIsMovable, True)
        self.live_title_item.setFlag(QGraphicsTextItem.ItemIsSelectable, True)
        self.canvas_scene.addItem(self.live_title_item)

        self.live_sub_item = QGraphicsTextItem()
        self.live_sub_item.setZValue(201)
        self.live_sub_item.setVisible(False)
        self.live_sub_item.setFlag(QGraphicsTextItem.ItemIsMovable, True)
        self.live_sub_item.setFlag(QGraphicsTextItem.ItemIsSelectable, True)
        self.canvas_scene.addItem(self.live_sub_item)
        
        self._has_moved_title = False
        self._has_moved_sub = False
        
        self.media_width = 0
        self.media_height = 0
        self.scale_mode = "Fit"  # "Fit", "Fill", "Stretch"
        self.pan_x = 0.5  # 0.0 to 1.0
        self.pan_y = 0.5  # 0.0 to 1.0
        
        self._is_dragging = False
        self.roi_selection_mode = False
        self._is_drawing_roi = False
        self._roi_start_scene_pos = QPointF()
        self.current_roi = (50, 50, 150, 80)

    @property
    def video_widget(self):
        return self.video_item

    def set_media_size(self, width: int, height: int):
        self.media_width = width
        self.media_height = height
        self.update_video_layout()

    def set_scale_mode(self, mode: str):
        self.scale_mode = mode
        self.pan_x = 0.5
        self.pan_y = 0.5
        self.update_video_layout()

    def set_roi_selection_mode(self, enabled: bool):
        self.roi_selection_mode = enabled
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_video_layout()

    def update_video_layout(self):
        cw = self.width()
        ch = self.height()
        if cw <= 0 or ch <= 0:
            return
            
        self.canvas_scene.setSceneRect(0, 0, cw, ch)
        
        if self.media_width <= 0 or self.media_height <= 0:
            self.video_item.setSize(QSizeF(cw, ch))
            self.video_item.setPos(0, 0)
            return

        aspect_media = self.media_width / self.media_height
        
        if self.scale_mode == "Stretch":
            vw = cw
            vh = ch
            vx = 0
            vy = 0
        elif self.scale_mode == "Fill":
            aspect_canvas = cw / ch
            if aspect_media > aspect_canvas:
                vh = ch
                vw = ch * aspect_media
            else:
                vw = cw
                vh = cw / aspect_media
            vx = (cw - vw) * self.pan_x
            vy = (ch - vh) * self.pan_y
        else:  # "Fit"
            aspect_canvas = cw / ch
            if aspect_media > aspect_canvas:
                vw = cw
                vh = cw / aspect_media
            else:
                vh = ch
                vw = ch * aspect_media

        zoom = getattr(self, 'zoom_factor', 1.0)
        vw *= zoom
        vh *= zoom
        # Position honors pan (0.5 = centered), so drag-to-pan works in Fill/zoom
        # modes — previously this unconditionally recentered, making pan a no-op.
        vx = (cw - vw) * self.pan_x
        vy = (ch - vh) * self.pan_y

        self.video_item.setSize(QSizeF(vw, vh))
        self.video_item.setPos(vx, vy)
        self.update_overlay_positions()

    def update_roi_overlay(self, x: int, y: int, w: int, h: int, visible: bool = True):
        self.current_roi = (x, y, w, h)
        if not visible or self.media_width <= 0 or self.media_height <= 0:
            self.roi_rect_item.setVisible(False)
            return

        vw = self.video_item.size().width()
        vh = self.video_item.size().height()
        vx = self.video_item.pos().x()
        vy = self.video_item.pos().y()

        scale_x = vw / self.media_width
        scale_y = vh / self.media_height

        cx = vx + (x * scale_x)
        cy = vy + (y * scale_y)
        cw = w * scale_x
        ch = h * scale_y

        self.roi_rect_item.setRect(QRectF(cx, cy, cw, ch))
        self.roi_rect_item.setVisible(True)

    def canvas_to_media_coords(self, rect_f: QRectF):
        vw = self.video_item.size().width()
        vh = self.video_item.size().height()
        vx = self.video_item.pos().x()
        vy = self.video_item.pos().y()

        if vw <= 0 or vh <= 0 or self.media_width <= 0 or self.media_height <= 0:
            return (50, 50, 150, 80)

        rx = rect_f.x() - vx
        ry = rect_f.y() - vy
        rw = rect_f.width()
        rh = rect_f.height()

        scale_x = self.media_width / vw
        scale_y = self.media_height / vh

        real_x = max(0, min(int(rx * scale_x), self.media_width - 2))
        real_y = max(0, min(int(ry * scale_y), self.media_height - 2))
        real_w = max(2, min(int(rw * scale_x), self.media_width - real_x))
        real_h = max(2, min(int(rh * scale_y), self.media_height - real_y))

        return (real_x, real_y, real_w, real_h)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item == self.live_title_item:
                self._has_moved_title = True
            elif item == self.live_sub_item:
                self._has_moved_sub = True

            if self.roi_selection_mode:
                self._is_drawing_roi = True
                self._roi_start_scene_pos = self.mapToScene(event.pos())
                self.roi_rect_item.setRect(QRectF(self._roi_start_scene_pos, QSizeF(1, 1)))
                self.roi_rect_item.setVisible(True)
                event.accept()
                return
            elif item not in (self.live_title_item, self.live_sub_item):
                self._is_dragging = True
                self._drag_start_pos = event.pos()
                self._drag_start_pan = (self.pan_x, self.pan_y)
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_drawing_roi:
            curr_pos = self.mapToScene(event.pos())
            rect = QRectF(self._roi_start_scene_pos, curr_pos).normalized()
            self.roi_rect_item.setRect(rect)
            event.accept()
            return
        elif self._is_dragging:
            delta = event.pos() - self._drag_start_pos
            cw = self.width()
            ch = self.height()
            vw = self.video_item.size().width()
            vh = self.video_item.size().height()

            dx = delta.x() / (cw - vw) if vw != cw else 0
            dy = delta.y() / (ch - vh) if vh != ch else 0

            self.pan_x = max(0.0, min(1.0, self._drag_start_pan[0] + dx))
            self.pan_y = max(0.0, min(1.0, self._drag_start_pan[1] + dy))
            self.update_video_layout()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_drawing_roi:
                self._is_drawing_roi = False
                curr_pos = self.mapToScene(event.pos())
                rect = QRectF(self._roi_start_scene_pos, curr_pos).normalized()
                
                if rect.width() > 5 and rect.height() > 5:
                    rx, ry, rw, rh = self.canvas_to_media_coords(rect)
                    self.current_roi = (rx, ry, rw, rh)
                    self.region_selected.emit(rx, ry, rw, rh)
                    self.update_roi_overlay(rx, ry, rw, rh, visible=True)
                
                self.set_roi_selection_mode(False)
                event.accept()
                return
            elif self._is_dragging:
                self._is_dragging = False
                self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _format_text_html(self, text: str, font_size: int, color_str: str, bg_style: str) -> str:
        escaped_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if not isinstance(bg_style, str):
            bg_style = 'Transparent (Clean Glow)'
        
        if 'Yellow' in bg_style:
            style = f"background-color: #ffd700; color: #000000; padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: {font_size}px; font-family: Arial;"
        elif 'Cyberpunk' in bg_style:
            style = f"background-color: rgba(10, 25, 50, 0.85); color: #00ffff; border: 1px solid #00ffff; padding: 4px 12px; border-radius: 4px; font-size: {font_size}px; font-family: Arial;"
        elif 'Dark' in bg_style:
            style = f"background-color: rgba(0, 0, 0, 0.70); color: #ffffff; padding: 4px 12px; border-radius: 4px; font-size: {font_size}px; font-family: Arial;"
        elif 'Red' in bg_style:
            style = f"background-color: #dc3545; color: #ffffff; padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: {font_size}px; font-family: Arial;"
        else: # Transparent Clean Glow
            style = f"color: {color_str}; text-shadow: 2px 2px 4px #000000; font-size: {font_size}px; font-family: Arial; font-weight: bold;"
            
        return f"<div align='center'><span style='{style}'>{escaped_text}</span></div>"

    def set_live_title_overlay(self, text: str, font_size: int = 36, color_str: str = 'white', bg_style: str = 'Transparent (Clean Glow)', visible: bool = True):
        if isinstance(bg_style, bool):
            visible = bg_style
            bg_style = 'Transparent (Clean Glow)'

        if not text or not visible:
            self.live_title_item.setVisible(False)
            return
        
        fs = max(12, int(font_size * 0.8))
        html_content = self._format_text_html(text, fs, color_str, bg_style)
        self.live_title_item.setHtml(html_content)
        self.live_title_item.setVisible(True)
        if not self._has_moved_title:
            self.update_overlay_positions()

    def set_live_subtitle_overlay(self, text: str, font_size: int = 28, color_str: str = 'yellow', bg_style: str = 'Transparent (Clean Glow)', visible: bool = True):
        if isinstance(bg_style, bool):
            visible = bg_style
            bg_style = 'Transparent (Clean Glow)'

        if not text or not visible:
            self.live_sub_item.setVisible(False)
            return
        
        fs = max(10, int(font_size * 0.7))
        html_content = self._format_text_html(text, fs, color_str, bg_style)
        self.live_sub_item.setHtml(html_content)
        self.live_sub_item.setVisible(True)
        if not self._has_moved_sub:
            self.update_overlay_positions()

    def update_overlay_positions(self):
        cw = self.width()
        ch = self.height()
        if cw <= 0 or ch <= 0:
            return

        is_vertical = (ch > cw * 1.2)
        max_w = cw * 0.85

        if self.live_title_item.isVisible() and not self._has_moved_title:
            self.live_title_item.setTextWidth(max_w)
            br = self.live_title_item.boundingRect()
            tx = (cw - br.width()) / 2
            ty = ch * 0.10
            self.live_title_item.setPos(tx, ty)

        if self.live_sub_item.isVisible() and not self._has_moved_sub:
            self.live_sub_item.setTextWidth(max_w)
            br = self.live_sub_item.boundingRect()
            sx = (cw - br.width()) / 2
            sy = ch * 0.72 if is_vertical else ch * 0.78
            self.live_sub_item.setPos(sx, sy)

    def set_image_overlay(self, image_path_or_pixmap = None, visible: bool = True):
        if not visible or image_path_or_pixmap is None:
            self.image_item.setVisible(False)
            self.video_item.setVisible(True)
            return

        from PySide6.QtGui import QPixmap
        pixmap = None
        if isinstance(image_path_or_pixmap, QPixmap):
            pixmap = image_path_or_pixmap
        elif isinstance(image_path_or_pixmap, str) and os.path.exists(image_path_or_pixmap):
            pixmap = QPixmap(image_path_or_pixmap)

        if pixmap and not pixmap.isNull():
            vw = max(1, self.video_item.size().width())
            vh = max(1, self.video_item.size().height())
            vx = self.video_item.pos().x()
            vy = self.video_item.pos().y()

            scaled_pix = pixmap.scaled(int(vw), int(vh), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.image_item.setPixmap(scaled_pix)
            self.image_item.setPos(vx, vy)
            self.image_item.setZValue(9999)
            self.image_item.setVisible(True)
            self.video_item.setVisible(False)
        else:
            self.image_item.setVisible(False)
            self.video_item.setVisible(True)

    def set_zoom_level(self, factor: float):
        self.zoom_factor = max(0.25, min(5.0, factor))
        self.update_video_layout()

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle > 0:
            self.zoom_factor = min(4.0, getattr(self, 'zoom_factor', 1.0) * 1.15)
        else:
            self.zoom_factor = max(0.5, getattr(self, 'zoom_factor', 1.0) / 1.15)
        self.update_video_layout()
        event.accept()

    def apply_live_color_tuning(self, brightness=0, contrast=0, saturation=0, temperature=0, exposure=0, denoise=0, sharpness=0):
        # Color grading is handled 100% by UnifiedRenderer pixel shading.
        # Overlay items are kept hidden to prevent white haze and unblock mouse events.
        self.color_overlay_item.setVisible(False)
        self.temp_overlay_item.setVisible(False)
        self.contrast_overlay_item.setVisible(False)