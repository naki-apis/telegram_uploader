import os
import random
import subprocess
import tempfile
from pyrogram import Client
from .compressor import compress_to_volumes, cleanup_volumes


def human_size(n):
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            if u == "B":
                return f"{int(f)} {u}"
            return f"{f:.2f} {u}"
        f /= 1024


def bar(pct):
    filled = int(pct / 5)
    if filled > 20:
        filled = 20
    return "[" + "*" * filled + "-" * (20 - filled) + "]"


def get_video_duration(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return int(float(out))
    except Exception:
        return 0


def get_random_thumb(path):
    try:
        fd, thumb = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        t = random.uniform(0, 5)
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-vframes", "1",
             "-vf", "scale=320:-1", thumb],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
        return thumb
    except Exception:
        return None


def sorted_files(folder):
    entries = sorted(os.listdir(folder))
    return [
        os.path.join(folder, e) for e in entries
        if os.path.isfile(os.path.join(folder, e))
    ]


def default_limit(premium=False):
    return 3995 * 1024 * 1024 if premium else 1995 * 1024 * 1024


class TelegramUploader:
    def __init__(self, api_id, api_hash, session_name="telegram_uploader",
                 premium=False, zip_option=None):
        self.client = Client(session_name, api_id=api_id, api_hash=api_hash)
        self.premium = premium
        self.limit = default_limit(premium)
        self.zip_option = zip_option
        self.errors = []

    def start(self):
        self.client.start()

    def stop(self):
        try:
            self.client.stop()
        except Exception:
            pass

    def _progress(self, current, total, prefix="Enviado"):
        pct = (current / total) * 100 if total else 0
        line = f"{bar(pct)} {human_size(current)}/{human_size(total)} {pct:.1f}%"
        print("\r" + line, end="", flush=True)

    def _done(self, total):
        line = f"{bar(100)} {human_size(total)}/{human_size(total)} 100.0%"
        print("\r" + line, flush=True)

    def _send_one(self, path, chat_id, as_video, caption):
        total = os.path.getsize(path)
        print(caption)
        if as_video:
            duration = get_video_duration(path)
            thumb = get_random_thumb(path)
            try:
                self.client.send_video(
                    chat_id=chat_id,
                    video=path,
                    duration=duration,
                    thumb=thumb,
                    caption=caption,
                    supports_streaming=True,
                    progress=self._progress,
                )
            finally:
                if thumb and os.path.exists(thumb):
                    try:
                        os.remove(thumb)
                    except OSError:
                        pass
        else:
            self.client.send_document(
                chat_id=chat_id,
                document=path,
                caption=caption,
                progress=self._progress,
            )
        self._done(total)

    def _should_compress(self, path):
        if self.zip_option is not None:
            return True
        return os.path.getsize(path) > self.limit

    def _compress(self, path):
        if self.zip_option is not None:
            volume, level = self.zip_option
        else:
            volume = self.limit
            level = 0
        return compress_to_volumes(path, volume, level)

    def send_file(self, path, chat_id=None, as_video=False):
        if chat_id is None:
            chat_id = "me"
        name = os.path.basename(path)
        if self._should_compress(path):
            try:
                parts = self._compress(path)
            except Exception as e:
                self.errors.append((path, str(e)))
                print(f"Error comprimiendo {path}: {e}")
                return
            try:
                for part in parts:
                    part_name = os.path.basename(part)
                    try:
                        self._send_one(part, chat_id, False, part_name)
                    except Exception as e:
                        self.errors.append((part, str(e)))
                        print(f"Error enviando {part}: {e}")
            finally:
                cleanup_volumes(parts)
        else:
            try:
                self._send_one(path, chat_id, as_video, name)
            except Exception as e:
                self.errors.append((path, str(e)))
                print(f"Error enviando {path}: {e}")

    def send_folder(self, folder, chat_id=None, as_video=False):
        if not os.path.isdir(folder):
            raise NotADirectoryError(folder)
        if self.zip_option is not None or self._folder_needs_compress(folder):
            try:
                parts = self._compress(folder)
            except Exception as e:
                self.errors.append((folder, str(e)))
                print(f"Error comprimiendo {folder}: {e}")
                return
            try:
                for part in parts:
                    part_name = os.path.basename(part)
                    try:
                        self._send_one(part, chat_id, False, part_name)
                    except Exception as e:
                        self.errors.append((part, str(e)))
                        print(f"Error enviando {part}: {e}")
            finally:
                cleanup_volumes(parts)
            return
        for f in sorted_files(folder):
            self.send_file(f, chat_id=chat_id, as_video=as_video)

    def _folder_needs_compress(self, folder):
        for f in sorted_files(folder):
            if os.path.getsize(f) > self.limit:
                return True
        return False
