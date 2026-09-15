"""
On Est Tous d'Accord - Générateur de Reel (vidéo courte, sans voix)
=====================================================================
Prend les 3 images du contenu du jour (déjà utilisées pour le carrousel,
mais rendues au format vertical 9:16), les enchaîne avec un léger effet de
zoom (façon "Ken Burns"), ajoute une petite musique de fond générée par
code, et exporte une vidéo verticale prête à poster comme Reel.

Utilisation en ligne de commande (test) :
    python generate_reel.py

Utilisation en import (depuis le script d'automatisation) :
    from generate_reel import generate_reel
    video_path = generate_reel(topic_tag, thought_text, spoken_text, out_dir, seed=3)
"""

import os
import subprocess
import tempfile

from generate_carousel import generate_reel_frames
from generate_music import generate_background_music

FPS = 30
SLIDE_DURATION = 3.2  # secondes par diapo
ZOOM_END = 1.12        # zoom max atteint à la fin de chaque diapo


def _make_zoom_clip(image_path, duration, out_path, fps=FPS, zoom_end=ZOOM_END):
    n_frames = int(fps * duration)
    vf = (
        f"scale=1080:1920,"
        f"zoompan=z='min(zoom+{(zoom_end - 1) / n_frames:.6f},{zoom_end})':"
        f"d={n_frames}:s=1080x1920:fps={fps}"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-vf", vf, "-t", str(duration),
        "-pix_fmt", "yuv420p", out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def generate_reel(topic_tag, thought_text, spoken_text, out_dir, seed=0,
                   closing_line="On est tous d'accord ?"):
    """Ne laisse dans out_dir QUE la vidéo finale (reel.mp4) : les images
    intermédiaires par diapo sont fabriquées dans un dossier temporaire et
    supprimées ensuite, pour ne pas alourdir inutilement le dépôt GitHub."""
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        frames = generate_reel_frames(topic_tag, thought_text, spoken_text, frames_dir, closing_line)
        total_duration = SLIDE_DURATION * len(frames)

        clip_paths = []
        for i, frame_path in enumerate(frames):
            clip_path = os.path.join(tmp, f"clip_{i}.mp4")
            _make_zoom_clip(frame_path, SLIDE_DURATION, clip_path)
            clip_paths.append(clip_path)

        concat_list = os.path.join(tmp, "concat.txt")
        with open(concat_list, "w") as f:
            for c in clip_paths:
                f.write(f"file '{c}'\n")

        silent_video = os.path.join(tmp, "silent.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c", "copy", silent_video],
            check=True, capture_output=True,
        )

        music_path = os.path.join(tmp, "music.wav")
        generate_background_music(duration_sec=total_duration, output_path=music_path, seed=seed)

        final_path = os.path.join(out_dir, "reel.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-i", silent_video, "-i", music_path,
             "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-pix_fmt", "yuv420p", final_path],
            check=True, capture_output=True,
        )

    return final_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = generate_reel(
        topic_tag="La réunion de trop",
        thought_text="Cette réunion aurait pu être un simple message.",
        spoken_text="Super réunion tout le monde, on est hyper alignés !",
        out_dir=os.path.join(here, "reel_test"),
        seed=2,
    )
    print("Reel généré :", path)
