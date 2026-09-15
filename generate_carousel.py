"""
On Est Tous d'Accord - Générateur de carrousel (Pensée vs Parole)
==================================================================
Crée les 3 images d'un carrousel Instagram/Facebook :
  1. "La Pensée"  -> ce que tout le monde pense en silence
  2. "La Parole"  -> ce que tout le monde dit à voix haute (le contraste)
  3. CTA          -> logo + relance ("On est tous d'accord ?")

Format 1080x1350 (4:5), le format recommandé pour les posts/carrousels
Instagram en 2026.

Utilisation en ligne de commande (test) :
    python generate_carousel.py

Utilisation en import (depuis le script d'automatisation) :
    from generate_carousel import generate_carousel
    paths = generate_carousel(topic_tag, thought_text, spoken_text, out_dir)
"""

import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
CHAR_DIR = os.path.join(HERE, "characters")
LOGO_PATH = os.path.join(HERE, "avatar_mustard.png")

W, H = 1080, 1350


def set_canvas(w, h):
    """Change la taille de la toile utilisée par toutes les fonctions de ce
    fichier. Sert à réutiliser exactement la même mise en page pour le
    carrousel (1080x1350) et pour les images du reel (1080x1920)."""
    global W, H
    W, H = w, h

# --- Palette (calée sur l'illustration ChatGPT des personnages) ---
BG = (243, 237, 228)       # #F3EDE4 fond crème
CHIP_BG = (230, 221, 213)  # #E6DDD5 fond du badge/tag
INK = (36, 26, 27)         # #241A1B texte principal
INK_SOFT = (110, 98, 92)   # texte secondaire, plus doux
BORDER = (223, 213, 203)   # liseré du cadre arrondi

FONT_HEADLINE = os.path.join(FONT_DIR, "Baloo2-ExtraBold.ttf")
FONT_LABEL = os.path.join(FONT_DIR, "Nunito-Black.ttf")
FONT_SMALL = os.path.join(FONT_DIR, "Nunito-Bold.ttf")


# ---------------------------------------------------------------- utilitaires

def wrap_text_to_width(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(draw, text, font_path, max_width, max_height, start_size=88, min_size=40):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = wrap_text_to_width(draw, text, font, max_width)
        line_height = int(size * 1.18)
        total_height = line_height * len(lines)
        widest = max(draw.textbbox((0, 0), l, font=font)[2] for l in lines)
        if total_height <= max_height and widest <= max_width:
            return font, lines, line_height
        size -= 2
    font = ImageFont.truetype(font_path, min_size)
    lines = wrap_text_to_width(draw, text, font, max_width)
    return font, lines, int(min_size * 1.18)


def rounded_border(draw, margin=28, radius=48, width=3):
    draw.rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=radius, outline=BORDER, width=width,
    )


def draw_chip(draw, text, center_x, top_y):
    font = ImageFont.truetype(FONT_SMALL, 30)
    bbox = draw.textbbox((0, 0), text.upper(), font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 38, 22
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    x0 = center_x - box_w // 2
    draw.rounded_rectangle([x0, top_y, x0 + box_w, top_y + box_h], radius=box_h // 2, fill=CHIP_BG)
    draw.text((center_x, top_y + box_h // 2), text.upper(), font=font, fill=INK, anchor="mm")
    return top_y + box_h


def paste_character(base, char_path, max_h, center_x, bottom_y):
    char = Image.open(char_path).convert("RGBA")
    ratio = max_h / char.height
    char = char.resize((int(char.width * ratio), max_h), Image.LANCZOS)
    x = center_x - char.width // 2
    y = bottom_y - char.height
    base.paste(char, (x, y), char)
    return y  # haut du perso, utile pour placer le texte au-dessus


def draw_footer_logo(base, draw):
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo_h = 56
        ratio = logo_h / logo.height
        logo = logo.resize((int(logo.width * ratio), logo_h))
        total_w = logo.width + 16 + 320
        start_x = (W - total_w) // 2
        base.paste(logo, (start_x, H - 100), logo)
        name_font = ImageFont.truetype(FONT_SMALL, 30)
        draw.text((start_x + logo.width + 16, H - 100 + logo_h // 2), "On Est Tous d'Accord",
                   font=name_font, fill=INK, anchor="lm")
    except FileNotFoundError:
        pass


def draw_label_pill(draw, text, center_x, y):
    font = ImageFont.truetype(FONT_LABEL, 26)
    bbox = draw.textbbox((0, 0), text.upper(), font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 30, 16
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    x0 = center_x - box_w // 2
    draw.rounded_rectangle([x0, y, x0 + box_w, y + box_h], radius=box_h // 2, fill=INK)
    draw.text((center_x, y + box_h // 2), text.upper(), font=font, fill=BG, anchor="mm")


# ---------------------------------------------------------------- slides

def slide_character(topic_tag, headline, char_filename, label, output_path):
    base = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(base)
    rounded_border(draw)

    center_x = W // 2
    chip_bottom = draw_chip(draw, topic_tag, center_x, top_y=90)

    # headline (le texte du jour), sous le tag
    max_w = W - 200
    font, lines, line_h = fit_text(draw, headline, FONT_HEADLINE, max_w, max_height=340,
                                    start_size=86, min_size=46)
    y = chip_bottom + 50
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=INK, anchor="ma")
        y += line_h
    headline_bottom = y + 20

    # personnage, occupe le bas de l'image
    char_path = os.path.join(CHAR_DIR, char_filename)
    char_bottom_y = H - 190
    max_char_h = char_bottom_y - headline_bottom - 40
    char_top = paste_character(base, char_path, max_char_h, center_x, char_bottom_y)

    draw_label_pill(draw, label, center_x, char_bottom_y + 20)
    draw_footer_logo(base, draw)

    base.save(output_path, "JPEG", quality=92)
    return output_path


def slide_cta(closing_line, output_path):
    base = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(base)
    rounded_border(draw)

    center_x = W // 2

    # même rythme que les slides 1/2 : texte en haut, personnages en grand en bas
    max_w = W - 140
    font, lines, line_h = fit_text(draw, closing_line, FONT_HEADLINE, max_w, max_height=260,
                                    start_size=92, min_size=50)
    y = 120
    for line in lines:
        draw.text((center_x, y), line, font=font, fill=INK, anchor="ma")
        y += line_h

    sub_font = ImageFont.truetype(FONT_SMALL, 36)
    draw.text((center_x, y + 22), "Dis-le en commentaire.", font=sub_font, fill=INK_SOFT, anchor="ma")
    content_bottom = y + 22 + draw.textbbox((0, 0), "Ag", font=sub_font)[3] + 60

    # les deux persos, en grand, juste sous le texte (la place restante en bas
    # devient une respiration avant le logo, plus naturelle qu'un vide au milieu)
    char_bottom_limit = H - 190
    max_h_by_width = 560  # limité de toute façon par la largeur des deux persos côte à côte
    char_h = min(max_h_by_width, char_bottom_limit - content_bottom)
    pensee = Image.open(os.path.join(CHAR_DIR, "la_pensee.png")).convert("RGBA")
    parole = Image.open(os.path.join(CHAR_DIR, "la_parole.png")).convert("RGBA")
    r1 = char_h / pensee.height
    r2 = char_h / parole.height
    pensee = pensee.resize((int(pensee.width * r1), char_h), Image.LANCZOS)
    parole = parole.resize((int(parole.width * r2), char_h), Image.LANCZOS)

    gap = 50
    total_w = pensee.width + gap + parole.width
    start_x = center_x - total_w // 2
    top_y = content_bottom + 40
    base.paste(pensee, (start_x, top_y), pensee)
    base.paste(parole, (start_x + pensee.width + gap, top_y), parole)

    draw_footer_logo(base, draw)
    base.save(output_path, "JPEG", quality=92)
    return output_path


# ---------------------------------------------------------------- orchestrateur

def generate_carousel(topic_tag, thought_text, spoken_text, out_dir, closing_line="On est tous d'accord ?"):
    os.makedirs(out_dir, exist_ok=True)
    # Format JPEG obligatoire : Instagram refuse le PNG pour les items de carrousel
    # ("Only photo or video can be accepted as media type").
    p1 = slide_character(topic_tag, thought_text, "la_pensee.png", "La Pensée", os.path.join(out_dir, "slide_1.jpg"))
    p2 = slide_character(topic_tag, spoken_text, "la_parole.png", "La Parole", os.path.join(out_dir, "slide_2.jpg"))
    p3 = slide_cta(closing_line, os.path.join(out_dir, "slide_3.jpg"))
    return [p1, p2, p3]


def generate_reel_frames(topic_tag, thought_text, spoken_text, out_dir, closing_line="On est tous d'accord ?"):
    """Même contenu que le carrousel, mais rendu au format vertical 9:16
    (1080x1920) utilisé pour assembler le reel vidéo."""
    os.makedirs(out_dir, exist_ok=True)
    set_canvas(1080, 1920)
    try:
        p1 = slide_character(topic_tag, thought_text, "la_pensee.png", "La Pensée", os.path.join(out_dir, "reel_1.jpg"))
        p2 = slide_character(topic_tag, spoken_text, "la_parole.png", "La Parole", os.path.join(out_dir, "reel_2.jpg"))
        p3 = slide_cta(closing_line, os.path.join(out_dir, "reel_3.jpg"))
    finally:
        set_canvas(1080, 1350)  # on remet la taille par défaut (carrousel) pour ne pas perturber le reste
    return [p1, p2, p3]


if __name__ == "__main__":
    paths = generate_carousel(
        topic_tag="La réunion de trop",
        thought_text="Cette réunion aurait pu être un simple message.",
        spoken_text="Super réunion tout le monde, on est hyper alignés !",
        out_dir=os.path.join(HERE, "carousel_test"),
    )
    print("Généré :", paths)
