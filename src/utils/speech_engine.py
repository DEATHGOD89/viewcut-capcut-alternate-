import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict
from utils.logger import get_logger

logger = get_logger(__name__)

class SpeechToTextEngine:
    """
    Responsive Voice-to-Text Subtitle Engine.
    Transcribes audio into timed subtitle lines synchronized with spoken voice,
    calculating resolution-responsive font sizes for 16:9 vs 9:16.
    """
    def __init__(self, ffmpeg_path: str = None):
        if not ffmpeg_path:
            try:
                from utils.ffmpeg_wrapper import FFmpegWrapper
                ffmpeg_path = FFmpegWrapper().ffmpeg_path
            except Exception:
                ffmpeg_path = "ffmpeg"
        self.ffmpeg_path = ffmpeg_path
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            ffmpeg_dir = str(Path(self.ffmpeg_path).parent.absolute())
            if ffmpeg_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    def calculate_responsive_font_style(self, canvas_w: int, canvas_h: int) -> Dict:
        """
        Calculates optimal responsive font size and position based on aspect ratio.
        """
        is_vertical = (canvas_h > canvas_w * 1.2)
        base_size = min(canvas_w, canvas_h)
        
        if is_vertical:
            # 9:16 Shorts/Reels (e.g. 1080x1920)
            font_size = max(24, int(base_size * 0.045))
            margin_bottom = int(canvas_h * 0.25)
        else:
            # 16:9 Horizontal (e.g. 1920x1080)
            font_size = max(28, int(base_size * 0.055))
            margin_bottom = int(canvas_h * 0.12)

        return {
            'font_size': font_size,
            'margin_bottom': margin_bottom,
            'is_vertical': is_vertical
        }

    def format_srt_time(self, seconds: float) -> str:
        millis = int((seconds - int(seconds)) * 1000)
        secs = int(seconds) % 60
        mins = (int(seconds) // 60) % 60
        hours = int(seconds) // 3600
        return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    def extract_audio_wav(self, video_path: str, temp_wav_path: str, start_time: float = 0.0, duration: float = None) -> bool:
        cmd = [self.ffmpeg_path]
        if start_time > 0:
            cmd.extend(['-ss', f"{start_time:.3f}"])
        cmd.extend(['-i', video_path])
        if duration is not None and duration > 0:
            cmd.extend(['-t', f"{duration:.3f}"])
        cmd.extend([
            '-map', '0:a:0?',
            '-ar', '16000',
            '-ac', '1',
            '-c:a', 'pcm_s16le',
            '-y', temp_wav_path
        ])
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=creationflags)
            return res.returncode == 0 and os.path.exists(temp_wav_path)
        except Exception as e:
            logger.error(f"Failed to extract WAV audio: {e}")
            return False

    @staticmethod
    def devanagari_to_hinglish(text: str) -> str:
        """
        Transliterates Devanagari Hindi text into Romanized Hindi (Hinglish).
        e.g. 'नमस्ते, आप कैसे हैं?' -> 'Namaste, aap kaise hain?'
        """
        if not any('\u0900' <= c <= '\u097f' for c in text):
            return text

        mapping = {
            'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
            'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah',
            'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
            'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'nya',
            'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
            'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
            'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
            'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
            'ष': 'sh', 'स': 's', 'ह': 'h',
            'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
            'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n',
            '्': '', '़': ''
        }

        res = []
        for char in text:
            res.append(mapping.get(char, char))

        result = "".join(res)
        if result and result[0].isalpha():
            result = result[0].upper() + result[1:]
        return result

    _cached_model = None
    _cached_model_name = None

    def get_model(self, model_name: str = "tiny"):
        if SpeechToTextEngine._cached_model is not None and SpeechToTextEngine._cached_model_name == model_name:
            return SpeechToTextEngine._cached_model
        import whisper
        logger.info(f"Loading Whisper AI model '{model_name}' into RAM cache...")
        model = whisper.load_model(model_name)
        SpeechToTextEngine._cached_model = model
        SpeechToTextEngine._cached_model_name = model_name
        return model

    def generate_subtitles(self, video_path: str, output_srt_path: str = None, language: str = None, translate_to_english: bool = False, start_time: float = 0.0, duration: float = None, model_size: str = "tiny") -> List[Dict]:
        """
        Generates timed voice subtitle segments (start_time, end_time, text).
        Supports Hindi, English, Romanized Hindi (Hinglish), and auto-translation.
        """
        segments = []
        import tempfile
        temp_wav = os.path.join(tempfile.gettempdir(), f"veditor_speech_{abs(hash(video_path))}.wav")
        
        # Guarantee FFmpeg binary directory is in OS PATH for Whisper's internal subprocess calls
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            ffmpeg_dir = str(Path(self.ffmpeg_path).parent.absolute())
            if ffmpeg_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

        try:
            if self.extract_audio_wav(video_path, temp_wav, start_time=start_time, duration=duration):
                try:
                    s_str = str(model_size).lower()
                    if "medium" in s_str or "studio" in s_str:
                        m_name = "medium"
                    elif "small" in s_str or "97%" in s_str or "high precision" in s_str:
                        m_name = "small"
                    elif "tiny" in s_str or "ultra-fast" in s_str:
                        m_name = "tiny"
                    else:
                        m_name = "base"
                        
                    model = self.get_model(m_name)
                    
                    options = {'fp16': False, 'word_timestamps': True}
                    is_hinglish = bool(language and ('Hinglish' in language or 'Romanized' in language))

                    if is_hinglish:
                        options['language'] = 'hi'
                        options['task'] = 'transcribe'
                    elif translate_to_english:
                        options['task'] = 'translate'
                    else:
                        options['task'] = 'transcribe'

                    if not is_hinglish and language and 'Auto' not in language:
                        lang_code = 'hi' if 'Hindi' in language else 'en' if 'English' in language else language.lower()[:2]
                        options['language'] = lang_code

                    res = model.transcribe(temp_wav, **options)
                    for seg in res.get('segments', []):
                        words = seg.get('words', [])
                        seg_text = seg.get('text', '').strip()
                        if not seg_text or seg_text == '.':
                            continue

                        if words:
                            curr_words = []
                            curr_start = None
                            last_end = None
                            for w in words:
                                w_txt = w.get('word', '').strip()
                                w_start = float(w.get('start', 0.0))
                                w_end = float(w.get('end', 0.0))
                                if not w_txt:
                                    continue
                                
                                # Silence gap > 0.4s splits subtitle clips
                                if last_end is not None and (w_start - last_end > 0.4):
                                    if curr_words:
                                        full_t = " ".join(curr_words).strip()
                                        if is_hinglish:
                                            full_t = self.devanagari_to_hinglish(full_t)
                                        if full_t and full_t != '.':
                                            segments.append({'start': curr_start, 'end': last_end, 'text': full_t})
                                    curr_words = [w_txt]
                                    curr_start = w_start
                                else:
                                    if curr_start is None:
                                        curr_start = w_start
                                    curr_words.append(w_txt)
                                last_end = w_end

                            if curr_words and curr_start is not None and last_end is not None:
                                full_t = " ".join(curr_words).strip()
                                if is_hinglish:
                                    full_t = self.devanagari_to_hinglish(full_t)
                                if full_t and full_t != '.':
                                    segments.append({'start': curr_start, 'end': last_end, 'text': full_t})
                        else:
                            txt = seg_text
                            if is_hinglish:
                                txt = self.devanagari_to_hinglish(txt)
                            if txt and txt != '.':
                                segments.append({
                                    'start': float(seg.get('start', 0.0)),
                                    'end': float(seg.get('end', 0.0)),
                                    'text': txt
                                })

                    if not segments and res.get('segments', []):
                        for seg in res.get('segments', []):
                            txt = seg.get('text', '').strip()
                            if is_hinglish:
                                txt = self.devanagari_to_hinglish(txt)
                            if txt and txt != '.':
                                segments.append({
                                    'start': float(seg.get('start', 0.0)),
                                    'end': float(seg.get('end', 0.0)),
                                    'text': txt
                                })
                except Exception as e:
                    logger.error(f"Whisper transcription failed: {e}")
        finally:
            if os.path.exists(temp_wav):
                try: os.remove(temp_wav)
                except OSError: pass

        if output_srt_path:
            with open(output_srt_path, "w", encoding="utf-8") as f:
                for idx, seg in enumerate(segments, 1):
                    s_str = self.format_srt_time(seg['start'])
                    e_str = self.format_srt_time(seg['end'])
                    # Strip only control characters — keeps Devanagari/Hindi and all other scripts intact
                    clean_t = "".join(c for c in seg['text'] if c == '\n' or c.isprintable())
                    f.write(f"{idx}\n{s_str} --> {e_str}\n{clean_t.strip()}\n\n")

        return segments
