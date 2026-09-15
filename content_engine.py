"""
ON EST TOUS D'ACCORD - Moteur de contenu (idéation + rédaction + relecture)
============================================================================
Ce module s'occupe de la partie "réflexion" de l'agent :
  1. Va chercher ce qui buzz aujourd'hui en France (Google Trends).
  2. Décide d'un angle "Pensée vs Parole" (ce que tout le monde pense en
     silence VS ce que tout le monde dit à voix haute), basé sur une
     tendance, ou intemporel si rien de la tendance ne s'y prête.
  3. Rédige le contenu du carrousel + reel (même contenu texte utilisé pour
     les deux formats, seule la mise en image change).
  4. Fait relire ce contenu par un second appel qui joue le rôle de filtre
     de sécurité/qualité (remplace la relecture humaine, puisqu'il n'y en
     a aucune ici).

Ce fichier ne fait AUCUN appel réseau à Facebook/Instagram/GitHub : c'est
tousdaccord_autopost.py (le chef d'orchestre) qui appelle les fonctions
d'ici, puis s'occupe de la génération du carrousel/reel et de la
publication.
"""

import json
import urllib.request
import urllib.error

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_VERSION = "2023-06-01"

TEXT_FIELDS = ["topic_tag", "thought_text", "spoken_text", "closing_line",
               "caption_instagram", "caption_facebook", "engagement_prompt"]


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


# ---------------------------------------------------------------------------
# Étape 1 : récupération des tendances du jour (Google Trends France)
# ---------------------------------------------------------------------------

def get_trending_topics(max_topics=8):
    """Renvoie une liste de sujets tendance en France aujourd'hui (chaînes de
    texte courtes). Gratuit, via la librairie pytrends (aucune clé requise).

    Important : si cette étape échoue pour une raison quelconque (Google a
    changé son site, coupure réseau, etc.), on ne doit JAMAIS faire planter
    toute la publication à cause de ça. On renvoie simplement une liste vide,
    et le contenu partira sur un angle intemporel à la place.
    """
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="fr-FR", tz=60)
        df = pytrends.trending_searches(pn="france")
        topics = df[0].tolist()[:max_topics]
        return topics
    except Exception as exc:  # noqa: BLE001
        print(f"AVERTISSEMENT : impossible de récupérer les tendances Google Trends : {exc}")
        return []


# ---------------------------------------------------------------------------
# Étape 2 : idéation + rédaction (API Claude)
# ---------------------------------------------------------------------------

GENERATION_SYSTEM_PROMPT = """Tu écris pour "On Est Tous d'Accord", un compte Facebook/Instagram grand public
construit autour de deux personnages : "La Pensée" (ce que tout le monde pense en silence dans une situation
donnée) et "La Parole" (ce qui est dit à voix haute dans la même situation, souvent poli, hypocrite ou en
décalage avec la pensée). Le contraste entre les deux, c'est toute la blague.

OBJECTIF : que la personne qui lit se reconnaisse immédiatement et se dise "ah oui, complètement, on est tous
d'accord". Chaque publication doit se comprendre en 2 secondes, sans contexte nécessaire. Le format est un
carrousel de 3 images (Pensée, puis Parole, puis relance) et un reel vidéo courte reprenant le même texte : tu
rédiges UN SEUL contenu, réutilisé pour les deux formats.

TON : direct, familier, mais WRITTEN pour être lu en gros sur une image (pas un script parlé). Des phrases
courtes. Jamais compliqué, jamais un mot recherché.

MATIÈRE PREMIÈRE : tu reçois une liste de sujets qui buzzent aujourd'hui en France (recherches Google Trends).
- Tu as le droit de t'appuyer sur un de ces sujets UNIQUEMENT s'il concerne du divertissement, de la pop culture,
  du sport, une sortie de film/série, de la musique, un buzz internet léger, une anecdote people, un événement
  sportif, une tendance de consommation, la météo, ou une situation du quotidien que l'actualité illustre bien.
- INTERDIT ABSOLU de t'appuyer sur un sujet politique, religieux, un fait divers grave, un drame, une catastrophe,
  un conflit, ou tout sujet qui pourrait diviser ou heurter une partie du public. Si TOUS les sujets de la liste
  sont de ce type, ou si aucun sujet ne se prête vraiment à une "Pensée vs Parole" sympa, ignore complètement la
  liste et pars sur un angle intemporel (voir ci-dessous).
- Angles intemporels toujours disponibles en secours : la vie de couple, la vie au travail (réunions, mails,
  open-space), les repas de famille, les groupes WhatsApp, les transports, la flemme, les résolutions jamais
  tenues, les habitudes de consommation (Netflix, livraison, réseaux sociaux), les phrases de politesse qu'on dit
  sans les penser, les petites hypocrisies du quotidien.
- Ne cite JAMAIS le nom d'une personne réelle précise (politique, célébrité) dans une blague qui lui attribue des
  propos ou un comportement inventé. Tu peux évoquer un événement public connu de façon neutre (ex: "la sortie du
  nouveau film Marvel") sans inventer de citation ni te moquer personnellement de quelqu'un.

INTERDITS ABSOLUS (contenu automatique, sans relecture humaine, donc zéro tolérance) :
- Le tiret cadratin "—" ou demi-cadratin "–" : STRICTEMENT INTERDIT, aucune exception. Utilise virgules,
  parenthèses, ou deux phrases séparées.
- Aucune moquerie ciblant un groupe (origine, religion, genre, orientation, handicap, physique).
- Aucun sujet politique, religieux, ou lié à un drame/une tragédie, même sous couvert d'humour.
- Aucun contenu vulgaire, à connotation sexuelle, ou qui encourage un comportement dangereux ou malsain.
- Aucune fausse citation attribuée à une personne réelle nommée.
- Rien qui sonne comme un texte généré par une IA : évite les phrases trop parfaites, les tournures littéraires,
  les transitions artificielles ("en effet", "par ailleurs"). Écris comme on parle.

CHAMPS À REMPLIR :
- topic_tag : le petit badge affiché en haut du visuel, 2 à 5 mots, qui résume la situation (ex: "La réunion de
  trop", "Le repas de famille", "Le groupe WhatsApp du travail"), à la forme nominale, pas une phrase complète.
- thought_text : LA phrase de "La Pensée", ce qui se pense en silence. Percutante, honnête, 4 à 16 mots.
- spoken_text : LA phrase de "La Parole", ce qui est dit à voix haute dans la même situation. Doit créer un
  contraste clair et drôle avec thought_text (poli, hypocrite, minimisant, ou au contraire too-much). 4 à 16 mots.
- closing_line : la relance de la dernière image/du reel, une variation autour de "On est tous d'accord ?"
  (tu peux garder cette phrase telle quelle la plupart du temps, ou proposer une petite variante collée au sujet
  du jour, du type "Dites-moi que c'est pas que moi." ou "On est bien d'accord ?"). Toujours une question courte.
- caption_instagram et caption_facebook : accompagnent la publication, ajoutent un peu de contexte ou une
  deuxième vanne, se terminent souvent par une question ou une invitation à commenter. Différentes l'une de
  l'autre. 40 à 90 mots.
- sujet : résumé en une courte phrase, pour l'historique.
- angle_type : "buzz_actu" si basé sur une tendance du jour, "intemporel" sinon.
- based_on_trend : le sujet tendance utilisé s'il y en a un, sinon "".
- engagement_prompt : une courte invitation à réagir en commentaire (ex: "Dis OUI en commentaire si t'es
  d'accord", "Tag quelqu'un qui fait pareil"), à glisser naturellement dans une des légendes plutôt qu'ajoutée
  à part.
- hashtags : 5 à 8 hashtags simples et larges (humour, quotidien, viral), en français, sans espace.

Réponds uniquement en appelant l'outil "post_content" fourni."""

GENERATION_TOOL = {
    "name": "post_content",
    "description": "Le contenu complet d'une publication \"On Est Tous d'Accord\" (carrousel Pensée/Parole + reel), prêt à être relu puis publié.",
    "input_schema": {
        "type": "object",
        "properties": {
            "angle_type": {"type": "string", "enum": ["buzz_actu", "intemporel"]},
            "sujet": {"type": "string"},
            "based_on_trend": {"type": "string"},
            "topic_tag": {"type": "string"},
            "thought_text": {"type": "string"},
            "spoken_text": {"type": "string"},
            "closing_line": {"type": "string"},
            "caption_instagram": {"type": "string"},
            "caption_facebook": {"type": "string"},
            "engagement_prompt": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "angle_type", "sujet", "based_on_trend", "topic_tag", "thought_text",
            "spoken_text", "closing_line", "caption_instagram",
            "caption_facebook", "engagement_prompt", "hashtags",
        ],
    },
}

REVIEW_SYSTEM_PROMPT = """Tu es le filtre de sécurité et de qualité pour "On Est Tous d'Accord", un compte
humour grand public basé sur le contraste "Pensée vs Parole". Comme il n'y a AUCUNE relecture humaine avant
publication, ton rôle est essentiel : tu es la seule protection contre un post problématique ou raté.

Rejette (approved=false) si l'UN de ces problèmes est présent :
- Le texte contient un tiret cadratin/demi-cadratin ("—" ou "–").
- Le post s'appuie sur un sujet politique, religieux, un drame, une tragédie, un conflit, ou tout sujet qui
  pourrait diviser ou heurter une partie du public (même traité "avec humour").
- Le post se moque d'un groupe entier (origine, religion, genre, orientation, handicap, physique).
- Le post invente une citation ou un comportement attribué à une personne réelle nommée.
- Le post est vulgaire, à connotation sexuelle, ou encourage un comportement dangereux/malsain.
- Le contraste Pensée/Parole ne fonctionne pas du tout (incompréhensible, illogique, ou les deux phrases disent
  en fait la même chose) au point qu'il n'y a clairement aucune raison de publier ce post.
- Le texte sonne artificiel/écrit par une IA plutôt que par une vraie personne (phrases trop parfaites,
  vocabulaire trop soutenu pour ce compte).
- topic_tag, thought_text ou spoken_text sont manquants, vides, ou beaucoup trop longs pour tenir sur un visuel
  (thought_text/spoken_text : plus de 18 mots).

Les préférences de style, une punchline moyenne mais correcte, ou une répétition entre les deux légendes ne
doivent JAMAIS à elles seules faire passer approved à false. Dans le doute sur un point non listé ci-dessus,
APPROUVE.

Si tu rejettes, propose SYSTÉMATIQUEMENT une version corrigée des champs concernés (garde le reste identique).
Réponds uniquement en appelant l'outil "content_review" fourni."""

REVIEW_TOOL = {
    "name": "content_review",
    "description": "Verdict de relecture qualité et sécurité avant publication.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "corrected_topic_tag": {"type": "string"},
            "corrected_thought_text": {"type": "string"},
            "corrected_spoken_text": {"type": "string"},
            "corrected_closing_line": {"type": "string"},
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


def generate_content(api_key, recent_topics, trending_topics):
    avoid = "\n".join(f"- {t}" for t in recent_topics) or "(aucun sujet récent)"
    trends_str = "\n".join(f"- {t}" for t in trending_topics) or "(aucune tendance récupérée aujourd'hui)"
    user_message = (
        f"Sujets tendance en France aujourd'hui (à utiliser seulement s'ils sont adaptés, voir tes règles) :\n"
        f"{trends_str}\n\n"
        f"Sujets déjà traités récemment, à éviter de répéter :\n{avoid}\n\n"
        "Choisis un angle et rédige le contenu Pensée / Parole du jour."
    )
    return call_claude(api_key, GENERATION_SYSTEM_PROMPT, user_message, GENERATION_TOOL)


def review_content(api_key, content):
    user_message = (
        f"Sujet : {content['sujet']}\n"
        f"Basé sur une tendance : {content.get('based_on_trend') or 'non'}\n\n"
        f"Badge sujet : {content.get('topic_tag', '')}\n"
        f"La Pensée : {content.get('thought_text', '')}\n"
        f"La Parole : {content.get('spoken_text', '')}\n"
        f"Relance finale : {content.get('closing_line', '')}\n\n"
        f"Légende Instagram :\n{content.get('caption_instagram', '')}\n\n"
        f"Légende Facebook :\n{content.get('caption_facebook', '')}"
    )
    return call_claude(api_key, REVIEW_SYSTEM_PROMPT, user_message, REVIEW_TOOL)


def apply_corrections(content, review):
    """Si le relecteur a rejeté le post mais propose des corrections, on les
    applique directement plutôt que de jeter tout le travail à la poubelle."""
    mapping = {
        "corrected_topic_tag": "topic_tag",
        "corrected_thought_text": "thought_text",
        "corrected_spoken_text": "spoken_text",
        "corrected_closing_line": "closing_line",
        "corrected_caption_instagram": "caption_instagram",
        "corrected_caption_facebook": "caption_facebook",
    }
    for corrected_key, original_key in mapping.items():
        value = review.get(corrected_key)
        if value:
            content[original_key] = value
    return content
