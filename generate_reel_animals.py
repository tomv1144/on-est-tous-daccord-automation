"""
ON EST TOUS D'ACCORD - Fabrication du reel (couple de Corgis + Golden Retriever)
====================================================================================
C'est ici que se construit la vidéo du jour, en 2 étapes, comme validé par le
test de preuve de concept (poc_animaux_test.py) que Tom a approuvé :

  1. invent_scene_plan() : un appel à l'API OpenAI (texte seul, function
     calling, comme generate_scene_illustrations.py pour Klarimo) invente les
     scènes précises et les poses à dessiner, à partir du thème/ambiance du
     jour décidé par Claude (voir content_engine.py). C'est OpenAI qui
     "réalise" la mise en scène concrète, jamais Claude : conforme à la
     demande explicite de Tom.
  2. render_reel() : génère chaque pose via l'API image d'OpenAI
     (endpoint /images/edits, modèle gpt-image-2), en partant TOUJOURS des
     images de référence des personnages (pour qu'ils restent reconnaissables
     d'une image à l'autre) et de la pose précédente de la même scène (pour
     garder le même décor/cadrage au sein d'une scène). Les poses sont
     ensuite enchaînées en fondu ("stop-motion") pour un vrai mouvement,
     puis une musique de fond générée par code est ajoutée.

PERSONNAGES : les images de référence ont été choisies par Tom lors du
"casting" (voir casting_personnages.py) et sont déjà dans ce dépôt, pas
besoin de les régénérer ni de les déplacer :
    casting_output/corgi_kawaii_chibi.png   (couple de Corgis, PRINCIPAUX)
    casting_output/golden_kawaii_chibi.png  (couple de Golden Retriever, SECONDAIRES)

IMPORTANT, DIFFÉRENCE AVEC KLARIMO ET L'ANCIEN FORMAT PENSÉE/PAROLE : il n'y a
PAS de moteur de secours local pour ce nouveau concept. L'ancien format pouvait
retomber sur un rendu Pillow basique si OpenAI était indisponible ; ici, tout
le concept repose sur les personnages dessinés par OpenAI, donc il n'existe
aucune alternative raisonnable si l'API échoue (clé absente, panne, quota,
crédit épuisé...). Dans ce cas, la fonction lève une exception, et c'est
tousdaccord_autopost.py qui doit alors ABANDONNER le cycle du jour (pas de
publication) plutôt que de publier autre chose à la place. C'est un choix
assumé : mieux vaut ne rien publier un jour donné que de publier un format
qui ne correspond plus du tout au concept.

Utilisation (depuis tousdaccord_autopost.py) :
    from generate_reel_animals import generate_reel_animals
    video_path = generate_reel_animals(theme_tag, mood_description, include_golden,
                                        out_dir, seed=3)
    # Lève une exception en cas d'échec : à l'appelant de décider de ne pas
    # publier ce cycle plutôt que de forcer un contenu de secours.
"""

import json
import mimetypes
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image

from generate_music import generate_background_music

HERE = os.path.dirname(os.path.abspath(__file__))

CHARACTER_REFERENCE = {
    "corgi": os.path.join(HERE, "casting_output", "corgi_kawaii_chibi.png"),
    "golden": os.path.join(HERE, "casting_output", "golden_kawaii_chibi.png"),
}

API_BASE = "https://api.openai.com/v1"
OPENAI_TEXT_MODEL = "gpt-6-astra"
OPENAI_IMAGE_MODEL = "gpt-image-2"

SIZE = "1024x1536"    # format portrait, cohérent avec un Reel vertical
QUALITY = "high"       # coût pas un problème pour Tom sur ce travail précis

FPS = 30
TARGET_DURATION_SECONDS = 65.0  # Tom : "les vidéos doivent durer au moins 1 minute"
TRANSITION_RATIO = 0.6          # durée du fondu = 60% de la durée d'affichage d'une pose
VIDEO_SIZE = (1080, 1920)

# Filet de sécurité si OpenAI renvoie très peu de poses malgré la consigne :
# le calcul de timing (voir _compute_timing) garantit déjà TARGET_DURATION_SECONDS
# quel que soit le nombre de poses, mais en dessous de ce seuil, chaque pose
# resterait affichée très longtemps et la vidéo ressemblerait à un diaporama
# plutôt qu'à un vrai mouvement : on le signale dans les journaux sans bloquer
# la publication pour autant.
MIN_RECOMMENDED_POSES = 28

STYLE_SUFFIX = (
    "Style: adorable 3D kawaii chibi render, oversized round head, tiny "
    "compact body, enormous sparkling round eyes, soft glossy smooth "
    "shading, like a cute 3D mobile game mascot character. Vertical "
    "portrait composition. Absolutely no text, no letters, no numbers, no "
    "logo, no watermark anywhere in the image."
)

CHARACTER_IDENTITY = {
    "corgi": (
        "the 'boy' Corgi (slightly bigger, wearing a simple navy blue "
        "collar) and the 'girl' Corgi (slightly smaller, with a small pink "
        "flower accessory behind one ear)"
    ),
    "golden": (
        "the 'boy' Golden Retriever (slightly bigger, wearing a simple "
        "forest green bandana around his neck) and the 'girl' Golden "
        "Retriever (slightly smaller, with a small yellow bow accessory "
        "behind one ear)"
    ),
}


# ---------------------------------------------------------------------------
# Étape 1 : invention des scènes et poses (API OpenAI, texte + function calling)
# ---------------------------------------------------------------------------

SCENE_PLAN_TOOL = {
    "type": "function",
    "name": "scene_plan",
    "description": (
        "Le découpage précis en scènes et poses d'un reel muet mettant en "
        "scène un couple de Corgis (et parfois un couple de Golden "
        "Retriever en personnages secondaires), à partir d'un thème et "
        "d'une ambiance donnés."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "setting": {
                            "type": "string",
                            "description": (
                                "Description en anglais du décor de cette scène "
                                "(lieu, lumière, ambiance), concrète et précise."
                            ),
                        },
                        "poses": {
                            "type": "array",
                            "minItems": 8,
                            "maxItems": 12,
                            "items": {"type": "string"},
                            "description": (
                                "8 à 12 actions/poses en anglais, décrivant une "
                                "petite progression fluide et cohérente au sein "
                                "de cette scène (pas des sauts brusques d'une "
                                "action à une autre sans rapport)."
                            ),
                        },
                    },
                    "required": ["setting", "poses"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["scenes"],
        "additionalProperties": False,
    },
    "strict": True,
}


def invent_scene_plan(theme_tag, mood_description, include_golden, api_key, timeout=90):
    """Demande à OpenAI d'imaginer le découpage en scènes/poses du jour.
    Ne masque pas les erreurs : c'est à l'appelant (generate_reel_animals) de
    décider quoi faire en cas d'échec (voir docstring du module : pas de
    moteur de secours pour ce concept)."""
    golden_instructions = (
        f"Le couple de Golden Retriever ({CHARACTER_IDENTITY['golden']}) "
        "apparaît AUJOURD'HUI, en personnages secondaires : ils rejoignent "
        "les Corgis dans une partie de l'histoire (par exemple une balade ou "
        "un pique-nique ensemble), mais les Corgis restent les personnages "
        "principaux de chaque scène."
        if include_golden
        else "Seul le couple de Corgis est présent aujourd'hui, aucun autre animal."
    )

    instructions = f"""
Tu es le réalisateur d'un reel muet et attendrissant pour "On Est Tous
D'Accord", mettant en scène un couple de chiens Corgis en 3D kawaii chibi
({CHARACTER_IDENTITY['corgi']}). {golden_instructions}

Thème du jour : {theme_tag}
Ambiance : {mood_description}

Découpe cette histoire en 3 à 5 petites scènes (des lieux/moments différents
qui s'enchaînent, comme les chapitres d'une petite histoire), chacune avec un
décor précis et 8 à 12 poses qui font progresser l'action pas à pas (pas de
sauts brusques : chaque pose doit être une suite naturelle de la précédente
au sein de la même scène). Vise environ 40 poses au total pour que la vidéo
finale dure confortablement plus d'une minute.

Aucun texte, logo, ou élément écrit ne doit être mentionné dans les
descriptions (la vidéo est purement visuelle, sans aucun texte à l'écran).
Toujours positif et mignon : jamais de danger, de tristesse, ou de détresse.
""".strip()

    payload = {
        "model": OPENAI_TEXT_MODEL,
        "input": instructions,
        "tools": [SCENE_PLAN_TOOL],
        "tool_choice": "required",
    }
    req = urllib.request.Request(
        f"{API_BASE}/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    for item in data.get("output", []):
        if item.get("type") == "function_call" and item.get("name") == "scene_plan":
            plan = json.loads(item["arguments"])
            scenes = plan.get("scenes") or []
            if not scenes:
                raise RuntimeError(f"OpenAI a renvoyé un plan de scènes vide : {plan}")
            total_poses = sum(len(s.get("poses") or []) for s in scenes)
            if total_poses < MIN_RECOMMENDED_POSES:
                print(
                    f"AVERTISSEMENT : seulement {total_poses} poses proposées par "
                    f"OpenAI (recommandé : au moins {MIN_RECOMMENDED_POSES}). La "
                    "vidéo restera au moins 1 minute (voir _compute_timing), mais "
                    "chaque pose sera affichée plus longtemps, donnant un rendu "
                    "un peu plus proche du diaporama que du mouvement fluide."
                )
            return scenes
    raise RuntimeError(f"Pas d'appel de fonction dans la réponse OpenAI : {data}")


# ---------------------------------------------------------------------------
# Étape 2 : génération des poses (API OpenAI, images)
# ---------------------------------------------------------------------------

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


def generate_posed_frame(reference_paths, pose_prompt, output_path, api_key, timeout=150):
    """Génère UNE pose à partir d'une ou plusieurs image(s) de référence
    (endpoint /images/edits). Ne masque pas les erreurs (voir docstring du
    module : aucun moteur de secours pour ce concept)."""
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


def _build_pose_prompt(setting_desc, action_desc, is_establishing, include_golden):
    identity = CHARACTER_IDENTITY["corgi"]
    if include_golden:
        identity += f", together with {CHARACTER_IDENTITY['golden']}"

    if is_establishing:
        lead = (
            f"Keep the exact same characters as in the reference image(s) "
            f"({identity}), 100% visually identical. New scene, "
        )
    else:
        lead = (
            "Reference images are provided: the original character "
            "reference(s) (for exact appearance) and the previous pose of "
            "this same scene (for the exact same setting/background and "
            "camera framing). Keep the characters 100% visually identical, "
            "and keep the same setting, "
        )
    return f"{lead}{setting_desc}. Now: {action_desc}. " + STYLE_SUFFIX


def _compute_timing(n_total_frames, target_duration=TARGET_DURATION_SECONDS, trans_ratio=TRANSITION_RATIO):
    """Calcule le temps d'affichage (hold) et de fondu (transition) de chaque
    pose pour que la vidéo dure TOUJOURS environ target_duration secondes,
    quel que soit le nombre de poses réellement reçu d'OpenAI. C'est ce qui
    garantit mécaniquement la consigne de Tom ("au moins 1 minute"), plutôt
    que de compter uniquement sur le respect du nombre de poses demandé."""
    if n_total_frames <= 1:
        return target_duration, 0.0
    denom = n_total_frames + trans_ratio * (n_total_frames - 1)
    hold = target_duration / denom
    trans = trans_ratio * hold
    return hold, trans


def _build_crossfade_video(frame_paths, out_path, fps=FPS, size=VIDEO_SIZE):
    hold_s, trans_s = _compute_timing(len(frame_paths))
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


def _probe_duration(video_path, default=TARGET_DURATION_SECONDS):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        )
        return max(1.0, float(result.stdout.strip()))
    except Exception:  # noqa: BLE001
        return default


def generate_reel_animals(theme_tag, mood_description, include_golden, out_dir, seed=0, api_key=None):
    """Fabrique le reel du jour (vidéo + musique). Renvoie le chemin de la
    vidéo finale. NE MASQUE PAS LES ERREURS (voir docstring du module en
    haut de ce fichier) : l'appelant doit abandonner le cycle du jour plutôt
    que de forcer une publication de secours si cette fonction échoue."""
    import os as _os
    api_key = api_key or _os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY n'est pas configurée : impossible de fabriquer ce reel.")

    os.makedirs(out_dir, exist_ok=True)

    print("Invention des scènes du jour (API OpenAI)...")
    scenes = invent_scene_plan(theme_tag, mood_description, include_golden, api_key)

    reference_paths = [CHARACTER_REFERENCE["corgi"]]
    if include_golden:
        reference_paths.append(CHARACTER_REFERENCE["golden"])

    frame_paths = []
    for scene_idx, scene in enumerate(scenes, start=1):
        setting = scene["setting"]
        poses = scene["poses"]
        print(f"Scène {scene_idx}/{len(scenes)} : {setting[:60]}...")
        scene_prev_path = None
        for pose_idx, action in enumerate(poses, start=1):
            is_establishing = (pose_idx == 1)
            prompt = _build_pose_prompt(setting, action, is_establishing, include_golden)
            refs = reference_paths if is_establishing else reference_paths + [scene_prev_path]
            frame_path = os.path.join(out_dir, f"frame_s{scene_idx}_{pose_idx:02d}.png")
            t0 = time.time()
            _generate_with_retry(generate_posed_frame, refs, prompt, frame_path, api_key)
            print(f"    -> {os.path.basename(frame_path)} ({time.time() - t0:.1f}s)")
            frame_paths.append(frame_path)
            scene_prev_path = frame_path

    print("Montage des poses en vidéo (fondu-enchaîné)...")
    silent_path = os.path.join(out_dir, "reel_silent.mp4")
    _build_crossfade_video(frame_paths, silent_path)

    duration = _probe_duration(silent_path)
    music_path = os.path.join(out_dir, "reel_music.wav")
    generate_background_music(duration_sec=duration, output_path=music_path, seed=seed)

    final_path = os.path.join(out_dir, "reel.mp4")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", silent_path, "-i", music_path,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-pix_fmt", "yuv420p", final_path,
        ],
        check=True, capture_output=True,
    )

    # Les images intermédiaires (poses + vidéo silencieuse + musique seule) ne
    # sont pas utiles à conserver dans le dépôt une fois la vidéo finale
    # assemblée : elles alourdiraient inutilement le dépôt GitHub au fil des
    # jours (contrairement au test, où Tom voulait justement les regarder).
    for p in frame_paths + [silent_path, music_path]:
        try:
            os.remove(p)
        except OSError:
            pass

    return final_path
