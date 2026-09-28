"""
NOS PETITES PAPATTES - Moteur de contenu (idéation + relecture)
============================================================================
Nouveau concept (remplace entièrement l'ancien "Pensée vs Parole") : un
compte de reels attendrissants avec un couple de Corgis (personnages
principaux) et, de temps en temps, un couple de Golden Retriever qui leur
rend visite (personnages secondaires). Aucun texte à l'écran dans la vidéo
(voir generate_reel_animals.py) : ce module ne s'occupe que de deux choses,
avant tout appel à OpenAI pour la partie visuelle :

  1. Invente le "thème du jour" (une petite situation de couple mignonne,
     ex: "Pique-nique sous les cerisiers") et la légende qui accompagnera
     le reel sur Facebook/Instagram. C'est un appel à l'API Claude : c'est
     le seul endroit où Claude choisit encore un contenu créatif pour ce
     compte, exactement comme pour Klarimo, où Claude décide du sujet/texte
     et où c'est ensuite OpenAI qui décide de la mise en image concrète
     (voir generate_reel_animals.invent_scene_plan).
  2. Fait relire ce thème par un second appel qui joue le rôle de filtre
     de sécurité/qualité (remplace la relecture humaine, puisqu'il n'y en
     a aucune ici).

Ce fichier ne fait AUCUN appel réseau à Facebook/Instagram/GitHub, ni à
OpenAI : c'est tousdaccord_autopost.py (le chef d'orchestre) qui appelle les
fonctions d'ici, puis passe le thème choisi à generate_reel_animals.py pour
la fabrication du reel.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"

TEXT_FIELDS = ["theme_tag", "mood_description", "caption_instagram", "caption_facebook", "engagement_prompt"]

# Tous les 3 posts, le couple de Golden Retriever rejoint les Corgis (voir
# decide_include_golden ci-dessous) : "de temps en temps", comme demandé,
# plutôt qu'un tirage aléatoire qui pourrait par malchance les faire
# apparaître 3 fois de suite ou pas du tout pendant 10 jours.
GOLDEN_EVERY_N_POSTS = 3


def sanitize_dashes(content):
    """Filet de sécurité : interdiction du tiret cadratin/demi-cadratin, comme
    pour Klarimo (ça sonne 'IA'). Interdit dans le prompt, retiré aussi ici
    au niveau du code au cas où le modèle en laisse passer un."""
    for field in TEXT_FIELDS:
        if field in content and content[field]:
            cleaned = content[field].replace(" — ", ", ").replace(" – ", ", ")
            cleaned = cleaned.replace("—", ",").replace("–", ",")
            content[field] = cleaned
    return content


def decide_include_golden(history):
    """Décide, à partir de l'historique, si le couple de Golden Retriever
    apparaît dans le post du jour. Rotation simple et prévisible (1 post sur
    GOLDEN_EVERY_N_POSTS) plutôt qu'un tirage au hasard, pour éviter qu'ils
    apparaissent par malchance plusieurs fois de suite ou pas du tout pendant
    longtemps. Décidé ici, en code, jamais laissé au hasard d'un appel IA qui
    n'a aucune mémoire des jours précédents."""
    return len(history) % GOLDEN_EVERY_N_POSTS == GOLDEN_EVERY_N_POSTS - 1


# ---------------------------------------------------------------------------
# Idéation du thème du jour + légendes (API Claude)
# ---------------------------------------------------------------------------

GENERATION_SYSTEM_PROMPT = """Tu écris pour "Nos Petites Papattes", un compte Facebook/Instagram de reels
attendrissants mettant en scène un couple de chiens Corgi (les personnages principaux) dans des petites
situations de couple mignonnes du quotidien. De temps en temps, un couple de Golden Retriever leur rend visite
en personnages secondaires (amis qui passent). AUCUN texte n'apparaît à l'écran dans la vidéo elle-même : c'est
un format purement visuel, silencieux, avec juste une petite musique de fond. Ton travail ne concerne QUE (1)
le thème/l'ambiance de la situation du jour, qui servira ensuite de brief créatif à une autre IA pour dessiner
les scènes, et (2) la légende qui accompagne le reel sur Facebook/Instagram.

PUBLIC ET OBJECTIF : grand public généraliste, tous âges, envie de faire sourire et d'être partagé largement
("regarde ça, c'est trop mignon"). Rien ici ne doit jamais être clivant, triste, effrayant ou compliqué : c'est
un plaisir simple et universel, jamais un second degré ou une blague qui demande du contexte.

CE QUI FAIT UN BON THÈME : une situation de couple précise et concrète, pas un thème générique. "Un moment
tranquille" n'est pas un thème, c'est une absence de thème. "Une sieste au soleil interrompue par un papillon"
est un thème. Pense aux petits riens attendrissants d'une vraie relation de couple, transposés à des chiens :
un petit-déjeuner préparé en amoureux, une balade sous la pluie avec un seul parapluie, ramasser des
coquillages sur la plage, faire les magasins de Noël, planter des fleurs ensemble au jardin, se réchauffer près
d'un feu de cheminée, un pique-nique improvisé, construire un bonhomme de neige, cueillir des pommes en
automne, regarder les étoiles allongés dans l'herbe, une danse improvisée dans le salon, faire la cuisine
ensemble et se mettre de la farine partout, un cadeau surprise caché derrière le dos, se blottir pendant un
orage. Varie les saisons, les lieux (intérieur/extérieur), les activités et la météo d'un jour à l'autre : ne te
limite pas au canapé du salon.

INSPIRATION SAISONNIÈRE : la date du jour t'est donnée. Si une saison, une météo probable, ou une fête proche
(Noël, Saint-Valentin, Halloween, la rentrée, l'été...) inspire naturellement un thème mignon, tu peux t'en
servir pour que le post résonne avec le moment de l'année, sans jamais forcer un thème qui ne s'y prêterait
pas : un bon thème intemporel bat toujours un thème saisonnier forcé.

RÔLE DU GOLDEN RETRIEVER : on te dit si le couple de Golden Retriever apparaît aujourd'hui. Si oui, imagine-les
comme des amis qui passent une partie du moment avec le couple de Corgis (ex: un pique-nique à 4, une balade
ensemble), jamais comme les personnages principaux : les Corgis restent le cœur de chaque scène.

CHAMPS À REMPLIR :
- theme_tag : 3 à 6 mots, à la forme nominale (ex: "Pique-nique sous les cerisiers", "Journée pluvieuse en
  amoureux"), qui résume la situation. Sert aussi à ne pas répéter un thème récent.
- mood_description : 1 à 2 phrases en français qui décrivent le lieu, l'ambiance, la lumière, et l'émotion de
  la scène (ex: "Une après-midi de printemps ensoleillée dans un jardin fleuri, ambiance douce et paisible,
  les deux Corgis profitent d'un moment de calme ensemble."). C'est le brief qu'une autre IA utilisera pour
  imaginer les scènes précises à dessiner : sois concret sur le décor et l'atmosphère.
- caption_instagram et caption_facebook : accompagnent la publication. Chaleureux, mignons, jamais ironiques
  ni sarcastiques. Peuvent se terminer par une question simple ou une invitation à commenter ("Vous êtes plutôt
  câlin ou sieste ?", "Tag la personne avec qui tu ferais ça"). Différentes l'une de l'autre. 30 à 70 mots.
- engagement_prompt : une courte invitation à réagir en commentaire, à glisser naturellement dans une des
  légendes plutôt qu'ajoutée à part.
- hashtags : 5 à 8 hashtags simples et larges (chiens mignons, couple, quotidien attendrissant), en français
  ou très courants en anglais (#cutedogs, #corgi), sans espace.
- sujet : résumé en une courte phrase, pour l'historique.

INTERDITS ABSOLUS (contenu automatique, sans relecture humaine, donc zéro tolérance) :
- Le tiret cadratin "—" ou demi-cadratin "–" : STRICTEMENT INTERDIT, aucune exception. Utilise virgules,
  parenthèses, ou deux phrases séparées.
- Tout ce qui n'est pas positif et attendrissant : rien de triste, effrayant, dangereux, violent, ou qui mette
  en scène un animal blessé, malade, perdu, ou en détresse, même brièvement.
- Rien qui sonne comme un texte généré par une IA : évite les phrases trop parfaites, les tournures littéraires,
  les transitions artificielles ("en effet", "par ailleurs"). Écris comme on parle.

Réponds uniquement en appelant l'outil "daily_theme" fourni."""

GENERATION_TOOL = {
    "name": "daily_theme",
    "description": "Le thème du jour (brief créatif) et les légendes d'une publication \"Nos Petites Papattes\".",
    "input_schema": {
        "type": "object",
        "properties": {
            "sujet": {"type": "string"},
            "theme_tag": {"type": "string"},
            "mood_description": {"type": "string"},
            "caption_instagram": {"type": "string"},
            "caption_facebook": {"type": "string"},
            "engagement_prompt": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "sujet", "theme_tag", "mood_description", "caption_instagram",
            "caption_facebook", "engagement_prompt", "hashtags",
        ],
    },
}

REVIEW_SYSTEM_PROMPT = """Tu es le filtre de sécurité et de qualité pour "Nos Petites Papattes", un compte de
reels attendrissants mettant en scène un couple de Corgis (et parfois un couple de Golden Retriever en
personnages secondaires). Comme il n'y a AUCUNE relecture humaine avant publication, ton rôle est essentiel.

Rejette (approved=false) si l'UN de ces problèmes est présent :
- Le texte contient un tiret cadratin/demi-cadratin ("—" ou "–").
- Le thème ou la description de l'ambiance n'est pas positif et attendrissant : quoi que ce soit de triste,
  effrayant, dangereux, violent, ou qui mette en scène un animal blessé, malade, perdu, ou en détresse.
- theme_tag reste un thème générique et vague ("un moment tranquille", "une jolie journée") au lieu d'une
  situation concrète et précise (voir les exemples du prompt de génération).
- Le thème est trop proche d'un thème déjà traité récemment (fourni dans le message).
- Les légendes sonnent artificielles/écrites par une IA plutôt que par une vraie personne (phrases trop
  parfaites, vocabulaire trop soutenu), ou sont ironiques/sarcastiques au lieu d'être chaleureuses.
- Un champ obligatoire est manquant, vide, ou beaucoup trop long pour une légende de réseau social.

Les préférences de style ou une légende moyenne mais correcte ne doivent JAMAIS à elles seules faire passer
approved à false. Dans le doute sur un point non listé ci-dessus, APPROUVE.

Si tu rejettes, propose SYSTÉMATIQUEMENT une version corrigée des champs concernés (garde le reste identique).
Réponds uniquement en appelant l'outil "theme_review" fourni."""

REVIEW_TOOL = {
    "name": "theme_review",
    "description": "Verdict de relecture qualité et sécurité avant publication.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "corrected_theme_tag": {"type": "string"},
            "corrected_mood_description": {"type": "string"},
            "corrected_caption_instagram": {"type": "string"},
            "corrected_caption_facebook": {"type": "string"},
        },
        "required": ["approved", "issues"],
    },
}


def call_claude(api_key, system_prompt, user_message, tool):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(ANTHROPIC_API_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, body = resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw_error": raw}
        status = e.code
    if status != 200:
        raise RuntimeError(f"Erreur API Claude ({status}) : {body}")
    for block in body.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise RuntimeError(f"Réponse API Claude sans tool_use : {body}")


def generate_theme(api_key, recent_themes, include_golden):
    avoid = "\n".join(f"- {t}" for t in recent_themes) or "(aucun thème récent)"
    golden_line = (
        "Le couple de Golden Retriever apparaît AUJOURD'HUI en personnages secondaires."
        if include_golden
        else "Le couple de Golden Retriever N'apparaît PAS aujourd'hui : seuls les Corgis sont de la scène."
    )
    user_message = (
        f"Date du jour : {datetime.now().strftime('%d/%m/%Y')}\n"
        f"{golden_line}\n\n"
        f"Thèmes déjà traités récemment, à éviter de répéter :\n{avoid}\n\n"
        "Choisis le thème du jour et rédige les légendes."
    )
    return call_claude(api_key, GENERATION_SYSTEM_PROMPT, user_message, GENERATION_TOOL)


def review_theme(api_key, content, recent_themes):
    avoid = "\n".join(f"- {t}" for t in recent_themes) or "(aucun thème récent)"
    user_message = (
        f"Thème : {content.get('theme_tag', '')}\n"
        f"Ambiance : {content.get('mood_description', '')}\n\n"
        f"Thèmes déjà traités récemment :\n{avoid}\n\n"
        f"Légende Instagram :\n{content.get('caption_instagram', '')}\n\n"
        f"Légende Facebook :\n{content.get('caption_facebook', '')}"
    )
    return call_claude(api_key, REVIEW_SYSTEM_PROMPT, user_message, REVIEW_TOOL)


def apply_corrections(content, review):
    """Si le relecteur a rejeté le post mais propose des corrections, on les
    applique directement plutôt que de jeter tout le travail à la poubelle."""
    mapping = {
        "corrected_theme_tag": "theme_tag",
        "corrected_mood_description": "mood_description",
        "corrected_caption_instagram": "caption_instagram",
        "corrected_caption_facebook": "caption_facebook",
    }
    for corrected_key, original_key in mapping.items():
        value = review.get(corrected_key)
        if value:
            content[original_key] = value
    return content
