"""
ON EST TOUS D'ACCORD - Agent de publication automatique (Facebook + Instagram)
================================================================================
Nouveau format (remplace entièrement l'ancien "Pensée vs Parole" et son
carrousel) : un reel muet et attendrissant mettant en scène un couple de
Corgis (et, de temps en temps, un couple de Golden Retriever en personnages
secondaires). Ce script fait tout, sans intervention humaine, à chaque
exécution :

  1. Décide si le couple de Golden Retriever apparaît aujourd'hui (rotation
     simple en code, voir content_engine.decide_include_golden).
  2. Invente le thème du jour + les légendes (API Claude), voir
     content_engine.generate_theme.
  3. Fait relire ce thème par un second appel API qui joue le rôle de filtre
     qualité/sécurité (remplace la relecture humaine) : s'il rejette le
     contenu et ne peut pas le corriger, le script ABANDONNE ce cycle plutôt
     que de publier un contenu problématique.
  4. Fabrique le reel (scènes + poses générées par OpenAI, montage en
     fondu-enchaîné, musique de fond générée par code), voir
     generate_reel_animals.generate_reel_animals. IMPORTANT : il n'y a AUCUN
     format de secours pour ce concept. Si la fabrication échoue pour
     n'importe quelle raison (clé API absente, panne, quota, crédit
     épuisé...), le script ABANDONNE ce cycle : rien n'est publié ce jour-là,
     plutôt que de publier un format qui ne correspond plus du tout au
     concept. C'est un choix assumé.
  5. Commit + push le reel dans CE MÊME dépôt GitHub (nécessaire pour que les
     API Facebook/Instagram puissent aller le chercher via
     raw.githubusercontent.com).
  6. Publie le reel sur la Page Facebook et sur le compte Instagram
     professionnel.
  7. Enregistre ce qui a été publié pour ne jamais répéter un thème récent.

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
    sanitize_dashes, decide_include_golden, generate_theme, review_theme, apply_corrections,
)
from generate_reel_animals import generate_reel_animals  # noqa: E402

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
        "OPENAI_API_KEY",
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
# Publication Facebook (vidéo)
# ---------------------------------------------------------------------------

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
# Publication Instagram (reel)
# ---------------------------------------------------------------------------

def _ig_wait_until_finished(creation_id, ig_token, label, max_attempts=20, sleep_seconds=3):
    """Interroge Instagram jusqu'à ce que le conteneur vidéo soit marqué
    FINISHED. Le traitement d'une vidéo peut occasionnellement prendre
    plusieurs minutes (transcodage pour le flux Reels)."""
    status_url = (
        f"https://graph.instagram.com/{FB_API_VERSION}/{creation_id}"
        f"?fields=status_code&access_token={urllib.parse.quote(ig_token)}"
    )
    for attempt in range(max_attempts):
        time.sleep(sleep_seconds)
        req = urllib.request.Request(status_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp_raw:
                status_data = json.loads(resp_raw.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Erreur vérification statut ({label}) : {e.read().decode('utf-8', errors='ignore')}")
        code = status_data.get("status_code")
        log(f"Statut {label} ({attempt + 1}/{max_attempts}) : {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Le traitement de {label} a échoué : {status_data}")
    raise RuntimeError(f"{label} n'était toujours pas prêt après l'attente maximale.")


def publish_instagram_reel(ig_user_id, ig_token, video_url, caption):
    status, resp = http_json(
        f"https://graph.instagram.com/{FB_API_VERSION}/{ig_user_id}/media",
        {"Content-Type": "application/json"},
        {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": ig_token},
    )
    if status != 200 or "id" not in resp:
        raise RuntimeError(f"Erreur création conteneur reel Instagram ({status}) : {resp}")
    creation_id = resp["id"]

    # Une vidéo met plus longtemps à être traitée qu'une image : jusqu'à 10
    # minutes d'attente (60 tentatives de 10 secondes) avant d'abandonner.
    _ig_wait_until_finished(creation_id, ig_token, "reel Instagram", max_attempts=60, sleep_seconds=10)

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
    recent_themes = [h["theme_tag"] for h in history[-15:] if h.get("theme_tag")]
    include_golden = decide_include_golden(history)
    log(f"Golden Retriever aujourd'hui : {'oui' if include_golden else 'non'}")

    ig_token = get_fresh_ig_token(cfg["IG_ACCESS_TOKEN"])
    git_commit_and_push([os.path.basename(IG_TOKEN_STATE_PATH)], "Renouvellement jeton Instagram")

    # --- Étape 1a : thème du jour (API Claude) ---
    log("Invention du thème du jour (API Claude)...")
    content = sanitize_dashes(generate_theme(cfg["ANTHROPIC_API_KEY"], recent_themes, include_golden))
    log(f"Thème proposé : {content['theme_tag']}")

    # --- Étape 1b : relecture qualité ---
    max_attempts = 3
    approved = False
    for attempt in range(max_attempts):
        log(f"Relecture qualité (tentative {attempt + 1}/{max_attempts})...")
        review = review_theme(cfg["ANTHROPIC_API_KEY"], content, recent_themes)
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
            content = generate_theme(cfg["ANTHROPIC_API_KEY"], recent_themes + [content["theme_tag"]], include_golden)
        content = sanitize_dashes(content)

    if not approved:
        log("Contenu toujours rejeté après plusieurs tentatives -> ABANDON de ce cycle, rien n'est publié.")
        return

    # --- Étape 2 : fabrication du reel ---
    # AUCUN format de secours ici (voir docstring de generate_reel_animals) :
    # si ça échoue, on abandonne proprement ce cycle plutôt que de laisser
    # planter le script ou publier autre chose à la place.
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    relative_dir = f"posts/{stamp}"
    out_dir = os.path.join(HERE, relative_dir)

    log("Fabrication du reel (scènes + poses via OpenAI, montage, musique)...")
    try:
        reel_path = generate_reel_animals(
            content["theme_tag"], content["mood_description"], include_golden,
            out_dir=out_dir, seed=abs(hash(content["theme_tag"])) % 1000, api_key=cfg["OPENAI_API_KEY"],
        )
    except Exception as exc:  # noqa: BLE001
        log(f"ÉCHEC de la fabrication du reel : {exc}")
        log(
            "ABANDON de ce cycle : pas de format de secours pour ce concept "
            "(voir generate_reel_animals.py). Rien n'est publié aujourd'hui."
        )
        return

    # --- Étape 3 : hébergement ---
    log("Publication du fichier dans le dépôt GitHub...")
    relative_path = os.path.relpath(reel_path, HERE)
    urls = publish_assets_and_get_urls(
        cfg["GITHUB_REPO"], [relative_path], f"Reel du {stamp} : {content['theme_tag'][:60]}",
    )
    reel_url = urls[relative_path]
    log(f"Fichier public : {reel_url}")

    hashtags_str = " ".join(f"#{h.lstrip('#')}" for h in content["hashtags"])
    fb_caption = content["caption_facebook"] + "\n\n" + hashtags_str
    ig_caption = content["caption_instagram"] + "\n\n" + hashtags_str

    # --- Étape 4 : publication du reel ---
    log("Publication du reel sur Facebook...")
    fb_video_result = publish_facebook_video(cfg["FB_PAGE_ID"], cfg["FB_PAGE_ACCESS_TOKEN"], reel_url, fb_caption)
    log(f"Reel Facebook OK : {fb_video_result}")

    log("Publication du reel sur Instagram...")
    ig_reel_result = publish_instagram_reel(cfg["IG_USER_ID"], ig_token, reel_url, ig_caption)
    log(f"Reel Instagram OK : {ig_reel_result}")

    # --- Étape 5 : historique ---
    history.append({
        "date": datetime.now().isoformat(timespec="seconds"),
        "sujet": content.get("sujet"),
        "theme_tag": content["theme_tag"],
        "mood_description": content["mood_description"],
        "include_golden": include_golden,
        "facebook_reel_video_id": fb_video_result.get("id"),
        "instagram_reel_media_id": ig_reel_result.get("id"),
    })
    save_history(history)
    git_commit_and_push([os.path.basename(HISTORY_PATH)], f"Historique : {content['theme_tag'][:60]}")
    log("Terminé avec succès.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        log(f"ERREUR NON GÉRÉE : {exc}")
        sys.exit(1)
