from moviepy import (
    AudioFileClip,
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
    ImageClip,
    ColorClip,
)
import math
import re
import os
import subprocess
import time
import random
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont
from Agents.Logger_Agent import get_current

CANVAS_W, CANVAS_H = 1280, 720

_NVENC_CACHE: Optional[bool] = None


def _nvenc_available() -> bool:
    """Detect h264_nvenc once per process. Falls back gracefully if ffmpeg missing."""
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        _NVENC_CACHE = "h264_nvenc" in (out.stdout or "")
    except Exception:
        _NVENC_CACHE = False
    return _NVENC_CACHE


def _encode_kwargs():
    """Pick the fastest encoder available on this machine."""
    if _nvenc_available():
        return {
            "codec": "h264_nvenc",
            "preset": "p1",
            "ffmpeg_params": ["-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", "28"],
        }
    return {
        "codec": "libx264",
        "preset": "ultrafast",
        "ffmpeg_params": ["-pix_fmt", "yuv420p"],
    }


def _video_codec_args() -> List[str]:
    """ffmpeg -c:v args matching _encode_kwargs."""
    if _nvenc_available():
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "28",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


FPS = 24
AUDIO_SAMPLE_RATE = 44100


def _write_scene_mp4(image_path: str, audio_path: Optional[str], duration: float,
                     out_path: str) -> bool:
    """Encode a single scene mp4: still image + audio, NVENC preferred.

    Sync-critical flags:
      -framerate {FPS} BEFORE -loop: image input clock matches output fps so
        the looped frames carry consistent timestamps from t=0.
      -fps_mode cfr: forces constant frame rate output — VFR drift on still
        images can accumulate to ~0.5s over 50+ scenes.
      -af aresample=async=1:first_pts=0: realigns audio start to t=0 with no
        leading silence and resamples to fix any sample-rate skew.
      Both streams are explicitly capped with -t and the audio uses -shortest
        as a belt-and-braces guarantee that v-duration == a-duration.
      safe_dur is rounded UP to the nearest video frame boundary so video's
        24fps quantization can't drop below the target — without this, a 1.7s
        target becomes 1.667s of video (40 frames) but ~1.7s of audio, drifting
        ~33ms per scene. Across 100 scenes that compounds to ~0.5s lag."""
    safe_dur = max(duration, 0.5)
    safe_dur = math.ceil(safe_dur * FPS) / FPS  # snap to next frame boundary
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(FPS), "-loop", "1", "-i", image_path]
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path]
    else:
        cmd += ["-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SAMPLE_RATE}"]
    cmd += ["-t", f"{safe_dur:.3f}"]
    cmd += _video_codec_args()
    # apad + atrim forces audio to exactly safe_dur seconds at sample level.
    # Without this, AAC's 1024-sample frame quantization (~23ms) over-runs the
    # video at every scene boundary, accumulating drift across the concat.
    cmd += ["-r", str(FPS), "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "128k",
            "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
            "-af", f"aresample=async=1:first_pts=0,apad,atrim=0:{safe_dur:.6f},asetpts=PTS-STARTPTS",
            "-shortest", "-movflags", "+faststart",
            "-video_track_timescale", "90000",  # consistent timescale for clean concat
            out_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        log = get_current()
        if log: log.error("ffmpeg scene write threw", error=str(e), out=out_path)
        return False
    if result.returncode != 0:
        log = get_current()
        if log: log.error("ffmpeg scene write failed",
                          returncode=result.returncode,
                          stderr=(result.stderr or "")[-600:],
                          out=out_path)
        return False
    return True


def _concat_scene_mp4s(scene_paths: List[str], out_path: str) -> bool:
    """ffmpeg concat demuxer: video copied (instant), audio re-encoded.

    Why audio re-encode (cheap, ~1s per minute): with `-c copy` for both
    streams, AAC encoder priming/padding (~23ms per scene) is preserved at
    every segment boundary and accumulates as audio drift. Re-encoding audio
    yields one continuous AAC stream with exactly one priming offset at the
    very start — so video and audio stay sample-locked across the join.
    Video copy keeps the bulk speedup (an h264 re-encode of the full video
    would be 100x more expensive than the audio pass).

    Sync flags:
      -fflags +genpts: regenerate presentation timestamps so each segment
        starts cleanly at the previous segment's end, no gap accumulation.
      -avoid_negative_ts make_zero: clamp any leading negative timestamps.
      -max_interleave_delta 0: disable mux interleaving heuristic that can
        delay audio by a fraction of a second waiting for video frames.
      -af aresample=async=1: continuous resample across the joined audio
        timeline drops any sub-frame skew from per-scene boundaries."""
    if not scene_paths:
        return False
    list_path = out_path + ".concat.txt"
    # ffmpeg resolves paths in the concat file relative to the list file's directory.
    # Absolute paths avoid the double-prefix trap when nested under the output dir.
    with open(list_path, "w", encoding="utf-8") as f:
        for p in scene_paths:
            absp = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{absp}'\n")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-fflags", "+genpts",
           "-f", "concat", "-safe", "0", "-i", list_path,
           "-c:v", "copy",
           "-c:a", "aac", "-b:a", "128k",
           "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
           "-avoid_negative_ts", "make_zero",
           "-max_interleave_delta", "0",
           "-shortest",  # clip audio to the (frame-snapped) video length so
                         # AAC frame-padding can't push audio past video end.
           "-movflags", "+faststart", out_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        try: os.remove(list_path)
        except OSError: pass
    if result.returncode != 0:
        log = get_current()
        if log: log.error("ffmpeg concat failed",
                          returncode=result.returncode,
                          stderr=(result.stderr or "")[-600:])
        return False
    return True

def unique_name(prefix, ext):
    return f"{prefix}_{int(time.time())}_{random.randint(1000,9999)}.{ext}"

def clean_text(text):
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"[\"']", "", text)
    return text.strip()

class VideoGenerationAgent:
    def __init__(self, voice_processing_agent=None):
        self.voice_processing_agent = voice_processing_agent

    def run(self, lesson_text: str, frames_dir="output/frames", audio_dir="output/audio", video_dir="output/video", max_total_duration=None) -> str:
        log = get_current()
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)
        if not lesson_text or not lesson_text.strip():
            raise ValueError("Transcript for video generation is empty!")

        chapters = self.split_into_chapters(lesson_text)
        if not chapters:
            chapters = [{'title': 'Lesson', 'body': lesson_text.strip()}]
        if log: log.info("VideoGen chapters parsed",
                         chapter_count=len(chapters),
                         titles=[c["title"] for c in chapters][:20])

        chapter_video_paths = []
        total_duration = 0.0
        max_total_duration = float(max_total_duration) if max_total_duration else None
        for i, chapter in enumerate(chapters):
            allowed_time = None
            if max_total_duration is not None:
                remaining_time = max_total_duration - total_duration
                if remaining_time <= 0:
                    if log: log.info("VideoGen budget exhausted, stopping",
                                     finished_chapters=i, total_duration=total_duration)
                    break
                allowed_time = remaining_time
            if log: log.step_start(f"VideoGen.chapter[{i}]",
                                   title=chapter["title"], allowed_s=allowed_time)
            video_path, chapter_duration = self.generate_chapter_video(
                chapter, i, frames_dir, audio_dir, video_dir, allowed_time
            )
            if log: log.step_end(f"VideoGen.chapter[{i}]",
                                 title=chapter["title"], duration_s=round(chapter_duration, 2),
                                 video_path=str(video_path))
            if video_path:
                chapter_video_paths.append(video_path)
                total_duration += chapter_duration
                if max_total_duration is not None and total_duration >= max_total_duration:
                    break

        main_video_name = unique_name("video_lesson_main", "mp4")
        main_video_path = os.path.join(video_dir, main_video_name)
        chapter_clips = [VideoFileClip(p) for p in chapter_video_paths if os.path.exists(p)]
        if not chapter_clips:
            if log: log.error("VideoGen no chapter clips generated")
            raise ValueError("No video clips generated for concatenation. Check transcript and agent logic.")

        enc = _encode_kwargs()
        if log: log.step_start("VideoGen.final_stitch",
                               clip_count=len(chapter_clips), codec=enc["codec"])
        final_video = concatenate_videoclips(chapter_clips, method="chain")
        if max_total_duration is not None and final_video.duration > max_total_duration:
            final_video = final_video.with_duration(max_total_duration)

        final_video.write_videofile(main_video_path, fps=24, audio_codec="aac",
                                    logger=None, threads=os.cpu_count() or 4, **enc)
        size = os.path.getsize(main_video_path) if os.path.exists(main_video_path) else 0
        if log: log.step_end("VideoGen.final_stitch",
                             output=main_video_path, file_size=size,
                             duration_s=round(final_video.duration, 2))
        final_video.close()
        for clip in chapter_clips:
            clip.close()
        return main_video_path

    def split_into_chapters(self, text):
        matches = list(re.finditer(r"([A-Za-z0-9 \-/]+):\s*\n", text))
        chapters = []
        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            body = text[start:end].strip()
            if body:
                chapters.append({'title': title, 'body': body})
        return chapters

    def split_into_sentences(self, text):
        return [s.strip() for s in re.split(r'(?<=[.!?]) +', text.strip()) if s.strip()]

    def generate_chapter_video(self, chapter, chapter_index, frames_dir, audio_dir, video_dir, allowed_time=None):
        log = get_current()
        title = clean_text(chapter['title'])
        body = chapter['body']
        sentences = self.split_into_sentences(body)
        if log: log.info(f"VideoGen.chapter[{chapter_index}] sentences split",
                         title=title, sentence_count=len(sentences), body_chars=len(body))
        if not sentences:
            if log: log.warn(f"VideoGen.chapter[{chapter_index}] no sentences", title=title)
            else: print(f"WARNING: No sentences found in chapter {title} (index {chapter_index})")
            return None, 0.0
        clips = []
        duration_accum = 0.0

        title_image_path = os.path.join(frames_dir, f"chapter_{chapter_index}_title.png")
        self.make_slide(title, title_image_path, is_title=True)
        title_duration = 2.0
        if allowed_time is not None and allowed_time < title_duration:
            title_duration = allowed_time
        title_clip = ImageClip(title_image_path).with_duration(title_duration)
        clips.append(title_clip)
        duration_accum += title_duration
        if allowed_time is not None and duration_accum >= allowed_time:
            return self._save_chapter_video(clips, video_dir, chapter_index), duration_accum

        for i, sentence in enumerate(sentences):
            clean_sentence = clean_text(sentence)
            if not clean_sentence:
                continue
            audio_name = unique_name(f"chapter_{chapter_index}_audio_{i}", "mp3")
            audio_path = os.path.join(audio_dir, audio_name)
            if log: log.step_start(f"VideoGen.ch{chapter_index}.sentence[{i}]",
                                   text_len=len(clean_sentence), preview=clean_sentence[:80])
            try:
                if self.voice_processing_agent is not None:
                    self.voice_processing_agent.text_to_speech(clean_sentence, audio_path)
                else:
                    raise RuntimeError("No voice_processing_agent available for TTS.")
            except Exception as e:
                if log: log.error(f"VideoGen.ch{chapter_index}.sentence[{i}] TTS failed",
                                  exc_info=True, error=str(e), sentence=clean_sentence[:120])
                else: print(f"TTS Error for sentence '{clean_sentence}': {e}")
                continue

            audioclip = AudioFileClip(audio_path)
            duration = audioclip.duration
            if log: log.step_end(f"VideoGen.ch{chapter_index}.sentence[{i}]",
                                 audio=audio_name, duration_s=round(duration, 2),
                                 cumulative_s=round(duration_accum + duration, 2))

            if allowed_time is not None and (duration_accum + duration) > allowed_time:
                time_left = allowed_time - duration_accum
                if time_left <= 0.01:
                    # audioclip.close()  # Don't close here!
                    break
                image_name = unique_name(f"chapter_{chapter_index}_frame_{i}", "png")
                image_path = os.path.join(frames_dir, image_name)
                self.make_slide(clean_sentence, image_path, is_title=False)
                trimmed_audio = audioclip.subclipped(0, time_left)
                slide_clip = ImageClip(image_path).with_duration(time_left).with_audio(trimmed_audio)
                clips.append(slide_clip)
                duration_accum += time_left
                # audioclip.close()  # Don't close here!
                break
            else:
                image_name = unique_name(f"chapter_{chapter_index}_frame_{i}", "png")
                image_path = os.path.join(frames_dir, image_name)
                self.make_slide(clean_sentence, image_path, is_title=False)
                slide_clip = ImageClip(image_path).with_duration(duration).with_audio(audioclip)
                clips.append(slide_clip)
                duration_accum += duration
                # audioclip.close()  # Don't close here!

            if allowed_time is not None and duration_accum >= allowed_time:
                break

        return self._save_chapter_video(clips, video_dir, chapter_index), duration_accum

    def _save_chapter_video(self, clips, video_dir, chapter_index):
        log = get_current()
        if not clips:
            if log: log.warn(f"VideoGen.chapter[{chapter_index}] no clips, skipping save")
            return None
        chapter_name = unique_name(f"chapter_{chapter_index}", "mp4")
        chapter_video_path = os.path.join(video_dir, chapter_name)
        enc = _encode_kwargs()
        if log: log.step_start(f"VideoGen.ch{chapter_index}.write",
                               clip_count=len(clips), codec=enc["codec"])
        chapter_video = concatenate_videoclips(clips, method="chain")
        chapter_video.write_videofile(chapter_video_path, fps=24, audio_codec="aac",
                                      logger=None, threads=os.cpu_count() or 4, **enc)
        size = os.path.getsize(chapter_video_path) if os.path.exists(chapter_video_path) else 0
        if log: log.step_end(f"VideoGen.ch{chapter_index}.write",
                             path=chapter_video_path, file_size=size)
        chapter_video.close()
        for clip in clips:
            clip.close()
        return chapter_video_path

    def run_storyboard(
        self,
        transcript: str,
        storyboard_composer,
        frames_dir: str = "output/frames",
        audio_dir: str = "output/audio",
        video_dir: str = "output/video",
        max_total_duration: Optional[float] = None,
        silent: bool = False,
        topic: str = "",
    ) -> str:
        """Animated render: storyboard scenes -> Ken-Burns image + overlay text + per-scene audio."""
        log = get_current()
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)
        if log: log.step_start("VideoGen.storyboard.compose")
        storyboard = storyboard_composer.run(
            transcript, max_total_duration=max_total_duration, topic=topic,
        )
        scenes: List[Dict[str, Any]] = storyboard.get("scenes", [])
        if log: log.step_end("VideoGen.storyboard.compose",
                             scene_count=len(scenes),
                             total_duration=storyboard.get("total_duration"))
        if not scenes:
            raise ValueError("Storyboard composer returned no scenes.")

        scene_mp4s: List[str] = []
        cumulative = 0.0
        for idx, scene in enumerate(scenes):
            duration = float(scene.get("duration", 4.0))
            if log: log.step_start(f"VideoGen.scene[{idx}]",
                                   scene_id=scene.get("scene_id"),
                                   keywords=scene.get("keywords"),
                                   visual_type=scene.get("visual_type"),
                                   duration=duration)

            audio_path: Optional[str] = None
            if not silent and self.voice_processing_agent is not None:
                audio_name = unique_name(f"scene_{idx}", "mp3")
                candidate = os.path.join(audio_dir, audio_name)
                try:
                    self.voice_processing_agent.text_to_speech(
                        clean_text(scene.get("text", "")), candidate
                    )
                    # Probe duration via AudioFileClip — this is fast (no encode).
                    a = AudioFileClip(candidate)
                    duration = a.duration
                    a.close()
                    audio_path = candidate
                except Exception as e:
                    if log: log.error(f"VideoGen.scene[{idx}] TTS failed",
                                      exc_info=True, error=str(e))
                    audio_path = None

            assets = scene.get("assets") or []
            # Background = first non-icon photo asset. Icon = first iconify PNG.
            bg_path = next(
                (a.get("local_path") for a in assets
                 if a.get("local_path")
                 and a.get("provider") != "iconify"
                 and not str(a.get("local_path")).endswith(".svg")),
                None,
            )
            icon_path = next(
                (a.get("local_path") for a in assets
                 if a.get("provider") == "iconify" and a.get("local_path")),
                None,
            )

            scene_image_path = os.path.join(frames_dir, f"scene_{idx}_full.png")
            self._build_scene_image(
                bg_path,
                clean_text(scene.get("text", "")),
                scene.get("layout", {}),
                idx,
                scene_image_path,
                icon_path=icon_path,
            )

            scene_mp4 = os.path.join(video_dir, f"scene_{idx:04d}.mp4")
            ok = _write_scene_mp4(scene_image_path, audio_path, duration, scene_mp4)
            if not ok:
                if log: log.error(f"VideoGen.scene[{idx}] mp4 write failed")
                continue
            scene_mp4s.append(scene_mp4)
            cumulative += duration
            if log: log.step_end(f"VideoGen.scene[{idx}]",
                                 cumulative_s=round(cumulative, 2),
                                 has_audio=audio_path is not None,
                                 bg=bg_path, icon=icon_path,
                                 mp4=scene_mp4)

            if max_total_duration and cumulative >= max_total_duration:
                break

        if not scene_mp4s:
            raise RuntimeError("No scene mp4s were produced — check ffmpeg + scene logs.")

        out_name = unique_name("video_storyboard", "mp4")
        out_path = os.path.join(video_dir, out_name)
        if log: log.step_start("VideoGen.storyboard.stitch",
                               clip_count=len(scene_mp4s), method="ffmpeg_concat_copy")
        # ffmpeg concat demuxer with `-c copy` — no re-encode, instant even for
        # hours of video. Replaces the moviepy chain stitch which took 45+ min.
        if not _concat_scene_mp4s(scene_mp4s, out_path):
            raise RuntimeError("ffmpeg concat failed — check log for stderr.")
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        if log: log.step_end("VideoGen.storyboard.stitch",
                             output=out_path, file_size=size,
                             duration_s=round(cumulative, 2))
        # Clean up the per-scene mp4s — they were only intermediate.
        for p in scene_mp4s:
            try: os.remove(p)
            except OSError: pass
        return out_path

    @classmethod
    def _build_scene_image(cls, asset_path: Optional[str], text: str,
                           layout: Dict[str, Any], idx: int, out_path: str,
                           icon_path: Optional[str] = None):
        """One PNG = bg photo + optional icon accent + translucent panel + wrapped text.
        Saved at canvas size so the scene becomes a single ImageClip."""
        bg = cls._build_bg_image(asset_path, idx)  # RGB, CANVAS_W x CANVAS_H
        canvas = bg.convert("RGBA")
        if icon_path and os.path.exists(icon_path):
            cls._paint_icon_accent(canvas, icon_path)
        cls._paint_text_panel(canvas, text, layout)
        canvas.convert("RGB").save(out_path, format="PNG")

    @staticmethod
    def _paint_icon_accent(canvas: Image.Image, icon_path: str):
        """Paste a small icon in the top-right corner with a translucent dark backing
        so a white iconify PNG is legible on any photo background."""
        try:
            icon = Image.open(icon_path).convert("RGBA")
        except Exception:
            return
        # Resize icon to ~140px tall.
        target_h = 140
        if icon.height != target_h:
            scale = target_h / icon.height
            icon = icon.resize((int(icon.width * scale), target_h), Image.LANCZOS)
        pad = 24
        box_w = icon.width + pad * 2
        box_h = icon.height + pad * 2
        # Top-right corner with 32px margin.
        bx = CANVAS_W - box_w - 32
        by = 32
        backing = Image.new("RGBA", (box_w, box_h), (15, 23, 42, 180))
        canvas.alpha_composite(backing, (bx, by))
        canvas.alpha_composite(icon, (bx + pad, by + pad))

    @staticmethod
    def _build_bg_image(asset_path: Optional[str], idx: int) -> Image.Image:
        """Cropped/resized background at exactly CANVAS_W x CANVAS_H, RGB."""
        palette = [(30, 41, 59), (55, 65, 81), (15, 23, 42), (51, 65, 85)]
        if not asset_path or not os.path.exists(asset_path):
            return Image.new("RGB", (CANVAS_W, CANVAS_H), palette[idx % len(palette)])
        try:
            img = Image.open(asset_path).convert("RGB")
        except Exception:
            return Image.new("RGB", (CANVAS_W, CANVAS_H), (20, 20, 30))
        scale = max(CANVAS_W / img.width, CANVAS_H / img.height)
        new_w, new_h = int(img.width * scale), int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - CANVAS_W) // 2
        top = (new_h - CANVAS_H) // 2
        return img.crop((left, top, left + CANVAS_W, top + CANVAS_H))

    @staticmethod
    def _paint_text_panel(canvas: Image.Image, text: str, layout: Dict[str, Any]):
        """Mutates canvas (RGBA) in place — translucent panel + wrapped text."""
        draw = ImageDraw.Draw(canvas)
        tp = layout.get("text_position", {}) if isinstance(layout, dict) else {}
        x = int(tp.get("x", 60))
        y = int(tp.get("y", 480))
        w = int(tp.get("width", CANVAS_W - 120))
        h = int(tp.get("height", 200))
        align = tp.get("align", "center")

        panel = Image.new("RGBA", (w + 40, h + 40), (15, 23, 42, 200))
        canvas.alpha_composite(panel, (max(x - 20, 0), max(y - 20, 0)))

        try:
            font = ImageFont.truetype("arial.ttf", 38)
        except Exception:
            font = ImageFont.load_default()

        words = (text or "").split()
        lines: List[str] = []
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            if draw.textlength(test, font=font) > w - 20 and line:
                lines.append(line)
                line = word
            else:
                line = test
        if line:
            lines.append(line)

        line_h = font.size + 10
        total_h = line_h * len(lines)
        cy = y + (h - total_h) // 2
        for ln in lines:
            tw = draw.textlength(ln, font=font)
            if align == "left":
                cx = x
            elif align == "right":
                cx = x + w - int(tw)
            else:
                cx = x + (w - int(tw)) // 2
            draw.text((cx, cy), ln, font=font, fill=(255, 255, 255, 255))
            cy += line_h

    def make_slide(self, text, image_path, is_title=False):
        width, height = 1280, 720
        font_size = 70 if is_title else 48
        image = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
        lines = []
        words = text.replace('\n', ' ').split(" ")
        line = ""
        for word in words:
            test_line = line + (" " if line else "") + word
            line_length = draw.textlength(test_line.replace("\n", ""), font=font)
            if line_length > width - 100:
                lines.append(line)
                line = word
            else:
                line = test_line
        lines.append(line)
        y_text = height // 2 - (len(lines) * font_size) // 2
        for line in lines:
            text_width = draw.textlength(line.replace("\n", ""), font=font)
            x_text = (width - int(text_width)) // 2
            draw.text((x_text, y_text), line, font=font, fill="black")
            y_text += font_size + 10
        image.save(image_path)
