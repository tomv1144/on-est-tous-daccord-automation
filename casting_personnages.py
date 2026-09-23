"""
On Est Tous d'Accord - CASTING (choix du style) des personnages Corgi et Golden
====================================================================================
Avant de reconstruire tout le pipeline automatique, ce petit script génère les
2 couples de personnages (le couple de Corgis, personnages PRINCIPAUX, et le
couple de Golden Retriever, personnages SECONDAIRES) dans 4 styles 3D
différents, pour que Tom choisisse le style qui lui plaît le plus, quitte à
prendre un style différent pour chaque race.

CE QUE CE SCRIPT NE FAIT PAS : il ne génère ni poses ni vidéo, uniquement des
images fixes de présentation ("character sheet"), une par race et par style
(8 images en tout : 4 styles x 2 couples). C'est volontairement plus rapide et
moins coûteux que le test de la semaine dernière (41 images) : il s'agit
seulement de choisir le LOOK des personnages avant d'aller plus loin.

Une fois les 8 images générées, le script les assemble automatiquement en une
seule planche récapitulative (grille annotée), pour que Tom puisse tout voir
d'un coup d'œil sans avoir à ouvrir 8 fichiers séparés.

Utilisation (voir le workflow GitHub .github/workflows/casting_test.yml, à
lancer à la main depuis l'onglet "Actions" de GitHub) :
    python casting_personnages.py
Résultat, dans le dossier casting_output/ :
    - corgi_<style>.png et golden_<style>.png pour chacun des 4 styles
    - planche_recap.png : la grille annotée avec les 8 images côte à côte
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "casting_output")
FONT_PATH = os.path.join(HERE, "fonts", "Baloo2-ExtraBold.ttf")

API_BASE = "https://api.openai.com/v1"
OPENAI_IMAGE_MODEL = "gpt-image-2"

SIZE = "1024x1536"   # format portrait, cohérent avec un Reel vertical
QUALITY = "high"      # coût pas un problème pour Tom sur ce travail précis

# Description des personnages (leurs "signes distinctifs", pour qu'on puisse
# les reconnaître facilement d'une image à l'autre une fois le style choisi).
CORGI_BOY = "the 'boy' Corgi, slightly bigger, wearing a simple navy blue collar"
CORGI_GIRL = "the 'girl' Corgi, slightly smaller, with a small pink flower accessory behind one ear"
GOLDEN_BOY = "the 'boy' Golden Retriever, slightly bigger, wearing a simple forest green bandana around his neck"
GOLDEN_GIRL = "the 'girl' Golden Retriever, slightly smaller, with a small yellow bow accessory behind one ear"

BASE_POSE = (
    "sitting close together side by side on a simple soft cushion, plain "
    "soft-colored background, both facing forward, friendly happy "
    "expression, tails visible, full body visible"
)

COMMON_SUFFIX = (
    "Vertical portrait composition. Absolutely no text, no letters, no "
    "numbers, no logo, no watermark anywhere in the image."
)

# Les 4 styles à comparer, tous en 3D (Tom a été explicite : "il faut que ça
# soit en 3D"), mais avec des degrés de stylisation très différents, pour
# vraiment donner le choix.
STYLES = {
    "kawaii_chibi": (
        "Ultra-kawaii chibi 3D render style: oversized round head, tiny "
        "compact body, enormous sparkling round eyes, soft glossy smooth "
        "shading, like a cute 3D mobile game mascot character."
    ),
    "pixar_realiste": (
        "Pixar/Disney feature-film 3D animation style: naturally "
        "proportioned dog body, softly stylized realistic fur texture, warm "
        "expressive eyes, cinematic soft studio lighting, like a beloved "
        "character from a 3D animated movie."
    ),
    "bold_bouncy": (
        "Bold, bouncy modern 3D animated-film style: vibrant saturated "
        "colors, smooth glossy rounded shapes, big glossy expressive eyes, "
        "playful energetic personality."
    ),
    "plush_pastel": (
        "Soft pastel plush-toy 3D render style: looks like an adorable "
        "stuffed animal brought to life, matte velvety fur texture, soft "
        "pastel color palette, extremely huggable and cozy look."
    ),
}


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


def generate_couple_image(prompt, output_path, api_key, timeout=120):
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


def _build_prompt(breed, char_a, char_b, style_desc):
    return (
        f"A cute couple of {breed} dogs, full body. One is {char_a}, the "
        f"other is {char_b}, so they stay easy to tell apart. {BASE_POSE}. "
        f"Style: {style_desc} {COMMON_SUFFIX}"
    )


def _build_recap_sheet(images_by_style, out_path, thumb_size=(360, 540), label_h=60):
    """Assemble les 8 images en une grille 4 lignes (styles) x 2 colonnes
    (Corgi | Golden), avec le nom du style écrit au-dessus de chaque ligne,
    pour que Tom puisse tout comparer d'un coup d'œil."""
    styles = list(images_by_style.keys())
    n_rows = len(styles)
    n_cols = 2
    margin = 20

    sheet_w = margin + n_cols * (thumb_size[0] + margin)
    sheet_h = margin + n_rows * (thumb_size[1] + label_h + margin)
    sheet = Image.new("RGB", (sheet_w, sheet_h), (245, 240, 232))
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype(FONT_PATH, 30)
        font_small = ImageFont.truetype(FONT_PATH, 22)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
        font_small = font

    col_titles = ["Corgi (personnages principaux)", "Golden Retriever (personnages secondaires)"]

    for row, style_name in enumerate(styles):
        y = margin + row * (thumb_size[1] + label_h + margin)
        draw.text((margin, y), style_name, fill=(40, 30, 25), font=font)
        y_img = y + label_h
        for col, key in enumerate(("corgi", "golden")):
            x = margin + col * (thumb_size[0] + margin)
            img_path = images_by_style[style_name][key]
            thumb = Image.open(img_path).convert("RGB").resize(thumb_size)
            sheet.paste(thumb, (x, y_img))
            if row == 0:
                draw.text((x, margin - 15), col_titles[col], fill=(40, 30, 25), font=font_small)

    sheet.save(out_path, "PNG")
    return out_path


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ERREUR : OPENAI_API_KEY n'est pas configurée dans l'environnement. Arrêt du casting.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    total = len(STYLES) * 2
    print(f"Ce casting va générer {total} images ({len(STYLES)} styles x 2 couples).")
    print()

    images_by_style = {}
    done = 0
    for style_name, style_desc in STYLES.items():
        images_by_style[style_name] = {}

        corgi_prompt = _build_prompt("Corgi", CORGI_BOY, CORGI_GIRL, style_desc)
        corgi_path = os.path.join(OUT_DIR, f"corgi_{style_name}.png")
        t0 = time.time()
        try:
            _generate_with_retry(generate_couple_image, corgi_prompt, corgi_path, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"ERREUR génération corgi_{style_name} : {exc}")
            sys.exit(1)
        done += 1
        print(f"  [{done}/{total}] corgi_{style_name}.png ({time.time() - t0:.1f}s)")
        images_by_style[style_name]["corgi"] = corgi_path

        golden_prompt = _build_prompt("Golden Retriever", GOLDEN_BOY, GOLDEN_GIRL, style_desc)
        golden_path = os.path.join(OUT_DIR, f"golden_{style_name}.png")
        t0 = time.time()
        try:
            _generate_with_retry(generate_couple_image, golden_prompt, golden_path, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"ERREUR génération golden_{style_name} : {exc}")
            sys.exit(1)
        done += 1
        print(f"  [{done}/{total}] golden_{style_name}.png ({time.time() - t0:.1f}s)")
        images_by_style[style_name]["golden"] = golden_path

    print()
    print("Montage de la planche récapitulative...")
    recap_path = os.path.join(OUT_DIR, "planche_recap.png")
    _build_recap_sheet(images_by_style, recap_path)

    print()
    print("CASTING TERMINÉ. Résultat dans casting_output/ :")
    print("  - corgi_<style>.png et golden_<style>.png pour chacun des 4 styles")
    print(f"  - {os.path.basename(recap_path)} (la grille récapitulative, à regarder en premier)")


if __name__ == "__main__":
    main()
