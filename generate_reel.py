"""
On Est Tous d'Accord - Reel local (moteur de secours), sans musique ni voix
====================================================================================
Ce moteur de rendu LOCAL sert de filet de secours si l'API OpenAI n'est pas
disponible pour monter le reel du jour (voir generate_reel_openai.py, qui
tente le montage par OpenAI, et generate_reel_final.py, qui choisit entre les
deux puis ajoute la musique de fond ensuite dans les deux cas).

Simple diaporama des 3 mêmes visuels que le carrousel (La Pensée / La Parole /
CTA, voir generate_carousel.generate_reel_frames), avec un effet de zoom léger
sur chacun ("Ken Burns"). Produit une vidéo SILENCIEUSE : la musique est
ajoutée ensuite par generate_reel_final.py, jamais ici.

Utilisation en ligne de commande (test, vidéo silencieuse) :
    python generate_reel.py

Utilisation en import :
    from generate_reel import render_reel_local
    video_path = render_reel_local(topic_tag, thought_text, spoken_text, out_path,
                                    closing_line="On est tous d'accord ?")
"""

import os
import subprocess
import tempfile

from generate_carousel import generate_reel_frames

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


def render_reel_local(topic_tag, thought_text, spoken_text, out_path,
                       closing_line="On est tous d'accord ?"):
    """Fabrique la vidéo SILENCIEUSE (sans musique, ajoutée ensuite par
    generate_reel_final.py) à partir des 3 visuels de la scène (La Pensée,
    La Parole, CTA), avec un effet de zoom léger sur chacun. Renvoie out_path.
    Ne masque pas les erreurs : c'est à l'appelant de décider quoi faire en
    cas d'échec (voir le mécanisme de secours dans generate_reel_final.py)."""
    with tempfile.TemporaryDirectory() as tmp:
        frames_dir = os.path.join(tmp, "frames")
        frames = generate_reel_frames(topic_tag, thought_text, spoken_text, frames_dir, closing_line)

        clip_paths = []
        for i, frame_path in enumerate(frames):
            clip_path = os.path.join(tmp, f"clip_{i}.mp4")
            _make_zoom_clip(frame_path, SLIDE_DURATION, clip_path)
            clip_paths.append(clip_path)

        concat_list = os.path.join(tmp, "concat.txt")
        with open(concat_list, "w") as f:
            for c in clip_paths:
                f.write(f"file '{c}'\n")

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c", "copy", out_path],
            check=True, capture_output=True,
        )

    return out_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = render_reel_local(
        topic_tag="La réunion de trop",
        thought_text="Cette réunion aurait pu être un simple message.",
        spoken_text="Super réunion tout le monde, on est hyper alignés !",
        out_path=os.path.join(here, "reel_test", "silent.mp4"),
    )
    print("Vidéo silencieuse générée :", path)
