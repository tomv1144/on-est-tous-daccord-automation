"""
On Est Tous d'Accord - Rendu du Reel par l'API OpenAI (code interpreter)
====================================================================================
Demande à OpenAI de monter la vidéo verticale du jour ("La Pensée" / "La
Parole" / relance finale), à la demande explicite de Tom : comme pour
Klarimo, c'est OpenAI qui "réalise" la vidéo, avec une vraie liberté
créative sur le montage (animations, transitions, rythme), pas seulement le
diaporama à zoom fixe du moteur de secours local (voir generate_reel.py).

DIFFÉRENCE avec le module équivalent côté Klarimo (generate_video_openai.py) :
Klarimo n'a pas de personnage fixe, donc une illustration différente est
générée pour chaque post (voir generate_scene_illustrations.py côté Klarimo).
"On Est Tous d'Accord" a au contraire DEUX personnages fixes qui font
l'identité du compte (La Pensée, La Parole) : ils sont TOUJOURS les mêmes,
donc il n'y a rien à générer, seulement à fournir à OpenAI en pièces jointes
(voir ASSET_FILES ci-dessous) pour qu'il les intègre dans son montage, sans
jamais en inventer d'autres à la place.

IMPORTANT (vérifié dans la documentation OpenAI le 20/09/2026, voir aussi
generate_video_openai.py côté Klarimo) : le bac à sable de l'outil
"code_interpreter" n'a PAS ACCÈS À INTERNET. Il peut dessiner avec du code
(Pillow, ffmpeg), mais seulement à partir des fichiers qu'on lui fournit :
c'est pour ça que les personnages, le logo et les polices sont téléversés ici
avant l'appel, jamais laissés à son imagination.

Ce module ne lève JAMAIS d'exception : renvoie out_path en cas de succès,
None en cas d'échec (clé absente, panne, quota, timeout, réponse
inattendue...). generate_reel_final.py bascule alors automatiquement sur le
moteur de secours local (generate_reel.render_reel_local), qui produit un
rendu différent (diaporama à zoom) mais avec les mêmes personnages, la même
palette et le même texte.

Utilisation :
    from generate_reel_openai import generate_reel_openai
    chemin = generate_reel_openai(topic_tag, thought_text, spoken_text, closing_line,
                                   "/chemin/vers/reel_silent.mp4")
    # chemin vaut None si la génération a échoué (jamais d'exception)
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
CHAR_DIR = os.path.join(HERE, "characters")
LOGO_PATH = os.path.join(HERE, "avatar_mustard.png")
REFERENCE_PATH = os.path.join(HERE, "generate_carousel.py")

API_BASE = "https://api.openai.com/v1"
OPENAI_VIDEO_MODEL = "gpt-6-astra"

# Fichiers envoyés à OpenAI à CHAQUE appel : contrairement à Klarimo, rien
# ici ne change d'un post à l'autre (les deux personnages sont fixes), donc
# pas de liste dynamique à construire.
ASSET_FILES = [
    os.path.join(FONT_DIR, "Baloo2-ExtraBold.ttf"),
    os.path.join(FONT_DIR, "Nunito-Black.ttf"),
    os.path.join(FONT_DIR, "Nunito-Bold.ttf"),
    os.path.join(CHAR_DIR, "la_pensee.png"),
    os.path.join(CHAR_DIR, "la_parole.png"),
    LOGO_PATH,
    REFERENCE_PATH,
]

# Comme pour Klarimo : la doc OpenAI ne précise pas quelle valeur de "purpose"
# utiliser pour des fichiers destinés à un container code_interpreter.
UPLOAD_PURPOSES_TO_TRY = ("user_data", "assistants")


def _multipart_body(fields, file_field_name, file_path):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(f"{value}\r\n".encode("utf-8"))

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(parts)


def _upload_file(path, api_key, timeout):
    last_error = None
    for purpose in UPLOAD_PURPOSES_TO_TRY:
        boundary, body = _multipart_body({"purpose": purpose}, "file", path)
        req = urllib.request.Request(
            f"{API_BASE}/files", data=body, method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["id"]
        except urllib.error.HTTPError as e:
            last_error = f"{e.code} : {e.read().decode('utf-8', errors='ignore')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise RuntimeError(f"Echec televersement de {os.path.basename(path)} : {last_error}")


def _upload_files(paths, api_key, timeout):
    return [_upload_file(path, api_key, timeout) for path in paths]


def _build_instructions(topic_tag, thought_text, spoken_text, closing_line):
    return f"""
Tu es en charge du montage d'un Reel pour "On Est Tous d'Accord", un compte
Facebook/Instagram d'humour grand public construit autour du contraste entre
"La Pensée" (ce qu'on pense en silence) et "La Parole" (ce qu'on dit tout
haut, poli ou hypocrite). Utilise ton outil code_interpreter (Python, avec
Pillow et ffmpeg disponibles) pour produire UNE video verticale (1080x1920,
format mp4, SANS SON, sans voix) a partir du contenu ci-dessous.

Personnages OBLIGATOIRES, joints en pieces jointes, a integrer TELS QUELS
(ne dessine jamais d'autres personnages a la place, tu ne peux de toute
facon pas en generer, ton environnement d'execution n'a pas acces a
internet) :
- la_pensee.png : le personnage "La Pensee" (tete-nuage violette, pensive).
- la_parole.png : le personnage "La Parole" (tete-bulle de dialogue orange,
  qui sourit, un peu hypocrite).
- avatar_mustard.png : le logo du compte (badge jaune/moutarde), a faire
  apparaitre au moins une fois, par exemple en pied de page pres du nom
  "On Est Tous d'Accord".

Structure du contenu, dans cet ordre (le texte doit apparaitre a l'ecran tel
quel, ne le reformule pas, mais TU choisis le rythme, les transitions et les
mouvements) :
1. Scene "LA PENSEE" : le badge/tag "{topic_tag}", puis la phrase suivante en
   gros, puis le personnage la_pensee.png quelque part sur cette scene :
   "{thought_text}"
2. Scene "LA PAROLE" : le meme badge "{topic_tag}", puis la phrase suivante
   en gros (contraste net avec la scene precedente), puis le personnage
   la_parole.png quelque part sur cette scene :
   "{spoken_text}"
3. Scene finale (relance) : la phrase suivante en gros, puis les DEUX
   personnages affiches ensemble, puis le logo et le nom du compte :
   "{closing_line}"

Contraintes de marque a respecter (les seules obligatoires) :
- Palette : fond creme chaud (#F3EDE4), texte encre presque noir (#241A1B),
  badges gris chaud (#E6DDD5), coherente avec le fichier de reference joint.
- Polices jointes : Baloo2-ExtraBold pour les grosses phrases (La Pensee /
  La Parole / relance), Nunito-Black pour les badges/etiquettes, Nunito-Bold
  pour le texte plus petit (nom du compte, sous-titre).
- Ton : enleve, punchy, rythme rapide (c'est de l'humour grand public, pas
  une marque serieuse) : n'hesite pas a faire "rebondir" ou apparaitre les
  personnages avec un peu de caractere plutot qu'un simple zoom lent et fixe
  sur une image statique (c'est justement ce qu'on cherche a depasser).
- Les deux personnages ne doivent JAMAIS etre deformes au point de devenir
  meconnaissables (tu peux les faire bouger, apparaitre, rebondir, mais pas
  les redessiner).

Si tu veux un point de depart technique rapide, un fichier generate_carousel.py
est joint : il contient le rendu statique actuellement utilise pour le
carrousel (mise en page exacte, couleurs, polices). Tu peux t'en inspirer
pour la mise en page de chaque scene, l'adapter, ou t'en eloigner si tu as
une meilleure idee de montage pour ce contenu precis : ce n'est qu'une
reference, pas un moule a repliquer a l'identique image par image.

Une fois la video produite, elle doit etre le seul fichier .mp4 present dans
ton repertoire de sortie, pour que je puisse la recuperer automatiquement
ensuite.
""".strip()


def _find_output_file(response_json):
    try:
        for item in response_json.get("output", []):
            for content in item.get("content", []) or []:
                for annotation in content.get("annotations", []) or []:
                    if annotation.get("type") != "container_file_citation":
                        continue
                    filename = annotation.get("filename", "") or ""
                    if filename.lower().endswith(".mp4"):
                        return annotation.get("container_id"), annotation.get("file_id")
        return None
    except (AttributeError, TypeError):
        return None


def _retrieve_container_file(container_id, file_id, api_key, out_path, timeout,
                              attempts=4, wait_between=8):
    url = f"{API_BASE}/containers/{container_id}/files/{file_id}/content"
    last_error = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                file_bytes = resp.read()
            if file_bytes:
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(file_bytes)
                return out_path
            last_error = "reponse vide"
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < attempts:
            time.sleep(wait_between)
    print(f"AVERTISSEMENT : echec recuperation du fichier video OpenAI apres {attempts} essais : {last_error}")
    return None


def generate_reel_openai(topic_tag, thought_text, spoken_text, closing_line, out_path,
                          api_key=None, timeout=600):
    """Tente de faire assembler le Reel silencieux par l'API OpenAI. Ne leve
    JAMAIS d'exception : renvoie out_path en cas de succes, None en cas
    d'echec. L'appelant (generate_reel_final.py) doit alors basculer sur le
    moteur de secours local (generate_reel.render_reel_local)."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Rendu reel OpenAI : pas de OPENAI_API_KEY configuree, on saute cette etape.")
        return None

    try:
        file_ids = _upload_files(ASSET_FILES, api_key, timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec televersement des fichiers de reference vers OpenAI : {exc}")
        return None

    instructions = _build_instructions(topic_tag, thought_text, spoken_text, closing_line)
    payload = {
        "model": OPENAI_VIDEO_MODEL,
        "input": instructions,
        "tools": [
            {"type": "code_interpreter", "container": {"type": "auto", "file_ids": file_ids}}
        ],
    }
    req = urllib.request.Request(
        f"{API_BASE}/responses",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"AVERTISSEMENT : echec appel API OpenAI (responses, {e.code}) : {body}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : echec appel API OpenAI (responses) : {exc}")
        return None

    found = _find_output_file(data)
    if not found or not all(found):
        print("AVERTISSEMENT : aucun fichier .mp4 identifiable dans la reponse OpenAI.")
        return None
    container_id, file_id = found

    return _retrieve_container_file(container_id, file_id, api_key, out_path, timeout=90)


if __name__ == "__main__":
    result = generate_reel_openai(
        topic_tag="La réunion de trop",
        thought_text="Cette réunion aurait pu être un simple message.",
        spoken_text="Super réunion tout le monde, on est hyper alignés !",
        closing_line="On est tous d'accord ?",
        out_path=os.path.join(HERE, "openai_test", "reel_openai.mp4"),
    )
    print("Resultat :", result)
