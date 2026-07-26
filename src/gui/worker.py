from PySide6.QtCore import QThread, Signal
import re
import traceback
import sys

class FFmpegWorker(QThread):
    progress = Signal(int)
    status_updated = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.total_target_duration = self.kwargs.pop('total_duration', 0.0)
        self.current_step_duration = 0.0
        self.completed_secs = 0.0
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _cancel_check(self):
        return self._is_cancelled

    def run(self):
        try:
            if 'editors' in self.kwargs:
                editors = self.kwargs.pop('editors')
                for ed in editors:
                    ed.progress_callback = self.handle_progress
                    ed.cancel_check = self._cancel_check
            elif 'editor' in self.kwargs:
                editor = self.kwargs.pop('editor')
                editor.progress_callback = self.handle_progress
                editor.cancel_check = self._cancel_check
                
            result = self.func(*self.args, **self.kwargs)
            self.progress.emit(100)
            self.status_updated.emit(100, "Export Complete (100%)")
            self.finished.emit(result)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
            self.error.emit(str(e))

    def handle_progress(self, line):
        duration_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})", line)
        if duration_match:
            if self.current_step_duration > 0:
                self.completed_secs += self.current_step_duration
            h, m, s = duration_match.groups()
            self.current_step_duration = int(h) * 3600 + int(m) * 60 + float(s)
            
        speed_match = re.search(r"speed=\s*([\d\.]+)x", line)
        speed_str = f" ({speed_match.group(1)}x speed)" if speed_match else ""

        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", line)
        if time_match:
            h, m, s = time_match.groups()
            current_step_secs = int(h) * 3600 + int(m) * 60 + float(s)
            
            if self.total_target_duration > 0:
                total_done = self.completed_secs + current_step_secs
                progress_pct = int((total_done / self.total_target_duration) * 100)
            elif self.current_step_duration > 0:
                progress_pct = int((current_step_secs / self.current_step_duration) * 100)
            else:
                progress_pct = 0

            pct = min(max(0, progress_pct), 100)
            msg = f"Exporting Media... {pct}%{speed_str}"
            self.progress.emit(pct)
            self.status_updated.emit(pct, msg)

class SubtitleWorker(QThread):
    finished = Signal(list, str)
    error = Signal(str)

    def __init__(self, engine, clips, lang, trans, srt_path, model_size="tiny"):
        super().__init__()
        self.engine = engine
        self.clips = clips
        self.lang = lang
        self.trans = trans
        self.srt_path = srt_path
        self.model_size = model_size

    def run(self):
        try:
            all_segments = []
            for clip in self.clips:
                clip_segs = self.engine.generate_subtitles(
                    clip.file_path,
                    language=self.lang,
                    translate_to_english=self.trans,
                    start_time=clip.source_start,
                    duration=clip.duration,
                    model_size=self.model_size
                )
                for seg in clip_segs:
                    all_segments.append({
                        'start': clip.start_time + seg['start'],
                        'end': clip.start_time + seg['end'],
                        'text': seg['text']
                    })

            with open(self.srt_path, "w", encoding="utf-8") as f:
                for idx, seg in enumerate(all_segments, 1):
                    s_str = self.engine.format_srt_time(seg['start'])
                    e_str = self.engine.format_srt_time(seg['end'])
                    # Strip only control characters — keeps Devanagari/Hindi and all other scripts intact
                    clean_t = "".join(c for c in seg['text'] if c == '\n' or c.isprintable())
                    f.write(f"{idx}\n{s_str} --> {e_str}\n{clean_t.strip()}\n\n")

            self.finished.emit(all_segments, self.srt_path)
        except Exception as e:
            self.error.emit(str(e))
