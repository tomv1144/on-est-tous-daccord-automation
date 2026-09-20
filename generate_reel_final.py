"""
On Est Tous d'Accord - Générateur de Reel final (vidéo courte, sans voix)
=========================================================
Fabrique la vidéo verticale finale et y ajoute une petite musique de fond
générée par code (aucune voix, aucun échantillon audio existant utilisé,
donc aucun risque de droit d'auteur).

Le rendu de la partie silencieuse (image + texte + mouvement) est tenté
d'abord via l'API OpenAI (voir generate_reel_openai.py), à la demande
explicite de Tom : c'est OpenAI qui "réalise" la vidéo, comme pour Klarimo.
Si ce n'est pas possible ce jour-là (clé absente, panne, quota, timeout,
réponse inattendue...), on bascule automatiquement sur le moteur de rendu
local (generate_reel.render_reel_local), qui reprend les mêmes personnages
et le même texte, sous une forme plus simple (diaporama à zoom). Dans les
deux cas, la musique de fond est ajoutée ensuite de la même façon : la
publication n'est donc jamais bloquée par une panne côté OpenAI.

Utilisation en import (depuis tousdaccord_autopost.py) :
    from generate_reel_final import generate_reel_final
    video_path = generate_reel_final(topic_tag, thought_text, spoken_text,
                                      out_dir, seed=3, closing_line="On est tous d'accord ?")
"""

import os
import subprocess
import tempfile

from generate_reel_openai import generate_reel_openai
from generate_reel import render_reel_local
from generate_music import generate_background_music


def generate_reel_final(topic_tag, thought_text, spoken_text, out_dir, seed=0,
                         closing_line="On est tous d'accord ?"):
    """Ne laisse dans out_dir QUE la vidéo finale (reel.mp4) : les fichiers
    intermédiaires (vidéo silencieuse, musique) sont fabriqués dans un
    dossier temporaire et supprimés ensuite, pour ne pas alourdir
    inutilement le dépôt GitHub."""
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        silent_video = os.path.join(tmp, "silent.mp4")

        rendered = None
        try:
            rendered = generate_reel_openai(
                topic_tag, thought_text, spoken_text, closing_line, silent_video,
            )
        except Exception as exc:  # noqa: BLE001 - jamais bloquant, voir docstring du module
            print(f"AVERTISSEMENT : rendu OpenAI a levé une exception inattendue ({exc}). Repli local.")
            rendered = None

        if rendered:
            print("Reel rendu par l'API OpenAI.")
        else:
            print("Rendu OpenAI indisponible ce cycle -> rendu local (generate_reel.py).")
            render_reel_local(topic_tag, thought_text, spoken_text, silent_video,
                               closing_line=closing_line)

        total_duration = _probe_duration(silent_video)

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


def _probe_duration(video_path, default=10.0):
    """Lit la durée réelle de la vidéo silencieuse via ffprobe. En cas
    d'échec (fichier corrompu, ffprobe absent...), renvoie une durée par
    défaut raisonnable plutôt que de bloquer toute la génération du reel."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        )
        return max(1.0, float(result.stdout.strip()))
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : impossible de lire la durée de la vidéo ({exc}), valeur par défaut utilisée.")
        return default


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = generate_reel_final(
        topic_tag="La réunion de trop",
        thought_text="Cette réunion aurait pu être un simple message.",
        spoken_text="Super réunion tout le monde, on est hyper alignés !",
        out_dir=os.path.join(here, "reel_test"),
        seed=2,
    )
    print("Reel généré :", path)
