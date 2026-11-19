"""Az AtiVideo-AI önálló, tesztalkalmazása."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from renderer import FPS, MAX_SECONDS, MEDIA_FORMATS, SIZES, RenderError, decode_narration, render, run

VISUAL_TYPES = ["jpg", "jpeg", "png", "webp", "mp4", "mov", "mkv", "webm"]
MUSIC_TYPES = ["mp3", "wav", "ogg", "flac", "m4a", "aac"]
MAX_SCENES = 100
MAX_FILE_MB = 50
MAX_TOTAL_MB = 150
MB = 1024 * 1024


def save_upload(folder, upload, name):
    target = folder / (name + Path(upload.name).suffix.lower())
    target.write_bytes(upload.getbuffer())
    return target


def join_scenes(scenes, narration, aspect, folder):
    # Feldolgozás egyesével, így egyszerre csak egy forrásdekóder fut.
    decoded_voice = folder / "narration.wav"
    duration = decode_narration(narration, decoded_voice)
    frames, remainder = divmod(math.ceil(duration * FPS), len(scenes))
    if not frames:
        raise RenderError(
            f"Ennyi jelenethez legalább {len(scenes) / FPS:g} másodperces narrációt tölts fel."
        )

    width, height = SIZES[aspect]
    segments = []
    for index, scene in enumerate(scenes):
        frame_count = frames + (index < remainder)
        segment = folder / f"segment-{index}.mp4"
        filters = (
            f"setpts=PTS-STARTPTS,scale={width}:{height}:"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"fps={FPS},format=yuv420p,tpad=stop_mode=clone:stop={frame_count}"
        )
        run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-filter_threads", "2",
                "-threads", "2", "-protocol_whitelist", "file",
                "-format_whitelist", MEDIA_FORMATS, "-i", str(scene),
                "-map", "0:v:0", "-vf", filters, "-frames:v", str(frame_count),
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-bf", "0", "-threads", "2",
                str(segment),
            ],
            f"A(z) {index + 1}. jelenet nem dolgozható fel.",
            30,
        )
        segments.append(f"file '{segment.name}'")

    playlist = folder / "scenes.txt"
    playlist.write_text("\n".join(segments) + "\n", encoding="utf-8")
    joined = folder / "joined.mp4"
    run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat",
            "-protocol_whitelist", "file", "-safe", "1", "-i", str(playlist),
            "-c:v", "copy", str(joined),
        ],
        "A jelenetek összefűzése nem sikerült.",
        60,
    )
    return joined, decoded_voice


def add_audio(video, voice, music, output):
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video),
        "-f", "wav", "-i", str(voice),
    ]
    if music is None:
        command.extend(["-af", "apad", "-map", "0:v:0", "-map", "1:a:0"])
    else:
        command.extend([
            "-stream_loop", "-1", "-protocol_whitelist", "file",
            "-format_whitelist", MEDIA_FORMATS, "-i", str(music),
            "-filter_complex",
            "[1:a]apad[voice];[2:a]aresample=48000,aformat=channel_layouts=stereo,"
            "volume=0.15[music];[voice][music]amix=inputs=2:normalize=0,"
            "alimiter=limit=0.97:level=0:latency=1[mixed]",
            "-map", "0:v:0", "-map", "[mixed]",
        ])
    command.extend([
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
        "-movflags", "+faststart", str(output),
    ])
    run(command, "Nem sikerült a videó és a hang összefűzése.", 60)


def make_video(visuals, narration, music, aspect):
    with TemporaryDirectory(prefix="ativideo-test-") as directory:
        folder = Path(directory)
        scenes = [
            save_upload(folder, upload, f"scene-{index}")
            for index, upload in enumerate(visuals, start=1)
        ]
        voice = save_upload(folder, narration, "narration")
        soundtrack = save_upload(folder, music, "music") if music is not None else None
        output = folder / "ativideo.mp4"
        if len(scenes) > 3:
            joined, decoded_voice = join_scenes(scenes, voice, aspect, folder)
            add_audio(joined, decoded_voice, soundtrack, output)
        else:
            render(scenes, voice, soundtrack, aspect, True, 0.15, output)
        return output.read_bytes()


def main():
    st.set_page_config(page_title="AtiVideo-AI 2.0 – teszt", menu_items={})
    st.html("""
        <style>
        [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
        [data-testid="stFileUploaderDropzone"] button:not([aria-label]) { font-size: 0; }
        [data-testid="stFileUploaderDropzone"] button:not([aria-label]) p { font-size: 0; }
        [data-testid="stFileUploaderDropzone"] button:not([aria-label])::after {
            content: "Fájlok kiválasztása";
            font-size: 1rem;
        }
        [data-testid="stMainMenu"] { display: none; }
        </style>
    """)
    st.title("AtiVideo-AI 2.0")
    st.caption(f"Tömeges feltöltés · akár {MAX_SCENES} jelenet")
    st.write("A jelenetek feltöltési sorrendben kerülnek a videóba. A videó hosszát a narráció adja.")

    with st.form("video_inputs", border=False):
        st.caption(
            f"Képek: JPG, PNG, WebP. Videók: MP4, MOV, MKV, WebM. "
            f"Legfeljebb {MAX_FILE_MB} MB fájlonként és {MAX_TOTAL_MB} MB összesen."
        )
        visuals = st.file_uploader(
            f"Képek és videók (1–{MAX_SCENES} fájl)",
            type=VISUAL_TYPES,
            accept_multiple_files=True,
            max_upload_size=MAX_FILE_MB,
        )
        narration = st.file_uploader("MP3-narráció", type=["mp3"], max_upload_size=MAX_FILE_MB)
        st.caption(f"A narráció legfeljebb {MAX_SECONDS} másodperces lehet. A videók eredeti hangja kimarad.")
        music = st.file_uploader(
            "Háttérzene (opcionális)", type=MUSIC_TYPES, max_upload_size=MAX_FILE_MB
        )
        aspect = st.radio("Képarány", ["16:9", "9:16"], horizontal=True)
        submitted = st.form_submit_button("Automatikus videókészítés", type="primary")

    if submitted:
        st.session_state.pop("test_video", None)
        if not visuals or narration is None:
            st.warning("Tölts fel legalább egy képet vagy videót és egy MP3-narrációt.")
            return
        if len(visuals) > MAX_SCENES:
            st.error(f"Legfeljebb {MAX_SCENES} képet vagy videót tölthetsz fel.")
            return
        uploads = [*visuals, narration]
        if music is not None:
            uploads.append(music)
        if any(upload.size > MAX_FILE_MB * MB for upload in uploads):
            st.error(f"Egy fájl legfeljebb {MAX_FILE_MB} MB lehet.")
            return
        if sum(upload.size for upload in uploads) > MAX_TOTAL_MB * MB:
            st.error(f"A feltöltések együttes mérete legfeljebb {MAX_TOTAL_MB} MB lehet.")
            return
        try:
            with st.spinner("Készül a videó…"):
                st.session_state.test_video = make_video(visuals, narration, music, aspect)
        except RenderError as error:
            st.error(str(error))
        except OSError:
            st.error("A szerver nem tudta feldolgozni a fájlokat. Próbáld újra.")

    if video := st.session_state.get("test_video"):
        st.success("Elkészült a videó.")
        st.video(video)
        st.download_button("MP4 letöltése", video, "ativideo.mp4", "video/mp4")


if __name__ == "__main__":
    main()
