"""Az AtiVideo-AI önálló, háromjelenetes tesztalkalmazása."""

from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from renderer import MAX_SECONDS, RenderError, render

VISUAL_TYPES = ["jpg", "jpeg", "png", "webp", "mp4", "mov", "mkv", "webm"]
MUSIC_TYPES = ["mp3", "wav", "ogg", "flac", "m4a", "aac"]
MAX_FILE_MB = 50
MAX_TOTAL_MB = 150
MB = 1024 * 1024


def save_upload(folder, upload, name):
    target = folder / (name + Path(upload.name).suffix.lower())
    target.write_bytes(upload.getbuffer())
    return target


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
        render(scenes, voice, soundtrack, aspect, True, 0.15, output)
        return output.read_bytes()


def main():
    st.set_page_config(page_title="AtiVideo-AI 2.0 – teszt", menu_items={})
    st.html("""
        <style>
        [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
        [data-testid="stFileUploaderDropzone"] button { font-size: 0; }
        [data-testid="stFileUploaderDropzone"] button p { font-size: 0; }
        [data-testid="stFileUploaderDropzone"] button::after {
            content: "Fájl kiválasztása";
            font-size: 1rem;
        }
        [data-testid="stMainMenu"] { display: none; }
        </style>
    """)
    st.title("AtiVideo-AI 2.0")
    st.caption("Háromjelenetes tesztalkalmazás")
    st.write("A jelenetek számozott sorrendben kerülnek a videóba. A videó hosszát a narráció adja.")

    with st.form("video_inputs", border=False):
        st.caption(
            f"Képek: JPG, PNG, WebP. Videók: MP4, MOV, MKV, WebM. "
            f"Legfeljebb {MAX_FILE_MB} MB fájlonként és {MAX_TOTAL_MB} MB összesen."
        )
        visuals = [
            st.file_uploader(
                f"{number}. jelenet (kép vagy videó)",
                type=VISUAL_TYPES,
                key=f"scene_{number}",
                max_upload_size=MAX_FILE_MB,
            )
            for number in range(1, 4)
        ]
        narration = st.file_uploader("MP3-narráció", type=["mp3"], max_upload_size=MAX_FILE_MB)
        st.caption(f"A narráció legfeljebb {MAX_SECONDS} másodperces lehet. A videók eredeti hangja kimarad.")
        music = st.file_uploader(
            "Háttérzene (opcionális)", type=MUSIC_TYPES, max_upload_size=MAX_FILE_MB
        )
        aspect = st.radio("Képarány", ["16:9", "9:16"], horizontal=True)
        submitted = st.form_submit_button("Automatikus videókészítés", type="primary")

    if submitted:
        st.session_state.pop("test_video", None)
        if any(upload is None for upload in visuals) or narration is None:
            st.warning("Tölts fel mindhárom jelenethez fájlt és adj meg egy MP3-narrációt.")
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
