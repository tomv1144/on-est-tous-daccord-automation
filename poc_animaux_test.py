"""
On Est Tous d'Accord - TEST (preuve de concept) du nouveau concept "couples d'animaux"
====================================================================================
CECI N'EST PAS LE PIPELINE FINAL. C'est un petit script de test, à lancer une
seule fois à la main, pour que Tom puisse VOIR un exemple concret avant de
valider l'approche technique retenue pour le nouveau concept "couples
d'animaux mignons" (Corgis + Golden Retrievers), comme demandé explicitement :
"Je veux voir un exemple avant de valider".

CE QUE CE TEST VÉRIFIE (les deux points bloquants du nouveau concept) :
1. Peut-on garder les MÊMES personnages (mêmes chiens, reconnaissables) d'une
   image à l'autre ? -> on génère UNE image de référence du couple de Corgis,
   puis on la redonne à OpenAI à chaque nouvelle image en lui demandant de
   garder exactement les mêmes personnages, juste dans une autre pose.
2. Peut-on obtenir un vrai MOUVEMENT (pas juste un zoom sur une image figée) ?
   -> on génère plusieurs poses différentes d'une même petite scène (les deux
   Corgis qui se câlinent), puis on les enchaîne en fondu ("stop-motion"),
   la même technique déjà utilisée pour Klarimo et pour les anciennes vidéos
   La Pensée / La Parole.

POURQUOI PAS SORA (l'outil vidéo d'OpenAI) : vérifié le 22/09/2026, l'API Sora
d'OpenAI ferme définitivement le 24/09/2026 (dans 2 jours). Ce n'est donc pas
une option utilisable maintenant. La solution testée ici (images fixes
enchaînées) est la seule voie actuellement disponible pour avoir à la fois des
personnages fixes ET du mouvement.

IMPORTANT SUR LE COÛT : ce test génère 7 images au total (1 image de référence
+ 6 poses) en qualité "high". Tom a indiqué que le coût n'est pas un problème
pour ce travail précis, donc la qualité est volontairement poussée pour bien
juger du résultat.

Utilisation (voir le workflow GitHub .github/workflows/poc_test.yml, à lancer
à la main depuis l'onglet "Actions" de GitHub) :
    python poc_animaux_test.py
Résultat, dans le dossier poc_test_output/ :
    - reference_corgi_couple.png       (l'image de référence des 2 Corgis)
    - frame_01.png à frame_06.png      (les 6 poses générées à partir de la référence)
    - poc_corgis_test_silent.mp4       (les poses enchaînées en fondu, sans musique)
    - poc_corgis_test.mp4              (la même vidéo, avec musique de fond ajoutée)
"""

import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image

from generate_music import generate_background_music

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "poc_test_output")

API_BASE = "https://api.openai.com/v1"
OPENAI_IMAGE_MODEL = "gpt-image-2"

SIZE = "1024x1536"       # format portrait, cohérent avec un Reel vertical
QUALITY = "high"          # coût pas un problème pour ce test, on privilégie le rendu

FPS = 30
HOLD_SECONDS = 0.55        # temps où chaque pose reste "figée" à l'écran
TRANSITION_SECONDS = 0.35  # durée du fondu-enchaîné entre deux poses
VIDEO_SIZE = (1080, 1920)  # format Reel final

STYLE_SUFFIX = (
    "Style: adorable 3D Pixar/Disney-like animated illustration, soft rounded "
    "shapes, big expressive round eyes, warm soft studio lighting, smooth "
    "clean render like a still from a 3D animated movie. Vertical portrait "
    "composition. Simple soft-colored plain background (no scenery clutter). "
    "Absolutely no text, no letters, no numbers, no logo, no watermark "
    "anywhere in the image."
)

REFERENCE_PROMPT = (
    "A cute couple of Corgi dogs, full body, sitting close together side by "
    "side on a simple soft cushion. One is the 'boy' Corgi (slightly bigger, "
    "wearing a simple navy blue collar) and the other is the 'girl' Corgi "
    "(slightly smaller, with a small pink flower accessory behind one ear), "
    "so they stay easy to tell apart in every future image. Both facing "
    "forward, friendly happy expression, tails visible. "
    + STYLE_SUFFIX
)

# Une petite séquence de poses qui raconte un instant tout simple (un câlin sur
# un canapé), pensée pour donner un mouvement progressif et fluide une fois
# enchaînée en fondu, plutôt que 6 poses sans rapport entre elles.
POSE_PROMPTS = [
    (
        "Keep the exact same two Corgi characters as in the reference image "
        "(same colors, same collar, same flower accessory, same faces, 100% "
        "visually identical dogs), redraw them in this new pose: both Corgis "
        "sitting side by side on a cozy couch, looking forward, relaxed. "
        + STYLE_SUFFIX
    ),
    (
        "Keep the exact same two Corgi characters as in the reference image, "
        "100% visually identical, redraw them in this new pose: the boy Corgi "
        "turns his head to look at the girl Corgi, both smiling softly. "
        + STYLE_SUFFIX
    ),
    (
        "Keep the exact same two Corgi characters as in the reference image, "
        "100% visually identical, redraw them in this new pose: the boy Corgi "
        "leans in and gently nuzzles the girl Corgi's cheek, eyes half closed, "
        "cozy and affectionate. " + STYLE_SUFFIX
    ),
    (
        "Keep the exact same two Corgi characters as in the reference image, "
        "100% visually identical, redraw them in this new pose: the girl "
        "Corgi rests her head on the boy Corgi's shoulder, both eyes gently "
        "closed, very cozy. " + STYLE_SUFFIX
    ),
    (
        "Keep the exact same two Corgi characters as in the reference image, "
        "100% visually identical, redraw them in this new pose: both Corgis "
        "cuddled up together in a tight little hug, tails wagging happily, "
        "big joyful smiles. " + STYLE_SUFFIX
    ),
    (
        "Keep the exact same two Corgi characters as in the reference image, "
        "100% visually identical, redraw them in this new pose: both Corgis "
        "settled and sleepy, cuddled together, eyes fully closed, peaceful "
        "contented expression. " + STYLE_SUFFIX
    ),
]


def _multipart_body(fields, file_fields):
    """fields : dict de champs texte simples {nom: valeur}.
    file_fields : liste de tuples (nom_de_champ, chemin_de_fichier) -- le même
    nom_de_champ peut apparaître plusieurs fois (nécessaire pour envoyer
    PLUSIEURS images de référence : OpenAI attend le nom "image[]" répété une
    fois par image, voir la documentation de l'endpoint /images/edits)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(f"{value}\r\n".encode("utf-8"))
    for field_name, file_path in file_fields:
        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(file_bytes)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(parts)


def _save_image_from_response(data, output_path, timeout):
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Réponse OpenAI inattendue (pas de champ data) : {data}")

    if item.get("b64_json"):
        import base64
        image_bytes = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=timeout) as img_resp:
            image_bytes = img_resp.read()
    else:
        raise RuntimeError(f"Ni b64_json ni url dans la réponse OpenAI : {item}")

    with open(output_path, "wb") as f:
        f.write(image_bytes)
    return output_path


def generate_reference_image(prompt, output_path, api_key, timeout=120):
    """Étape 1 : génère l'image de référence des personnages, texte -> image
    (endpoint /images/generations, aucune image de départ)."""
    payload = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "size": SIZE,
        "quality": QUALITY,
        "n": 1,
    }
    req = urllib.request.Request(
        f"{API_BASE}/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _save_image_from_response(data, output_path, timeout)


def generate_posed_frame(reference_paths, pose_prompt, output_path, api_key, timeout=120):
    """Étape 2 : génère UNE nouvelle pose des MÊMES personnages, en repartant
    de la ou des image(s) de référence (endpoint /images/edits). NOTE
    technique importante : le paramètre "input_fidelity" (utile sur d'anciens
    modèles) ne doit PAS être envoyé pour gpt-image-2, sous peine d'erreur --
    ce modèle traite toujours les images fournies en haute fidélité par
    défaut, il n'y a donc rien à faire de plus ici."""
    fields = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": pose_prompt,
        "size": SIZE,
        "quality": QUALITY,
        "n": "1",
    }
    file_fields = [("image[]", p) for p in reference_paths]
    boundary, body = _multipart_body(fields, file_fields)
    req = urllib.request.Request(
        f"{API_BASE}/images/edits",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _save_image_from_response(data, output_path, timeout)


def _build_crossfade_video(frame_paths, out_path, fps=FPS, hold_s=HOLD_SECONDS,
                            trans_s=TRANSITION_SECONDS, size=VIDEO_SIZE):
    """Enchaîne les poses en fondu ('stop-motion'), exactement la même
    technique que _expand_to_frames dans klarimo_motion.py : chaque pose est
    affichée quelques instants (hold_s), puis on fond doucement vers la pose
    suivante (trans_s), plutôt qu'un simple cut ou un zoom sur une image
    figée."""
    imgs = [Image.open(p).convert("RGB").resize(size) for p in frame_paths]

    frames = []
    prev = None
    for img in imgs:
        if prev is not None and trans_s > 0:
            n_trans = max(1, int(fps * trans_s))
            for i in range(1, n_trans + 1):
                alpha = i / n_trans
                frames.append(Image.blend(prev, img, alpha))
        n_hold = max(1, int(fps * hold_s))
        for _ in range(n_hold):
            frames.append(img)
        prev = img

    with tempfile.TemporaryDirectory() as tmp:
        for idx, frame in enumerate(frames):
            frame.save(os.path.join(tmp, f"frame_{idx:05d}.png"), "PNG")
        subprocess.run(
            [
                "ffmpeg", "-y", "-framerate", str(fps),
                "-i", os.path.join(tmp, "frame_%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
            ],
            check=True, capture_output=True,
        )
    return out_path


def _probe_duration(video_path, default=6.0):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        )
        return max(1.0, float(result.stdout.strip()))
    except Exception:  # noqa: BLE001
        return default


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ERREUR : OPENAI_API_KEY n'est pas configurée dans l'environnement. Arrêt du test.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    print("Étape 1/3 : génération de l'image de référence du couple de Corgis...")
    reference_path = os.path.join(OUT_DIR, "reference_corgi_couple.png")
    t0 = time.time()
    try:
        generate_reference_image(REFERENCE_PROMPT, reference_path, api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"ERREUR génération image de référence ({e.code}) : {body}")
        sys.exit(1)
    print(f"  -> {reference_path} ({time.time() - t0:.1f}s)")

    print(f"Étape 2/3 : génération de {len(POSE_PROMPTS)} poses à partir de la référence...")
    frame_paths = [reference_path]  # la 1ère frame de la vidéo est la référence elle-même
    for i, pose_prompt in enumerate(POSE_PROMPTS, start=1):
        frame_path = os.path.join(OUT_DIR, f"frame_{i:02d}.png")
        t0 = time.time()
        try:
            generate_posed_frame([reference_path], pose_prompt, frame_path, api_key)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            print(f"ERREUR génération pose {i} ({e.code}) : {body}")
            sys.exit(1)
        print(f"  -> {frame_path} ({time.time() - t0:.1f}s)")
        frame_paths.append(frame_path)

    print("Étape 3/3 : montage des poses en vidéo (fondu-enchaîné) + musique...")
    silent_path = os.path.join(OUT_DIR, "poc_corgis_test_silent.mp4")
    _build_crossfade_video(frame_paths, silent_path)

    duration = _probe_duration(silent_path)
    music_path = os.path.join(OUT_DIR, "poc_test_music.wav")
    generate_background_music(duration_sec=duration, output_path=music_path, seed=1)

    final_path = os.path.join(OUT_DIR, "poc_corgis_test.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", silent_path, "-i", music_path,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-pix_fmt", "yuv420p", final_path,
        ],
        check=True, capture_output=True,
    )

    print()
    print("TEST TERMINÉ. Résultat dans poc_test_output/ :")
    print(f"  - {os.path.basename(reference_path)} (personnages de référence)")
    print(f"  - frame_01.png à frame_{len(POSE_PROMPTS):02d}.png (poses générées)")
    print(f"  - {os.path.basename(silent_path)} (poses enchaînées, sans musique)")
    print(f"  - {os.path.basename(final_path)} (vidéo finale du test, avec musique)")


if __name__ == "__main__":
    main()
