from moviepy import AudioFileClip, VideoFileClip, concatenate_videoclips, ImageClip
import re
import os
import time
import random
from PIL import Image, ImageDraw, ImageFont

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
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(video_dir, exist_ok=True)
        if not lesson_text or not lesson_text.strip():
            raise ValueError("Transcript for video generation is empty!")

        chapters = self.split_into_chapters(lesson_text)
        if not chapters:
            chapters = [{'title': 'Lesson', 'body': lesson_text.strip()}]

        chapter_video_paths = []
        total_duration = 0.0
        max_total_duration = float(max_total_duration) if max_total_duration else None
        for i, chapter in enumerate(chapters):
            allowed_time = None
            if max_total_duration is not None:
                remaining_time = max_total_duration - total_duration
                if remaining_time <= 0:
                    break
                allowed_time = remaining_time
            video_path, chapter_duration = self.generate_chapter_video(
                chapter, i, frames_dir, audio_dir, video_dir, allowed_time
            )
            if video_path:
                chapter_video_paths.append(video_path)
                total_duration += chapter_duration
                if max_total_duration is not None and total_duration >= max_total_duration:
                    break

        main_video_name = unique_name("video_lesson_main", "mp4")
        main_video_path = os.path.join(video_dir, main_video_name)
        chapter_clips = [VideoFileClip(p) for p in chapter_video_paths if os.path.exists(p)]
        if not chapter_clips:
            raise ValueError("No video clips generated for concatenation. Check transcript and agent logic.")

        final_video = concatenate_videoclips(chapter_clips, method="compose")
        if max_total_duration is not None and final_video.duration > max_total_duration:
            final_video = final_video.with_duration(max_total_duration)

        final_video.write_videofile(main_video_path, fps=24, codec="libx264", audio_codec="aac")
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
        title = clean_text(chapter['title'])
        body = chapter['body']
        sentences = self.split_into_sentences(body)
        if not sentences:
            print(f"WARNING: No sentences found in chapter {title} (index {chapter_index})")
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
            try:
                if self.voice_processing_agent is not None:
                    self.voice_processing_agent.text_to_speech(clean_sentence, audio_path)
                else:
                    raise RuntimeError("No voice_processing_agent available for TTS.")
            except Exception as e:
                print(f"TTS Error for sentence '{clean_sentence}': {e}")
                continue

            audioclip = AudioFileClip(audio_path)
            duration = audioclip.duration

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
        if not clips:
            return None
        chapter_name = unique_name(f"chapter_{chapter_index}", "mp4")
        chapter_video_path = os.path.join(video_dir, chapter_name)
        chapter_video = concatenate_videoclips(clips, method="compose")
        chapter_video.write_videofile(chapter_video_path, fps=24, codec="libx264", audio_codec="aac")
        chapter_video.close()
        for clip in clips:
            clip.close()
        return chapter_video_path

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
