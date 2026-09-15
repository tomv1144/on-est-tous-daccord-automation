"""
ON EST TOUS D'ACCORD - Agent de publication automatique (Facebook + Instagram)
================================================================================
Ce script fait tout, sans intervention humaine, à chaque exécution :

  1. Récupère les tendances du jour en France (Google Trends, gratuit).
  2. Rédige le contenu "Pensée vs Parole" du jour (API Claude), en respectant
     la voix éditoriale et les règles de sécurité du compte.
  3. Fait relire ce contenu par un second appel API qui joue le rôle de
     filtre qualité/sécurité (remplace la relecture humaine) : s'il rejette
     le contenu, le script régénère, puis abandonne ce cycle plutôt que de
     publier un contenu problématique.
  4. Génère le carrousel (3 images) et le reel (vidéo courte, musique
     générée par code, sans voix) correspondants.
  5. Commit + push ces fichiers dans CE MÊME dépôt GitHub (nécessaire pour
     que les API Facebook/Instagram puissent aller les chercher via
     raw.githubusercontent.com).
  6. Publie le carrousel + le reel sur la Page Facebook et sur le compte
     Instagram professionnel.
  7. Enregistre ce qui a été publié pour ne jamais répéter un sujet récent.

Ce script est fait pour tourner comme "GitHub Actions workflow" planifié
(voir .github/workflows/autopost.yml) : il s'exécute sur les serveurs de
GitHub, 24h/24, sans dépendre d'un PC allumé.

Configuration : toutes les clés/identifiants sont lus depuis les variables
d'environnement (Secrets du dépôt GitHub). Rien de sensible n'est stocké
dans un fichier ici.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from content_engine import (  # noqa: E402
    sanitize_dashes, get_trending_topics, generate_content, review_content, apply_corrections,
)
from generate_carousel import generate_carousel  # noqa: E402
from generate_reel import generate_reel  # noqa: E402

HISTORY_PATH = os.path.join(HERE, "tousdaccord_history.json")
LOG_PATH = os.path.join(HERE, "tousdaccord_autopost.log")
IG_TOKEN_STATE_PATH = os.path.join(HERE, "tousdaccord_ig_token_state.json")

FB_API_VERSION = "v21.0"


# ---------------------------------------------------------------------------
# Utilitaires (identiques au fonctionnement déjà validé sur Klarimo)
# ---------------------------------------------------------------------------

def log(message):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config():
    required = [
        "ANTHROPIC_API_KEY",
        "GITHUB_REPO",
        "FB_PAGE_ID",
        "FB_PAGE_ACCESS_TOKEN",
        "IG_USER_ID",
        "IG_ACCESS_TOKEN",
    ]
    cfg = {k: os.environ.get(k, "") for k in required}
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log(f"ERREUR : variables d'environnement manquantes : {missing}")
        sys.exit(1)
    return cfg


def run_git(args):
    result = subprocess.run(["git"] + args, cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Commande 'git {' '.join(args)}' a échoué : {result.stderr}")
    return result.stdout


def git_commit_and_push(paths, message):
    existing = [p for p in paths if os.path.isfile(os.path.join(HERE, p))]
    if not existing:
        log(f"Rien à committer pour {paths} (fichier(s) introuvable(s)).")
        return
    subprocess.run(["git", "config", "user.name", "tousdaccord-autopost-bot"], cwd=HERE)
    subprocess.run(["git", "config", "user.email", "autopost@onesttousdaccord.fr"], cwd=HERE)
    run_git(["add"] + existing)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE)
    if diff.returncode == 0:
        log(f"Rien à committer pour {paths} (aucun changement).")
        return
    run_git(["commit", "-m", message])
    run_git(["push"])
    log(f"Commit + push effectué : {message}")


def load_history():
    if os.path.isfile(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def http_json(url, headers, payload, method="POST"):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw_error": body}


# ---------------------------------------------------------------------------
# Jeton Instagram longue durée -> renouvellement automatique (même mécanisme
# que Klarimo : Meta impose un renouvellement avant 60 jours)
# ---------------------------------------------------------------------------

def get_fresh_ig_token(config_token):
    current_token = config_token
    if os.path.isfile(IG_TOKEN_STATE_PATH):
        with open(IG_TOKEN_STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        current_token = state.get("access_token", config_token)

    url = (
        "https://graph.instagram.com/refresh_access_token"
        f"?grant_type=ig_refresh_token&access_token={urllib.parse.quote(current_token)}"
    )
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        new_token = data.get("access_token")
        if new_token:
            with open(IG_TOKEN_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "access_token": new_token,
                        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
                        "expires_in_seconds": data.get("expires_in"),
                    },
                    f,
                    indent=2,
                )
            log("Jeton Instagram renouvelé avec succès (valable ~60 jours de plus).")
            return new_token
    except urllib.error.HTTPError as e:
        log(
            "AVERTISSEMENT : échec du renouvellement du jeton Instagram "
            f"({e.code}) : {e.read().decode('utf-8', errors='ignore')}. "
            "On continue avec le jeton actuel."
        )
    except Exception as exc:  # noqa: BLE001
        log(f"AVERTISSEMENT : échec du renouvellement du jeton Instagram : {exc}")

    return current_token


# ---------------------------------------------------------------------------
# Hébergement des fichiers (commit direct dans le dépôt, via git)
# ---------------------------------------------------------------------------

def publish_assets_and_get_urls(repo, relative_paths, commit_message):
    """Commit + push tous les fichiers indiqués EN UNE SEULE FOIS (un seul
    commit), puis renvoie un dictionnaire {chemin_relatif: url_publique}.
    On attend un peu après le push pour laisser le CDN de GitHub servir les
    fichiers avant que Facebook/Instagram n'essaient de les télécharger."""
    git_commit_and_push(relative_paths, commit_message)
    time.sleep(6)
    return {p: f"https://raw.githubusercontent.com/{repo}/main/{p}" for p in relative_paths}


# ---------------------------------------------------------------------------
# Publication Facebook (carrousel + vidéo)
# ---------------------------------------------------------------------------

def _fb_upload_unpublished_photo(page_id, page_token, image_path):
    """Étape 1 d'un post multi-photos Facebook : on met en ligne chaque image
    sans la publier tout de suite (published=false), pour récupérer son id
    et pouvoir ensuite les assembler dans un seul post via /feed."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/photos"
    boundary = "----tousdaccordBoundary"
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"published\"\r\n\r\nfalse\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"access_token\"\r\n\r\n{page_token}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; filename=\"slide.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n",
    ]
    body = "".join(parts).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Erreur upload photo Facebook : {e.read().decode('utf-8', errors='ignore')}")


def publish_facebook_carousel(page_id, page_token, image_paths, caption):
    photo_ids = []
    for path in image_paths:
        result = _fb_upload_unpublished_photo(page_id, page_token, path)
        if "id" not in result:
            raise RuntimeError(f"Erreur upload photo Facebook (pas d'id) : {result}")
        photo_ids.append(result["id"])

    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/feed"
    payload = {"message": caption, "access_token": page_token}
    for i, photo_id in enumerate(photo_ids):
        payload[f"attached_media[{i}]"] = json.dumps({"media_fbid": photo_id})
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Erreur publication carrousel Facebook : {e.read().decode('utf-8', errors='ignore')}")


def publish_facebook_video(page_id, page_token, video_url, description):
    """Publie une vidéo sur la Page via une URL déjà hébergée (pas d'upload
    par morceaux nécessaire). Les vidéos verticales courtes sont
    généralement traitées comme des Reels par Facebook automatiquement."""
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/videos"
    payload = {
        "file_url": video_url,
        "description": description,
        "access_token": page_token,
        "published": "true",
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Erreur publication vidéo Facebook : {e.read().decode('utf-8', errors='ignore')}")


# ---------------------------------------------------------------------------
# Publication Instagram (carrousel + reel)
# ---------------------------------------------------------------------------

def _ig_wait_until_finished(creation_id, ig_token, label):
    status_url = (
        f"https://graph.instagram.com/{FB_API_VERSION}/{creation_id}"
        f"?fields=status_code&access_token={urllib.parse.quote(ig_token)}"
    )
    for attempt in range(20):
        time.sleep(3)
        req = urllib.request.Request(status_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp_raw:
                status_data = json.loads(resp_raw.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Erreur vérification statut ({label}) : {e.read().decode('utf-8', errors='ignore')}")
        code = status_data.get("status_code")
        log(f"Statut {label} ({attempt + 1}/20) : {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Le traitement de {label} a échoué : {status_data}")
    raise RuntimeError(f"{label} n'était toujours pas prêt après l'attente maximale.")


def publish_instagram_carousel(ig_user_id, ig_token, image_urls, caption):
    child_ids = []
    for index, image_url in enumerate(image_urls):
        status, resp = http_json(
            f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media",
            {"Content-Type": "application/json"},
            {"image_url": image_url, "is_carousel_item": "true", "access_token": ig_token},
        )
        if status != 200 or "id" not in resp:
            raise RuntimeError(f"Erreur création item carrousel Instagram ({status}) : {resp}")
        child_id = resp["id"]
        # On attend que Instagram ait fini de télécharger/traiter CHAQUE image avant
        # de construire le conteneur carrousel : sinon l'appel média_publish arrive
        # trop tôt et Instagram répond "Media ID is not available".
        _ig_wait_until_finished(child_id, ig_token, f"item carrousel {index + 1}")
        child_ids.append(child_id)

    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media",
        {"Content-Type": "application/json"},
        {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption, "access_token": ig_token},
    )
    if status != 200 or "id" not in resp:
        raise RuntimeError(f"Erreur création conteneur carrousel Instagram ({status}) : {resp}")
    carousel_id = resp["id"]

    # Même logique pour le conteneur carrousel final lui-même avant de publier.
    _ig_wait_until_finished(carousel_id, ig_token, "conteneur carrousel")

    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media_publish",
        {"Content-Type": "application/json"},
        {"creation_id": carousel_id, "access_token": ig_token},
    )
    if status != 200:
        raise RuntimeError(f"Erreur publication carrousel Instagram ({status}) : {resp}")
    return resp


def publish_instagram_reel(ig_user_id, ig_token, video_url, caption):
    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media",
        {"Content-Type": "application/json"},
        {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": ig_token},
    )
    if status != 200 or "id" not in resp:
        raise RuntimeError(f"Erreur création conteneur reel Instagram ({status}) : {resp}")
    creation_id = resp["id"]

    _ig_wait_until_finished(creation_id, ig_token, "reel Instagram")

    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media_publish",
        {"Content-Type": "application/json"},
        {"creation_id": creation_id, "access_token": ig_token},
    )
    if status != 200:
        raise RuntimeError(f"Erreur publication reel Instagram ({status}) : {resp}")
    return resp


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def main():
    log("=" * 70)
    log("ON EST TOUS D'ACCORD AUTOPOST - démarrage")
    cfg = load_config()
    history = load_history()
    recent_topics = [h["sujet"] for h in history[-15:]]

    ig_token = get_fresh_ig_token(cfg["IG_ACCESS_TOKEN"])
    git_commit_and_push([os.path.basename(IG_TOKEN_STATE_PATH)], "Renouvellement jeton Instagram")

    # --- Étape 1a : tendances du jour ---
    log("Récupération des tendances Google Trends France...")
    trending_topics = get_trending_topics()
    log(f"Tendances récupérées : {trending_topics or '(aucune, on part sur un angle intemporel)'}")

    # --- Étape 1b : génération ---
    log("Génération du contenu (API Claude)...")
    content = sanitize_dashes(generate_content(cfg["ANTHROPIC_API_KEY"], recent_topics, trending_topics))
    log(f"Sujet proposé : {content['sujet']} (angle: {content['angle_type']})")
    log(f"Analyse des tendances : {content.get('raisonnement_choix_angle', '(non fourni)')}")

    # --- Étape 1c : relecture qualité ---
    max_attempts = 3
    approved = False
    for attempt in range(max_attempts):
        log(f"Relecture qualité (tentative {attempt + 1}/{max_attempts})...")
        review = review_content(cfg["ANTHROPIC_API_KEY"], content)
        if review.get("approved"):
            log("Contenu approuvé.")
            approved = True
            break

        log(f"Contenu rejeté : {review.get('issues')}")
        has_corrections = any(k.startswith("corrected_") and review.get(k) for k in review)
        content = apply_corrections(content, review)

        if attempt == max_attempts - 1:
            break

        if not has_corrections:
            content = generate_content(cfg["ANTHROPIC_API_KEY"], recent_topics + [content["sujet"]], trending_topics)
        content = sanitize_dashes(content)

    if not approved:
        log("Contenu toujours rejeté après plusieurs tentatives -> ABANDON de ce cycle, rien n'est publié.")
        return

    # --- Étape 2 : visuels (carrousel + reel) ---
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    relative_dir = f"posts/{stamp}"
    out_dir = os.path.join(HERE, relative_dir)

    log("Génération du carrousel (3 images)...")
    carousel_paths = generate_carousel(
        content["topic_tag"], content["thought_text"], content["spoken_text"],
        out_dir=out_dir, closing_line=content["closing_line"],
    )

    log("Génération du reel (vidéo + musique générée)...")
    reel_path = generate_reel(
        content["topic_tag"], content["thought_text"], content["spoken_text"],
        out_dir=out_dir, seed=abs(hash(content["sujet"])) % 1000, closing_line=content["closing_line"],
    )

    # --- Étape 3 : hébergement (un seul commit pour tous les fichiers du jour) ---
    log("Publication des fichiers dans le dépôt GitHub...")
    all_relative_paths = [os.path.relpath(p, HERE) for p in carousel_paths + [reel_path]]
    urls = publish_assets_and_get_urls(cfg["GITHUB_REPO"], all_relative_paths, f"Contenu du {stamp} : {content['sujet'][:60]}")
    carousel_urls = [urls[os.path.relpath(p, HERE)] for p in carousel_paths]
    reel_url = urls[os.path.relpath(reel_path, HERE)]
    log(f"Fichiers publics : {urls}")

    hashtags_str = " ".join(f"#{h.lstrip('#')}" for h in content["hashtags"])
    fb_caption = content["caption_facebook"] + "\n\n" + hashtags_str
    ig_caption = content["caption_instagram"] + "\n\n" + hashtags_str

    # --- Étape 4 : publication du carrousel ---
    log("Publication du carrousel sur Facebook...")
    fb_carousel_result = publish_facebook_carousel(cfg["FB_PAGE_ID"], cfg["FB_PAGE_ACCESS_TOKEN"], carousel_paths, fb_caption)
    log(f"Carrousel Facebook OK : {fb_carousel_result}")

    log("Publication du carrousel sur Instagram...")
    ig_carousel_result = publish_instagram_carousel(cfg["IG_USER_ID"], ig_token, carousel_urls, ig_caption)
    log(f"Carrousel Instagram OK : {ig_carousel_result}")

    # --- Étape 5 : publication du reel ---
    log("Publication du reel sur Facebook...")
    fb_video_result = publish_facebook_video(cfg["FB_PAGE_ID"], cfg["FB_PAGE_ACCESS_TOKEN"], reel_url, fb_caption)
    log(f"Reel Facebook OK : {fb_video_result}")

    log("Publication du reel sur Instagram...")
    ig_reel_result = publish_instagram_reel(cfg["IG_USER_ID"], ig_token, reel_url, ig_caption)
    log(f"Reel Instagram OK : {ig_reel_result}")

    # --- Étape 6 : historique ---
    history.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "sujet": content["sujet"],
        "angle_type": content["angle_type"],
        "based_on_trend": content.get("based_on_trend"),
        "raisonnement_choix_angle": content.get("raisonnement_choix_angle"),
        "topic_tag": content["topic_tag"],
        "facebook_carousel_post_id": fb_carousel_result.get("id"),
        "facebook_reel_video_id": fb_video_result.get("id"),
        "instagram_carousel_media_id": ig_carousel_result.get("id"),
        "instagram_reel_media_id": ig_reel_result.get("id"),
    })
    save_history(history)
    git_commit_and_push([os.path.basename(HISTORY_PATH)], f"Historique : {content['sujet'][:60]}")
    log("Terminé avec succès.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        log(f"ERREUR NON GÉRÉE : {exc}")
        sys.exit(1)
