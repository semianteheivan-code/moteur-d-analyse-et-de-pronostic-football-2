# Feuille de route — Moteur d'analyse et de pronostic football

Ce document complète le `CAHIER_DES_CHARGES.md` (ce que le moteur doit faire)
et le `JOURNAL_PROJET.md` (comment il a été construit). Il répond à trois
besoins précis : savoir ce qui reste à faire, retrouver un fichier sans
fouiller, et comprendre le fonctionnement d'ensemble sans relire tout le code.

---

## 1. Avancement des étapes (API / infrastructure)

Toutes les étapes de la feuille de route API/infrastructure sont terminées.

| Étape | Objet | Statut |
|---|---|---|
| 1 | `/health`, `train_season` par défaut (A9 + A5) | Fait |
| 2 | `GET /fixtures` + cache (A1 + D2) | Fait |
| 3 | Le moteur récupère lui-même matchs et cotes si le client ne les fournit pas (A2 + A3) | Fait |
| 4 | Option "ne pas enregistrer" sur `/daily-batch` (A4) | Fait |
| 5 | Modèles de réponse déclarés, statuts d'erreur listés, paramètre championnat (A6 + A8 + A7) | Fait |
| 6 | Script de test automatisé de l'API + génération d'`openapi.json` (T5) | Fait (commit `e2b044a`) |
| 7 | Seuil de suspicion sur les edges flagrants (M4) | Fait (commit `f45bcb9`) |
| 8 | Suivi de statut des matchs | Sans objet pour l'instant (voir section 2) |
| 9 | Protection de quota avancée (compteur glissant, `QuotaExceededError`) | Fait (commit `b2fa415`) |
| 10 | Rafraîchissement non destructif du calendrier et des cotes | Fait (commit `593ae6e`) |

Les commits des étapes 1 à 5 sont antérieurs à ce document ; `git log --oneline`
permet de retrouver leurs hash exacts si besoin.

## 2. Travaux non achevés

### Modèle (amélioration continue, mis en pause par choix assumé)

Ce chantier n'est pas "fini" au sens classique : c'est une amélioration
continue qu'on reprendra régulièrement une fois le reste stabilisé, pas une
étape qu'on termine une fois pour toutes.

- **M1 — biais domicile sur les tranches basses** : le moteur sous-estime la
  victoire à domicile quand il la juge peu probable (10-20 % annoncé →
  nettement plus réalisé). Confirmé par plusieurs backtests et par le test
  qualitatif des 10 matchs buts, non corrigé par Dixon-Coles. Trois pistes
  identifiées, aucune implémentée : (1) recalibration statistique a
  posteriori sur la courbe déjà mesurée — rapide, corrige le symptôme pas la
  cause ; (2) avantage domicile propre à chaque équipe plutôt qu'un
  paramètre global unique — s'attaque à la cause, plus complexe ; (3)
  pondération temporelle intégrée directement dans le calcul MLE des forces.
- **M5 — fuite de données dans le rho global** : `fit_global_rho()` calibre
  rho en utilisant toutes les saisons de la base, y compris les saisons de
  test et la saison en cours, avec leurs forces en-échantillon. Le rho utilisé
  dans chaque backtest est donc influencé par des données futures par
  rapport à la coupure train/test — résultat probablement légèrement
  optimiste. Pas corrigé.

### Décisions en suspens (pas des travaux de fond, juste des choix à trancher)

- `ten_match_check_goals.py` (non suivi par git, test qualitatif 1N2/buts) :
  à supprimer ou à garder comme script utilitaire réutilisable ?
- Commits `b2fa415` (étape 9) et `593ae6e` (étape 10) : pas encore poussés
  sur GitHub.
- `requirements.txt` : mentionné dans `JOURNAL_PROJET.md` mais absent de
  `git ls-files` — à régénérer (`pip freeze > requirements.txt`) et ajouter
  au dépôt si ce n'est pas déjà fait autrement.
- `rapport.md` : présent dans le dépôt, rôle exact à reconfirmer (contenu
  pas revérifié au moment de la rédaction de ce document).

### Limites connues, non bloquantes

- `sources/elo.py` : bloqué par une erreur 502 persistante de clubelo.com.
  Jamais résolu ; un calcul Elo "maison" de repli a été envisagé mais jamais
  implémenté.
- `sources/live_fixtures.py` (intégration API-Football) : écrit et
  fonctionnel, mais le palier gratuit d'API-Football ne couvre pas la
  saison en cours — mis de côté au profit de 5DollarFootballAPI. Gardé dans
  le dépôt, dormant, pour un éventuel abonnement Pro futur (7500 req/jour).
- Cotes Double Chance : non disponibles chez aucune source utilisée. Le
  marché Double Chance du moteur (calculé, pas mesuré) reste donc non
  testable contre de vraies cotes — seuls 1N2 et Over/Under 2.5 le sont.

## 3. Inventaire des fichiers du projet

### Racine

| Fichier | Rôle |
|---|---|
| `config.py` | Paramètres centraux (chemins, championnat/saisons, seuils, cache, quota) |
| `config_secrets.py` | Clés API (gitignored, jamais commité) |
| `engine.py` | Assemblage final : probabilités + value bets + confiance par marché, pour un ou plusieurs matchs |
| `combo_builder.py` | Construction de combinés (SAFE/MEDIUM) dans une fourchette de cote donnée |
| `daily_batch.py` | Batch quotidien générique : analyse une liste de matchs, construit les combinés, stocke en base |
| `run_live_batch.py` | Relie la source live (5DollarFootballAPI) au batch quotidien, sans modifier `daily_batch.py` |
| `backtest.py` | Backtest de calibration et de rentabilité du modèle Poisson/Dixon-Coles |
| `cards_corners_backtest.py` | Backtest dédié au modèle cartons/corners (seuils, shrinkage) |
| `form_backtest.py` | Backtest de la piste forme pondérée (abandonnée, alpha 0 à 0,5) |
| `diagnostic_rho.py` | Script d'investigation sur la fuite de données du rho global (M5) |
| `check_five_dollar_names.py` | Vérifie la correspondance des noms d'équipes face à 5DollarFootballAPI |
| `check_journee8.py` | Vérification ponctuelle sur la Journée 8 (validation du bug combo_builder corrigé) |
| `check_names.py` | Vérification des noms d'équipes football-data.co.uk / Understat |
| `_check_cards_corners.py` | Vérification de la couverture et des anomalies des données cartons/corners |
| `ten_match_check.py` | Test qualitatif sur 10 matchs connus — marchés cartons/corners |
| `ten_match_check_goals.py` | Test qualitatif sur 10 matchs connus — marchés 1N2/buts (non suivi par git, voir section 2) |
| `test_api.py` | Suite de tests automatisés de l'API (8 scénarios) |
| `test_integration_five_dollar.py` | Test d'intégration bout-en-bout : calendrier live + cotes live + moteur |
| `openapi.json` | Notice générée de l'API (régénérée après chaque changement d'`api/main.py`) |
| `rapport.md` | À reconfirmer (voir section 2) |
| `.gitignore` | Exclut `config_secrets.py`, `.venv/`, etc. |

### `db/`

| Fichier | Rôle |
|---|---|
| `database.py` | Connexion SQLite + schéma : `matches`, `match_xg`, `team_elo`, `raw_cache`, `predictions`, `api_requests` |

### `sources/`

| Fichier | Rôle |
|---|---|
| `football_data.py` | Collecte l'historique football-data.co.uk (résultats, cotes, cartons, corners) |
| `understat.py` | Collecte l'historique xG (Understat) |
| `elo.py` | Classements Elo via clubelo.com (bloqué, voir section 2) |
| `team_names.py` | Correspondance des noms d'équipes entre toutes les sources utilisées |
| `live_fixtures.py` | Intégration API-Football (dormant, voir section 2) |
| `five_dollar_football.py` | Source live utilisée en pratique : calendrier + cotes 5DollarFootballAPI, avec cache, quota et fusion non destructive |

### `features/`

| Fichier | Rôle |
|---|---|
| `form.py` | Calcule forme récente, xG récent et face-à-face pour un match |

### `models/`

| Fichier | Rôle |
|---|---|
| `poisson.py` | Modèle Poisson/Dixon-Coles (MLE conjointe attaque/défense/avantage domicile) |
| `ml.py` | Couche gradient boosting (ajustement par features additionnelles) |
| `ml_backtest.py` | Calibration et ROI de la couche ML |
| `form_adjustment.py` | Piste forme pondérée (abandonnée, voir section 2) |
| `cards_corners.py` | Modèle Poisson pour les marchés cartons et corners |

### `api/`

| Fichier | Rôle |
|---|---|
| `main.py` | API FastAPI en lecture seule : `/health`, `GET /fixtures`, `POST /analyze`, `POST /daily-batch` |

## 4. Fonctionnement du moteur — vue d'ensemble

### Deux pipelines séparés

- **Entraînement** : à partir de l'historique (football-data.co.uk +
  Understat, 6 saisons de La Liga), calibre les forces attaque/défense de
  chaque équipe (Poisson/Dixon-Coles) et entraîne la couche ML. Ne tourne
  pas en continu — relancé manuellement quand la base est rafraîchie.
- **Inférence** : pour un match donné (passé en paramètre ou récupéré via la
  source live), calcule une probabilité par marché, la compare à la cote
  disponible, et produit un score de confiance. C'est `engine.py` qui
  assemble tout ça.

### Le calendrier et les cotes : deux cadences différentes

- Les données d'entraînement (football-data.co.uk) sont rafraîchies
  manuellement, pas en continu.
- Les données live (5DollarFootballAPI, via `sources/five_dollar_football.py`)
  sont mises en cache dans `raw_cache` avec deux durées de vie différentes :
  calendrier 12h, cotes 2h. Un rafraîchissement ne remplace jamais
  aveuglément ce qui était déjà connu — il fusionne (étape 10) : un match ou
  une cote déjà connue n'est jamais perdue à cause d'une réponse API vide
  ou incomplète.
- Le nombre d'appels réels vers l'API externe est protégé par un compteur
  glissant sur 60 minutes (étape 9), avec une marge de sécurité sous le
  quota réel du fournisseur.

### Ce que produit une analyse de match

Pour chaque marché (1N2, Double Chance, Over/Under buts, cartons, corners),
le moteur renvoie : une probabilité, la cote du marché si disponible, l'écart
entre les deux, si c'est un value bet, et si l'écart est jugé suspect (edge
trop flagrant, étape 7/M4). En plus des données complètes par marché, deux
vues dérivées transparentes sont fournies : les opportunités triées par
écart, et le marché jugé le plus sûr (hors Double Chance, qui gonfle
mécaniquement les probabilités).

Si plus de 40 % des données clés manquent, ou si l'équipe est inconnue ou
absente de la saison d'entraînement, le moteur refuse de prédire plutôt que
de sortir une estimation peu fiable — avec un statut distinct selon la
raison (`refused`, `unknown_team`, `insufficient_history`).

### Le principe multi-récepteurs

Le moteur ne décide jamais "quoi jouer" : c'est au récepteur (bot Telegram,
SaaS...) de décider. Rien de propre à un client (ex. les fourchettes de cote
SAFE/MEDIUM du bot) n'est codé en dur dans le moteur — ces paramètres sont
toujours fournis par l'appelant. L'API (`api/main.py`) expose ce que le
moteur sait déjà faire, en lecture seule : aucun appel ne déclenche de
nouveau calcul d'entraînement.
