import uuid
import json
from typing import List, Optional, Dict, Any

class Clip:
    def __init__(self, file_path: str, start_time: float, duration: float, 
                 source_start: float = 0.0, speed: float = 1.0, text: str = "",
                 layer: int = 0, clip_type: str = "video",
                 x_pos: int = 0, y_pos: int = 0, scale: float = 1.0, 
                 rotation: float = 0.0, opacity: float = 1.0,
                 volume: float = 1.0, is_muted: bool = False,
                 effects: Optional[Dict[str, Any]] = None,
                 animation: Optional[Dict[str, Any]] = None):
        self.id = str(uuid.uuid4())
        self.file_path = file_path
        self.start_time = float(start_time)      # Position on the timeline (sec)
        self.duration = float(duration)          # Duration on timeline (sec)
        self.source_start = float(source_start)  # Start time in source file (sec)
        self.speed = float(speed)                # Playback speed (0.25 to 4.0)
        self.keyframes = []                      # Keyframe animation list
        self.text = text                         # Text overlay content
        self.layer = int(layer)                  # Z-Index layer ordering (higher = on top)
        self.clip_type = clip_type               # 'video', 'image', 'text', 'audio'
        
        # Transform & Audio properties
        self.x_pos = int(x_pos)
        self.y_pos = int(y_pos)
        self.scale = float(scale)
        self.rotation = float(rotation)
        self.opacity = float(opacity)
        self.volume = float(volume)
        self.is_muted = bool(is_muted)
        
        # Non-destructive Effects & Animation dicts
        self.effects = effects or {
            "brightness": 0.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "temperature": 0.0,
            "tint": 0.0,
            "exposure": 0.0,
            "blur": 0.0,
            "vignette": 0.0
        }
        self.animation = animation or {
            "in": "none",
            "out": "none",
            "duration": 0.5
        }
        
    @property
    def end_time(self) -> float:
        return self.start_time + (self.duration / max(0.1, self.speed))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "start": self.start_time,
            "end": self.end_time,
            "duration": self.duration,
            "source_start": self.source_start,
            "speed": self.speed,
            "text": self.text,
            "layer": self.layer,
            "type": self.clip_type,
            "position": {"x": self.x_pos, "y": self.y_pos},
            "scale": self.scale,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "effects": self.effects,
            "animation": self.animation,
            "keyframes": [kf.to_dict() if hasattr(kf, 'to_dict') else str(kf) for kf in self.keyframes]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Clip':
        pos = data.get("position", {})
        clip = cls(
            file_path=data.get("file_path", ""),
            start_time=data.get("start", data.get("start_time", 0.0)),
            duration=data.get("duration", 5.0),
            source_start=data.get("source_start", 0.0),
            speed=data.get("speed", 1.0),
            text=data.get("text", ""),
            layer=data.get("layer", 0),
            clip_type=data.get("type", data.get("clip_type", "video")),
            x_pos=pos.get("x", data.get("x_pos", 0)),
            y_pos=pos.get("y", data.get("y_pos", 0)),
            scale=data.get("scale", 1.0),
            rotation=data.get("rotation", 0.0),
            opacity=data.get("opacity", 1.0),
            effects=data.get("effects"),
            animation=data.get("animation")
        )
        if "id" in data:
            clip.id = data["id"]
        return clip

class Track:
    def __init__(self, name: str, track_type: str = "video", layer: int = 0):
        self.id = str(uuid.uuid4())
        self.name = name
        self.track_type = track_type  # 'video', 'audio', 'subtitle', 'overlay'
        self.layer = int(layer)       # Track Z-Index
        self.is_muted: bool = False
        self.is_solo: bool = False
        self.clips: List[Clip] = []
        
    def add_clip(self, clip: Clip):
        clip.layer = self.layer
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.start_time)
        
    def remove_clip(self, clip_id: str):
        self.clips = [c for c in self.clips if c.id != clip_id]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "track_type": self.track_type,
            "layer": self.layer,
            "is_muted": self.is_muted,
            "is_solo": self.is_solo,
            "clips": [c.to_dict() for c in self.clips]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Track':
        t = cls(
            name=data.get("name", "Track"),
            track_type=data.get("track_type", "video"),
            layer=data.get("layer", 0)
        )
        t.id = data.get("id", t.id)
        t.is_muted = data.get("is_muted", False)
        t.is_solo = data.get("is_solo", False)
        for cd in data.get("clips", []):
            t.add_clip(Clip.from_dict(cd))
        return t

class Project:
    def __init__(self, name: str = "Untitled Project"):
        self.name = name
        self.tracks: List[Track] = []
        
    def add_track(self, track: Track):
        self.tracks.append(track)
        
    def get_duration(self) -> float:
        max_duration = 0.0
        for track in self.tracks:
            for clip in track.clips:
                max_duration = max(max_duration, clip.end_time)
        return max_duration

    def get_active_clips_at(self, timeline_time: float) -> List[Clip]:
        active = []
        for track in self.tracks:
            if track.is_muted:
                continue
            for clip in track.clips:
                if clip.start_time <= timeline_time < clip.end_time:
                    active.append(clip)
        active.sort(key=lambda c: c.layer)
        return active

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tracks": [t.to_dict() for t in self.tracks]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        p = cls(name=data.get("name", "Untitled Project"))
        for td in data.get("tracks", []):
            p.add_track(Track.from_dict(td))
        return p
