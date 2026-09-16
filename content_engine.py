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
# Claude Sonnet 5 pour la partie créative (l'humour a besoin d'un modèle plus
# fort que Haiku, qui a tendance à sortir des vannes plates/génériques). Le
# coût reste négligeable : un seul appel par jour, quelques centaines de mots
# en sortie, quelques centimes par mois.
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"

TEXT_FIELDS = ["topic_tag", "thought_text", "spoken_text", "closing_line",
               "caption_instagram", "caption_facebook", "engagement_prompt",
               "raisonnement_choix_angle"]


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

RÈGLE LA PLUS IMPORTANTE N°1 : LA PRÉCISION, PAS LA GÉNÉRALITÉ. Le principal défaut qui tue une blague, c'est de
rester sur un thème général au lieu de décrire UNE scène précise avec un détail concret (un chiffre, un mot
exact qu'on dit, un objet, une durée). "Les réunions qui durent trop longtemps" n'est pas une scène, c'est un
titre d'article. "Ça fait 40 minutes qu'on refait le même point pour la 3e fois" est une scène. Si ton
topic_tag ressemble à un titre de liste ("les habitudes des Français au travail", "les résolutions du nouvel
an"), c'est raté : redécoupe jusqu'à trouver LE moment précis où ça se joue.

RÈGLE LA PLUS IMPORTANTE N°2 : LA PENSÉE DOIT ÊTRE BRUTE, PAS ÉDULCORÉE. thought_text n'est pas "la version un
peu moins polie" de spoken_text, c'est la pensée la plus honnête, la plus directe, la moins flatteuse pour la
personne qui la pense, sans aucun filtre de politesse. Le but n'est PAS d'être vulgaire ou méchant (toujours
interdit, voir plus bas), c'est d'être sans détour : zéro mot édulcorant ("un peu", "plutôt", "je trouve que",
"peut-être", "disons que"), zéro hésitation, zéro nuance polie. Une pensée molle ou hésitante rate la blague
aussi sûrement qu'une pensée trop vague. Si ta première version de thought_text pourrait presque être dite à
voix haute sans choquer personne, elle n'est pas assez brute : recommence en enlevant tous les amortisseurs.

Voici des exemples du niveau de précision, de brutalité (sans vulgarité) et de contraste attendu (des exemples
de TON à suivre, jamais à recopier : invente un sujet et une scène différents à chaque fois) :

Exemple 1 — sujet "la réunion Zoom qui aurait pu être un mail"
  La Pensée : "Je t'écoute plus, je réponds à mes mails depuis dix minutes."
  La Parole : "Super réunion, on est hyper alignés, merci à tous !"

Exemple 2 — sujet "le groupe WhatsApp de la famille"
  La Pensée : "Je lis même plus les messages, je scrolle juste pour mettre un like."
  La Parole : "Haha trop mignon, merci Maman !"

Exemple 3 — sujet "la commande à emporter en retard"
  La Pensée : "Dans 5 minutes j'annule et je me fais des pâtes, tant pis pour le remboursement."
  La Parole : "Pas de souci du tout, prenez votre temps !"

Exemple 4 — sujet "le collègue qui met toute l'équipe en copie pour rien"
  La Pensée : "Il s'est senti important en mettant 14 personnes en copie pour ça."
  La Parole : "Merci pour ce retour, super complet !"

Remarque le niveau de franchise de La Pensée dans ces exemples : elle admet un truc pas glorieux (la flemme,
l'égoïsme, l'hypocrisie envers soi-même), sans filtre ni excuse. La Parole, elle, n'est pas juste "une phrase
polie" au hasard : c'est le mensonge social exact que tout le monde a déjà dit dans cette situation précise.
Vise ce niveau-là : si un lecteur ne peut pas s'imaginer la scène en 1 seconde, ou si La Pensée sonne encore
sage et mesurée, recommence.

MATIÈRE PREMIÈRE : tu reçois une liste de sujets qui buzzent aujourd'hui en France (recherches Google Trends).

PROCESSUS OBLIGATOIRE, à faire mentalement avant de rédiger quoi que ce soit :
1. Passe en revue CHAQUE sujet de la liste, un par un. Pour chacun, élimine-le immédiatement s'il est politique,
   religieux, un fait divers grave, un drame, une catastrophe, un conflit, ou tout sujet qui pourrait diviser ou
   heurter une partie du public.
2. Pour chaque sujet restant, évalue honnêtement son potentiel comique : est-ce qu'il fait naître une scène
   "Pensée vs Parole" précise et immédiate (voir la règle de précision ci-dessus), ou est-ce qu'il reste vague,
   tiré par les cheveux, ou seulement "vaguement lié" ? Sois exigeant : un sujet qui t'oblige à forcer le lien
   n'est pas un bon sujet.
3. S'il existe au moins un sujet qui donne vraiment une scène drôle et précise, choisis le MEILLEUR d'entre eux
   et pars sur "buzz_actu" : un contenu ancré dans l'actualité du jour a plus de portée qu'un sujet intemporel,
   donc priorise-le chaque fois qu'un sujet s'y prête vraiment.
4. Si aucun sujet de la liste ne passe ce test (tous éliminés à l'étape 1, ou aucun ne donne une scène vraiment
   bonne à l'étape 2), pars sur un angle intemporel plutôt que de forcer un sujet tendance qui ne marche pas.
   Un bon sujet intemporel bat toujours un sujet tendance forcé.

Dans le champ raisonnement_choix_angle, résume en une phrase ce passage en revue : quels sujets tendance tu as
considérés et pourquoi tu as retenu (ou écarté) chacun. Ça doit refléter une vraie comparaison, pas une phrase
vague du type "j'ai choisi un sujet intemporel".

Catégories de sujets tendance exploitables (si le test ci-dessus est passé) : divertissement, pop culture,
sport, sortie de film/série, musique, buzz internet léger, anecdote people, événement sportif, tendance de
consommation, météo, ou situation du quotidien que l'actualité illustre bien.

RÈGLE LA PLUS IMPORTANTE N°3 : DES SUJETS CRUS, PAS SEULEMENT DES SITUATIONS MIGNONNES. "Cru" ici veut dire des
sujets qui touchent à des petites vérités qu'on cache par honte, par gêne ou par égoïsme (la jalousie, l'argent,
l'apparence, le désir de reconnaissance, les mensonges affectifs), PAS un ton vulgaire ou grossier (toujours
interdit, voir plus bas). Une réunion Zoom ou un groupe WhatsApp, c'est gentillet ; la jalousie envers un ami
qui gagne plus, ou le mensonge qu'on fait à sa belle-mère, c'est cru. Vise systématiquement les sujets qui
touchent un point sensible qu'on n'admet jamais à voix haute, pas juste une contrariété du quotidien.

Angles intemporels toujours disponibles en secours, classés par famille (pioche large, ne reste pas cantonné
au travail et à la famille) :
- Argent entre proches : qui paie l'addition, prêter de l'argent à un ami, comparer les salaires, un cadeau
  jugé trop cher ou trop cheap, culpabiliser de ne pas donner assez pour un cadeau collectif.
- Jalousie et comparaison sociale : l'ami qui vient d'être augmenté ou de s'acheter une maison, les vacances
  des autres sur Instagram, la réussite d'un ancien camarade de classe, le ex qui a l'air heureux avec sa
  nouvelle personne.
- Rencontres et vie de couple : une appli de rencontre (photos qui datent, réponses tièdes), un date qui déçoit,
  ne plus avoir envie de sortir avec son/sa partenaire, mentir sur pourquoi on annule un rendez-vous, la
  jalousie sur le téléphone de l'autre.
- Apparence et corps : la salle de sport et les résolutions abandonnées, se comparer à quelqu'un sur les
  réseaux, un vêtement qui ne va plus, un compliment qu'on ne pense pas vraiment.
- Amitiés : faire semblant d'aimer un cadeau, ne pas vouloir aller à un anniversaire, une amitié qui s'éteint
  sans qu'on l'admette, un ami qui parle trop de lui.
- Famille élargie : la belle-famille qu'on supporte à peine, les préférences cachées entre frères et sœurs ou
  entre ses propres enfants, les conseils non sollicités des parents.
- Travail et argent professionnel : envier le salaire ou le poste d'un collègue, faire semblant d'être malade,
  mentir sur sa charge de travail, applaudir une idée qu'on trouve mauvaise en réunion.
- Habitudes qu'on cache un peu : la flemme, le temps d'écran, la nourriture livrée en cachette d'un régime, les
  séries regardées en secret, stalker quelqu'un sur les réseaux.

Ces sujets restent 100% familiaux et publiables : aucune allusion sexuelle explicite, aucune méchanceté ciblée
sur une personne réelle, aucune vulgarité. Le "cru" vient de l'honnêteté du sentiment (jalousie, égoïsme, petit
mensonge), pas du langage.

Voici deux exemples supplémentaires sur ce registre plus "cru" en termes de sujet (toujours des exemples de TON
à suivre, jamais à recopier) :

Exemple 5 — sujet "l'ami qui vient d'être augmenté"
  La Pensée : "Ça me rend malade qu'il gagne plus que moi maintenant."
  La Parole : "Trop bien pour toi, tu le mérites !"

Exemple 6 — sujet "le cadeau d'anniversaire raté"
  La Pensée : "Je vais le revendre dès demain matin."
  La Parole : "Wow, c'est exactement ce que je voulais, merci !"

Ne cite JAMAIS le nom d'une personne réelle précise (politique, célébrité) dans une blague qui lui attribue des
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
- thought_text : LA phrase de "La Pensée", ce qui se pense en silence. Brute, sans filtre de politesse, CONCRÈTE
  (un détail précis plutôt qu'une généralité), 4 à 16 mots. Jamais édulcorée par "un peu", "plutôt", "je trouve
  que" ou une nuance polie.
- spoken_text : LA phrase de "La Parole", ce qui est dit à voix haute dans la même situation. Doit créer un
  contraste clair et drôle avec thought_text (poli, hypocrite, minimisant, ou au contraire too-much) : c'est le
  mensonge social exact qu'on a tous déjà dit dans cette situation précise, pas une politesse générique. 4 à 16
  mots.
- closing_line : la relance de la dernière image/du reel, une variation autour de "On est tous d'accord ?"
  (tu peux garder cette phrase telle quelle la plupart du temps, ou proposer une petite variante collée au sujet
  du jour, du type "Dites-moi que c'est pas que moi." ou "On est bien d'accord ?"). Toujours une question courte.
- caption_instagram et caption_facebook : accompagnent la publication, ajoutent un peu de contexte ou une
  deuxième vanne, se terminent souvent par une question ou une invitation à commenter. Différentes l'une de
  l'autre. 40 à 90 mots.
- sujet : résumé en une courte phrase, pour l'historique.
- angle_type : "buzz_actu" si basé sur une tendance du jour, "intemporel" sinon.
- based_on_trend : le sujet tendance utilisé s'il y en a un, sinon "".
- raisonnement_choix_angle : une phrase qui résume ton passage en revue des tendances (voir le PROCESSUS
  OBLIGATOIRE ci-dessus) et pourquoi tu as retenu cet angle plutôt qu'un autre.
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
            "raisonnement_choix_angle": {"type": "string"},
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
            "angle_type", "sujet", "based_on_trend", "raisonnement_choix_angle", "topic_tag", "thought_text",
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
- topic_tag, thought_text ou spoken_text restent au niveau d'un thème général ("les réunions interminables",
  "les habitudes des Français") au lieu de décrire UNE scène précise avec un détail concret (chiffre, mot exact,
  objet, durée). Une blague qui pourrait s'appliquer à n'importe quelle situation similaire, sans aucun détail
  qui ancre une scène précise, doit être rejetée : ce n'est pas drôle, c'est un titre d'article.
- thought_text est encore mou ou édulcoré (contient "un peu", "plutôt", "je trouve que", "peut-être", ou toute
  autre nuance polie) au lieu d'être une pensée brute et sans filtre. Une Pensée qui pourrait presque être dite
  à voix haute sans choquer personne n'a pas assez de contraste avec La Parole : à rejeter.
- Le sujet choisi reste trop "gentillet" (une simple contrariété du quotidien comme une réunion qui traîne ou
  un groupe WhatsApp bruyant) alors qu'un sujet plus cru était possible (jalousie, argent, apparence, mensonge
  affectif, comparaison sociale, petite lâcheté qu'on cache par honte). Ce compte vise des vérités qu'on cache
  par gêne, pas juste des désagréments qu'on partage déjà volontiers entre amis.
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
