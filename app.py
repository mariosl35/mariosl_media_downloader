import os
import re
import sys
import shutil
import uuid
import threading
import webbrowser
import time
from pathlib import Path

import yt_dlp
from flask import Flask, jsonify, render_template, request, send_from_directory

# ─────────────────────
# App Initialisation
# ─────────────────────

app = Flask(__name__)

# Path to the downloads folder
def get_downloads_folder() -> Path:
    """Return the user's actual Windows Downloads folder."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            folder_id = GUID(
                0x374DE290,
                0x123F,
                0x4565,
                (wintypes.BYTE * 8)(
                    0x91, 0x64, 0x39, 0xC4,
                    0x92, 0x5E, 0x46, 0x7B
                ),
            )

            path_ptr = ctypes.c_wchar_p()

            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folder_id),
                0,
                None,
                ctypes.byref(path_ptr),
            )

            if result == 0 and path_ptr.value:
                path = Path(path_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                return path

        except Exception as exc:
            print(
                f"[mrsl_mda_dwnldr] WARNING: could not locate Downloads folder: {exc}",
                flush=True,
            )

    return Path.home() / "Downloads"


DOWNLOADS_DIR = get_downloads_folder()
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

print(
    f"[mrsl_mda_dwnldr] downloads will be saved to: {DOWNLOADS_DIR}",
    flush=True,
)

# ──────────────────────────────────────────────────────────────────────
# FFmpeg auto-detection
#
# On Windows, PATH inside a venv subprocess often differs from the shell
# where you confirmed `ffmpeg -version` works.  We resolve the absolute
# path once at startup so yt-dlp always finds it regardless of how the
# server was launched.
# ──────────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    # 1 — PyInstaller bundled FFmpeg
    if getattr(sys, "frozen", False):
        bundled_ffmpeg = Path(sys._MEIPASS) / "ffmpeg"
        if (bundled_ffmpeg / "ffmpeg.exe").exists():
            return str(bundled_ffmpeg)

    # 2 — Local project FFmpeg
    project_ffmpeg = Path(__file__).resolve().parent / "ffmpeg"
    if (project_ffmpeg / "ffmpeg.exe").exists():
        return str(project_ffmpeg)

    # 3 — Explicit override via environment variable
    env_loc = os.environ.get("FFMPEG_LOCATION", "").strip()
    if env_loc:
        p = Path(env_loc)
        directory = p if p.is_dir() else p.parent

        if (directory / "ffmpeg.exe").exists() or (directory / "ffmpeg").exists():
            return str(directory)

    # 4 — System PATH
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return str(Path(ffmpeg_bin).parent)

    # 5 — Windows fallback paths
    if sys.platform == "win32":
        candidates = [
            Path(r"C:\ffmpeg\bin"),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg",
            Path(os.environ.get("LOCALAPPDATA", r"C:\Users\user\AppData\Local"))
            / "Microsoft" / "WinGet" / "Packages"
            / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "ffmpeg-7.1.1-full_build" / "bin",
            Path(r"C:\ProgramData\chocolatey\bin"),
            Path(r"C:\tools\ffmpeg\bin"),
            Path(os.path.expanduser("~")) / "scoop" / "shims",
        ]

        for candidate in candidates:
            if (candidate / "ffmpeg.exe").exists():
                return str(candidate)

    raise RuntimeError(
        "ffmpeg not found. Install it and make sure it is on your PATH, "
        "or set the FFMPEG_LOCATION environment variable to its directory."
    )
    
try:
    FFMPEG_DIR = _find_ffmpeg()
    print(
        f"[mrsl_mda_dwnldr] ffmpeg found at: {FFMPEG_DIR}",
        flush=True,
    )
except RuntimeError as _ffmpeg_err:
    FFMPEG_DIR = ""
    print(
        f"[mrsl_mda_dwnldr] WARNING: {_ffmpeg_err}",
        flush=True,
    )

# ─────────────────────────────────────────────────────────────
# In-memory job store
# Each entry: { status, progress, speed, eta, filename, error }
# Keyed by a UUID job_id generated at request time.
# ─────────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}


# ─────────
# Helpers
# ─────────

def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are unsafe in filenames across
    Windows, macOS, and Linux.
    """
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:200]  # cap length to avoid filesystem limits


def build_ydl_opts(job_id: str, download_type: str, audio_format: str) -> dict:
    """
    Build the yt-dlp options dictionary for the requested job.

    - Video  → best video + audio merged into MP4 via FFmpeg
    - Audio  → best audio quality, converted to the chosen format via FFmpeg
    """

    def progress_hook(d: dict) -> None:
        """
        Called by yt-dlp on each chunk. Updates the shared job store so
        the /api/progress endpoint can relay live feedback to the browser.
        """
        job = jobs.get(job_id)
        if job is None:
            return

        status = d.get("status")

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            progress = round((downloaded / total) * 100, 1) if total else 0

            job.update(
                {
                    "status": "downloading",
                    "progress": progress,
                    "speed": d.get("_speed_str", "").strip(),
                    "eta": d.get("_eta_str", "").strip(),
                }
            )

        elif status == "finished":
            # yt-dlp fires "finished" after each fragment/stream; FFmpeg
            # post-processing happens afterwards, so we show a transitional state.
            job.update({"status": "processing", "progress": 99})

        elif status == "error":
            job.update({"status": "error", "error": "yt-dlp reported a download error."})

    # ── shared base options ──
    if not FFMPEG_DIR:
        raise RuntimeError(
            "ffmpeg was not found at startup.  Install ffmpeg and add it to "
            "your PATH (or set the FFMPEG_LOCATION environment variable), "
            "then restart the server."
        )

    opts: dict = {
        "outtmpl": str(DOWNLOADS_DIR / "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        # Absolute directory resolved at startup – works even when the venv
        # subprocess does not inherit the interactive shell's PATH.
        "ffmpeg_location": FFMPEG_DIR,
    }

    if download_type == "video":
        # ── Video: best streams merged into MP4 ──
        opts.update(
            {
                # Prefer best combined stream; fall back to separate video+audio
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
                "postprocessors": [
                    {
                        "key": "FFmpegVideoConvertor",
                        "preferedformat": "mp4",
                    }
                ],
            }
        )
    else:
        # ── Audio: best quality, converted to the requested codec ──
        codec_map = {
            "mp3": "mp3",
            "wav": "wav",
            "ogg": "vorbis",
        }
        codec = codec_map.get(audio_format, "mp3")

        opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": codec,
                        "preferredquality": "0",  # VBR best quality
                    }
                ],
            }
        )

    return opts


# ───────────────────
# Background worker
# ───────────────────

def run_download(job_id: str, url: str, download_type: str, audio_format: str) -> None:
    """
    Execute the yt-dlp download in a background thread so the Flask
    response can return immediately and progress is polled separately.
    """
    job = jobs[job_id]
    try:
        opts = build_ydl_opts(job_id, download_type, audio_format)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # After download+post-processing, determine the final filename
            if info:
                title = sanitize_filename(info.get("title", "media"))
                ext = "mp4" if download_type == "video" else audio_format
                job.update(
                    {
                        "status": "complete",
                        "progress": 100,
                        "filename": f"{title}.{ext}",
                    }
                )
            else:
                job.update({"status": "error", "error": "Could not retrieve media info."})

    except yt_dlp.utils.DownloadError as exc:
        job.update({"status": "error", "error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        job.update({"status": "error", "error": f"Unexpected error: {exc}"})


# ────────
# Routes
# ────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/supported")
def supported():
    return render_template("supported.html")
    
@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(
        Path(__file__).parent / "assets",
        filename
    )


@app.route("/api/info", methods=["POST"])
def get_info():
    """
    Fetch metadata (title, duration, thumbnail) for a URL without downloading.
    Called by the frontend when the user pastes a URL.
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Fetch only the flat playlist entry to keep things fast
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({"error": "Could not extract media information."}), 422

        # Duration: yt-dlp returns seconds as an integer
        duration_secs = info.get("duration")
        if duration_secs is not None:
            mins, secs = divmod(int(duration_secs), 60)
            hrs, mins = divmod(mins, 60)
            duration_str = (
                f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            )
        else:
            duration_str = "Unknown"

        return jsonify(
            {
                "title": info.get("title", "Unknown title"),
                "duration": duration_str,
                "thumbnail": info.get("thumbnail", ""),
                "uploader": info.get("uploader", ""),
            }
        )

    except yt_dlp.utils.DownloadError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/download", methods=["POST"])
def start_download():
    """
    Enqueue a download job and return its job_id immediately.
    The actual work runs in a daemon thread.
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    download_type = data.get("download_type", "video")          # "video" | "audio"
    audio_format = data.get("audio_format", "mp3")     # "mp3" | "wav" | "ogg"

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    if download_type not in ("video", "audio"):
        return jsonify({"error": "Invalid download type."}), 400

    if download_type == "audio" and audio_format not in ("mp3", "wav", "ogg"):
        return jsonify({"error": "Unsupported audio format."}), 400

    # Create job record before spawning the thread
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "speed": "",
        "eta": "",
        "filename": "",
        "error": "",
    }

    thread = threading.Thread(
        target=run_download,
        args=(job_id, url, download_type, audio_format),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def get_progress(job_id: str):
    """
    Return the current state of a job.
    The frontend polls this endpoint every second.
    """
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


# ────────────
# Entry point
# ────────────

def open_browser():
    time.sleep(1)
    webbrowser.open_new("http://127.0.0.1:5000")
    
    

if __name__ == "__main__":
    open_browser()
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )