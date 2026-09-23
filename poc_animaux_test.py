"""
On Est Tous d'Accord - TEST (preuve de concept) du nouveau concept "couples d'animaux"
====================================================================================
CECI N'EST PAS LE PIPELINE FINAL. C'est un petit script de test, à lancer une
seule fois à la main, pour que Tom puisse VOIR un exemple concret avant de
valider l'approche technique retenue pour le nouveau concept "couples
d'animaux mignons" (Corgis + Golden Retrievers), comme demandé explicitement :
"Je veux voir un exemple avant de valider".

CE QUE CE TEST VÉRIFIE (les points bloquants du nouveau concept) :
1. Peut-on garder les MÊMES personnages (mêmes chiens, reconnaissables) d'une
   image à l'autre ? -> on génère UNE image de référence du couple de Corgis,
   puis on la redonne à OpenAI à chaque nouvelle image en lui demandant de
   garder exactement les mêmes personnages, juste dans une autre pose.
2. Peut-on obtenir un vrai MOUVEMENT (pas juste un zoom sur une image figée) ?
   -> on génère de nombreuses poses différentes, organisées en 4 petites
   scènes qui racontent une mini-histoire (câlin du matin, jeu, balade au
   parc, coucher de soleil), puis on les enchaîne en fondu ("stop-motion").
3. (ajouté suite au retour de Tom : "les vidéos doivent durer au moins 1
   minute") Peut-on tenir une durée d'au moins 1 minute sans que ça devienne
   répétitif ou que le cout/temps de génération explose ? -> on est passé de
   7 images (test précédent, ~6 secondes) à 41 images (1 référence + 40 poses
   réparties sur 4 scènes), ce qui donne environ 65 secondes. Voir la
   remarque sur le temps de génération plus bas.

COMMENT ON GARDE LES PERSONNAGES ET LE DÉCOR COHÉRENTS D'UNE POSE À L'AUTRE :
chaque nouvelle pose est générée en donnant DEUX images de référence à
OpenAI (endpoint /images/edits, qui accepte plusieurs images de référence
à la fois) : (1) l'image de référence originale des 2 Corgis, pour ne
jamais dériver sur les personnages, et (2) la pose précédente DE LA MÊME
SCÈNE, pour garder le même décor/cadrage d'une pose à l'autre au sein d'une
scène. Quand on change de scène (nouveau décor), on repart uniquement de
l'image de référence originale.

POURQUOI PAS SORA (l'outil vidéo d'OpenAI) : vérifié le 22/09/2026, l'API Sora
d'OpenAI ferme définitivement le 24/09/2026. Ce n'est donc pas une option
utilisable maintenant. La solution testée ici (images fixes enchaînées) est
la seule voie actuellement disponible pour avoir à la fois des personnages
fixes ET du mouvement.

IMPORTANT SUR LE COÛT ET LE TEMPS : ce test génère 41 images en qualité
"high" (2 images de référence par appel pour la plupart des poses, ce qui
est un peu plus lourd qu'une image de référence seule). Tom a indiqué que le
coût n'est pas un problème pour ce travail précis. En revanche, le TEMPS de
génération est réel : avec 41 appels à l'API, ce test prend environ 15 à 25
minutes à s'exécuter (contre 2 minutes pour la version précédente à 7
images). C'est une donnée importante à garder en tête pour le pipeline
automatique final : générer une vidéo de ce genre chaque jour prendra un
temps comparable, ce qui reste largement compatible avec une publication une
fois par jour, mais n'est plus une opération de quelques secondes.

Utilisation (voir le workflow GitHub .github/workflows/poc_test.yml, à lancer
à la main depuis l'onglet "Actions" de GitHub) :
    python poc_animaux_test.py
Résultat, dans le dossier poc_test_output/ :
    - reference_corgi_couple.png            (l'image de référence des 2 Corgis)
    - frame_scene1_01.png, frame_scene1_02.png, ... (poses de chaque scène)
    - poc_corgis_test_silent.mp4            (les poses enchaînées en fondu, sans musique)
    - poc_corgis_test.mp4                   (la même vidéo, avec musique de fond ajoutée)
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
HOLD_SECONDS = 1.0         # temps où chaque pose reste "figée" à l'écran
TRANSITION_SECONDS = 0.6   # durée du fondu-enchaîné entre deux poses
VIDEO_SIZE = (1080, 1920)  # format Reel final

STYLE_SUFFIX = (
    "Style: adorable 3D Pixar/Disney-like animated illustration, soft rounded "
    "shapes, big expressive round eyes, warm soft studio lighting, smooth "
    "clean render like a still from a 3D animated movie. Vertical portrait "
    "composition. Absolutely no text, no letters, no numbers, no logo, no "
    "watermark anywhere in the image."
)

REFERENCE_PROMPT = (
    "A cute couple of Corgi dogs, full body, sitting close together side by "
    "side on a simple soft cushion, plain soft-colored background. One is "
    "the 'boy' Corgi (slightly bigger, wearing a simple navy blue collar) "
    "and the other is the 'girl' Corgi (slightly smaller, with a small pink "
    "flower accessory behind one ear), so they stay easy to tell apart in "
    "every future image. Both facing forward, friendly happy expression, "
    "tails visible. " + STYLE_SUFFIX
)

# La mini-histoire du jour, en 4 scènes. Chaque scène a son décor (setting)
# et une liste de poses (actions) : la 1ère pose de chaque scène est une
# "pose d'établissement" du nouveau décor (ne référence que l'image de
# référence des personnages), les poses suivantes de la même scène
# référencent EN PLUS la pose précédente, pour garder le même décor/cadrage
# tout au long de la scène (voir _build_pose_prompt plus bas).
SCENES = [
    {
        "name": "scene1_calin_matin",
        "setting": "in a cozy living room, sitting together on a soft couch, warm morning light",
        "poses": [
            "sitting side by side on the couch, looking at each other and smiling",
            "the boy Corgi leans his head onto the girl Corgi's shoulder",
            "the girl Corgi playfully boops the boy Corgi's nose with her paw",
            "both Corgis laughing together, happy open-mouth pant expression",
            "the boy Corgi nuzzles into the girl Corgi's neck affectionately",
            "the girl Corgi rests her paw gently on the boy Corgi's paw",
            "both Corgis lean their foreheads together, eyes closed",
            "the boy Corgi wags his tail happily while looking at the girl Corgi",
            "both Corgis cuddled close in a tight hug, content smiles",
            "both Corgis settled quietly, eyes half-closed, peaceful and cozy",
        ],
    },
    {
        "name": "scene2_jeu",
        "setting": "standing together on a soft rug in the same cozy living room",
        "poses": [
            "both Corgis standing facing each other, tails up, playful stance",
            "the girl Corgi play-bows with her front paws down, inviting to play",
            "the boy Corgi hops forward playfully towards the girl Corgi",
            "both Corgis chasing each other in a small circle, big joyful smiles",
            "the boy Corgi playfully paws at the girl Corgi's tail",
            "both Corgis mid-jump, front paws off the ground, happy and energetic",
            "the girl Corgi playfully nips at the boy Corgi's ear",
            "both Corgis rolling together gently on the rug, laughing",
            "both Corgis pausing, panting happily, tongues out, looking at each other",
            "both Corgis sitting down together after playing, tails wagging, content",
        ],
    },
    {
        "name": "scene3_balade",
        "setting": "walking together outside on a sunny park path lined with flowers",
        "poses": [
            "both Corgis walking side by side on the sunny park path",
            "the girl Corgi sniffing a flower while the boy Corgi watches fondly",
            "both Corgis walking closely, shoulders touching",
            "the boy Corgi playfully carries a small stick in his mouth",
            "both Corgis running together happily through the grass",
            "the girl Corgi looks back over her shoulder at the boy Corgi, smiling",
            "both Corgis sitting together under a small tree, looking at the view",
            "the boy Corgi rests his head on the girl Corgi's back",
            "both Corgis playing together in a small pile of leaves",
            "both Corgis walking back together, close together, happy",
        ],
    },
    {
        "name": "scene4_coucher_soleil",
        "setting": "sitting together on a cozy window seat indoors, warm sunset light streaming in",
        "poses": [
            "both Corgis sitting together on the window seat, watching the sunset",
            "both Corgis watching the sunset together, peaceful expression",
            "the girl Corgi leans her head onto the boy Corgi's shoulder",
            "the boy Corgi settles closer to the girl Corgi, both relaxed",
            "both Corgis cuddled up close, eyes half-closed, content",
            "the girl Corgi nuzzles into the boy Corgi's chest",
            "both Corgis' eyes slowly closing, very sleepy and cozy",
            "both Corgis curled up together, almost asleep",
            "both Corgis fully asleep, cuddled together peacefully",
            "final peaceful shot, both Corgis fast asleep together, soft smiles, very cozy",
        ],
    },
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


def generate_posed_frame(reference_paths, pose_prompt, output_path, api_key, timeout=150):
    """Étape 2 : génère UNE nouvelle pose des MÊMES personnages, en repartant
    d'une ou plusieurs image(s) de référence (endpoint /images/edits, qui
    accepte jusqu'à 16 images de référence à la fois). NOTE technique
    importante : le paramètre "input_fidelity" (utile sur d'anciens modèles)
    ne doit PAS être envoyé pour gpt-image-2, sous peine d'erreur -- ce
    modèle traite toujours les images fournies en haute fidélité par défaut,
    il n'y a donc rien à faire de plus ici."""
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


def _generate_with_retry(fn, *args, attempts=2, wait_s=6, **kwargs):
    """Ce test dure maintenant 15-25 minutes (41 images) : on ne veut pas
    perdre tout le travail déjà fait à cause d'un simple raté ponctuel de
    l'API (ça arrive). On retente donc une fois avant d'abandonner pour de
    bon."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except urllib.error.HTTPError as e:
            last_error = f"{e.code} : {e.read().decode('utf-8', errors='ignore')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if attempt < attempts:
            print(f"    (tentative {attempt} échouée : {last_error} -- nouvel essai dans {wait_s}s)")
            time.sleep(wait_s)
    raise RuntimeError(last_error)


def _build_pose_prompt(setting_desc, action_desc, is_establishing):
    if is_establishing:
        lead = (
            "Keep the exact same two Corgi characters as in the reference image "
            "(same colors, same navy collar, same pink flower accessory, same "
            "faces, 100% visually identical dogs). New scene, "
        )
    else:
        lead = (
            "Two reference images are provided: the original character "
            "reference (for the dogs' exact appearance) and the previous pose "
            "of this same scene (for the exact same setting/background and "
            "camera framing). Keep the two Corgi characters 100% visually "
            "identical, and keep the same setting, "
        )
    return f"{lead}{setting_desc}. Now: {action_desc}. " + STYLE_SUFFIX


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


def _probe_duration(video_path, default=60.0):
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

    total_poses = sum(len(scene["poses"]) for scene in SCENES)
    predicted_duration = HOLD_SECONDS * (total_poses + 1) + TRANSITION_SECONDS * total_poses
    print(f"Ce test va générer 1 image de référence + {total_poses} poses "
          f"({len(SCENES)} scènes), pour une durée finale prévue d'environ "
          f"{predicted_duration:.0f} secondes.")
    print()

    print("Étape 1/3 : génération de l'image de référence du couple de Corgis...")
    reference_path = os.path.join(OUT_DIR, "reference_corgi_couple.png")
    t0 = time.time()
    try:
        _generate_with_retry(generate_reference_image, REFERENCE_PROMPT, reference_path, api_key)
    except Exception as exc:  # noqa: BLE001
        print(f"ERREUR génération image de référence : {exc}")
        sys.exit(1)
    print(f"  -> {reference_path} ({time.time() - t0:.1f}s)")

    print(f"Étape 2/3 : génération des {total_poses} poses ({len(SCENES)} scènes)...")
    frame_paths = [reference_path]  # la 1ère frame de la vidéo est la référence elle-même
    for scene in SCENES:
        print(f"  Scène : {scene['name']}")
        scene_prev_path = None
        for i, action in enumerate(scene["poses"], start=1):
            is_establishing = (i == 1)
            prompt = _build_pose_prompt(scene["setting"], action, is_establishing)
            refs = [reference_path] if is_establishing else [reference_path, scene_prev_path]
            frame_path = os.path.join(OUT_DIR, f"frame_{scene['name']}_{i:02d}.png")
            t0 = time.time()
            try:
                _generate_with_retry(generate_posed_frame, refs, prompt, frame_path, api_key)
            except Exception as exc:  # noqa: BLE001
                print(f"    ERREUR génération pose {i} de {scene['name']} : {exc}")
                sys.exit(1)
            print(f"    -> {os.path.basename(frame_path)} ({time.time() - t0:.1f}s)")
            frame_paths.append(frame_path)
            scene_prev_path = frame_path

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
    print(f"TEST TERMINÉ ({duration:.0f} secondes). Résultat dans poc_test_output/ :")
    print(f"  - {os.path.basename(reference_path)} (personnages de référence)")
    print(f"  - frame_<scene>_<numéro>.png ({total_poses} poses générées)")
    print(f"  - {os.path.basename(silent_path)} (poses enchaînées, sans musique)")
    print(f"  - {os.path.basename(final_path)} (vidéo finale du test, avec musique)")


if __name__ == "__main__":
    main()
