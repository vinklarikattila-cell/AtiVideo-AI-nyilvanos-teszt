"""A feltöltött média összeállítása FFmpeg segítségével."""

import math
from pathlib import Path
import subprocess
import wave

FPS = 25
MAX_SECONDS = 180
MAX_VISUALS = 12
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280)}
MEDIA_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,wav,ogg,flac,aac,image2,png_pipe,jpeg_pipe,webp_pipe"


class RenderError(Exception):
    """A felületen megjeleníthető feldolgozási hiba."""


def run(command, error_message, timeout):
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=timeout
        ).stdout
    except FileNotFoundError as exc:
        raise RenderError("A szerveren szükség van az FFmpeg programra.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("A feldolgozás túllépte az időkorlátot.") from exc
    except subprocess.CalledProcessError as exc:
        raise RenderError(error_message) from exc


def decode_narration(source, target):
    # A dekódolt minták hossza nem tartalmazza az MP3 kódolási kitöltését.
    run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "mp3", "-i", str(source),
         "-map", "0:a:0", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
         "-t", str(MAX_SECONDS + 1), str(target)],
        "A narrációs MP3 nem olvasható.",
        30,
    )
    with wave.open(str(target), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    if not 0 < duration <= MAX_SECONDS:
        raise RenderError(f"A narráció hossza legfeljebb {MAX_SECONDS} másodperc lehet.")
    return duration


def seconds(frames):
    return f"{frames / FPS:.6f}"


def render(visuals, narration, music, aspect, dissolve, music_volume, output):
    if not 1 <= len(visuals) <= MAX_VISUALS:
        raise RenderError(f"Adj hozzá 1–{MAX_VISUALS} képet vagy videót.")

    width, height = SIZES[aspect]
    decoded_voice = Path(output).with_suffix(".narration.wav")
    duration = decode_narration(narration, decoded_voice)
    # Az utolsó videókocka fedje le a narráció végét.
    total = max(1, math.ceil(duration * FPS))
    count = len(visuals)
    if total < count:
        raise RenderError("A narráció túl rövid ennyi képhez vagy videóhoz.")

    cuts = count - 1
    transition = min(12, total // count // 2) if dissolve and cuts else 0
    base, remainder = divmod(total + cuts * transition, count)
    lengths = [base + (index < remainder) for index in range(count)]

    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-filter_complex_threads", "2"]
    filters = []
    for index, (path, frames) in enumerate(zip(visuals, lengths)):
        command.extend(["-threads", "2", "-protocol_whitelist", "file",
                        "-format_whitelist", MEDIA_FORMATS, "-i", str(path)])
        pixel_format = "yuv444p" if transition else "yuv420p"
        filters.append(
            f"[{index}:v:0]setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"fps={FPS},format={pixel_format},"
            f"tpad=stop_mode=clone:stop={frames},trim=end_frame={frames},"
            f"fps={FPS}[v{index}]"
        )

    command.extend(["-f", "wav", "-i", str(decoded_voice)])
    video = "[v0]"
    if transition:
        offset = 0
        for index in range(1, count):
            offset += lengths[index - 1] - transition
            previous = video
            video = f"[x{index}]"
            filters.append(
                f"{previous}[v{index}]xfade=transition=fade:"
                f"duration={seconds(transition)}:offset={seconds(offset)},"
                f"fps={FPS}{video}"
            )
    elif cuts:
        inputs = "".join(f"[v{i}]" for i in range(count))
        video = "[joined]"
        filters.append(f"{inputs}concat=n={count}:v=1:a=0{video}")

    audio_end = seconds(total)
    filters.append(
        f"[{count}:a:0]aresample=48000,aformat=channel_layouts=stereo,"
        f"apad,atrim=duration={audio_end}[voice]"
    )
    audio = "[voice]"
    if music:
        command.extend(["-stream_loop", "-1", "-protocol_whitelist", "file",
                        "-format_whitelist", MEDIA_FORMATS, "-i", str(music)])
        filters.append(
            f"[{count + 1}:a:0]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={music_volume:.2f},atrim=duration={audio_end}[music]"
        )
        filters.append(
            "[voice][music]amix=inputs=2:duration=first:normalize=0,"
            "alimiter=limit=0.97:level=0:latency=1[mixed]"
        )
        audio = "[mixed]"

    command.extend([
        "-filter_complex", ";".join(filters), "-map", video, "-map", audio,
        "-t", audio_end, "-r", str(FPS), "-c:v", "libx264", "-threads", "2",
        "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output),
    ])
    run(command, "Az összeállítás sikertelen. Ellenőrizd, hogy a fájlok lejátszhatók-e.", 240)
    if not Path(output).is_file() or Path(output).stat().st_size == 0:
        raise RenderError("Az MP4-fájl nem készült el.")


if __name__ == "__main__":
    # Keep the existing Streamlit Cloud entry point working.
    from app import main

    main()
