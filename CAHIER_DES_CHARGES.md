# Cahier des charges — Moteur d'analyse et de pronostic football

## 1. Présentation du modèle

Le modèle est un moteur d'analyse statistique et prédictive dédié au football. Il calcule des probabilités d'issues de matchs à partir de données historiques et de données en temps réel, puis compare ces probabilités aux cotes du marché pour identifier des situations de "value bet" (quand le marché sous-estime une issue).

Le moteur est conçu comme un composant autonome et réutilisable, indépendant de tout canal de diffusion. Il expose une interface claire en entrée (paramètres du match, données) et en sortie (probabilités, value bet, score de confiance), sans aucune logique de présentation mêlée au cœur du calcul. Cette séparation lui permet d'être branché ultérieurement sur différents usages sans réécrire la logique d'analyse :

- un SaaS,
- une application mobile,
- un bot d'analyse Telegram,
- ou tout autre service consommateur.

Dans cette première version, le moteur est utilisé et testé en local (sans interface), mais son architecture est pensée dès le départ pour un usage multiservice.

## 2. Objectif

- Prédire les probabilités d'issues de matchs de football.
- Comparer ces probabilités aux cotes des bookmakers pour détecter des écarts de valeur (value bets).
- Fournir un score de confiance associé à chaque prédiction, reflétant la qualité et la disponibilité des données utilisées.

Le modèle n'a pas pour objectif de garantir un gain financier : c'est un outil d'aide à la décision basé sur des probabilités statistiques.

## 3. Périmètre

- Sport : football uniquement.
- Compétitions couvertes : un championnat national majeur + coupes nationales et européennes associées. Le championnat précis reste à déterminer (candidats envisagés : Ligue 1, Premier League, La Liga) — ce choix doit être fixé avant le début du développement du pipeline de données.
- Marchés analysés en priorité :
  - Résultat du match (1N2)
  - Double Chance (1X, X2, 12) — dérivé du 1N2, utile quand l'écart entre deux issues est faible, réduit le risque
  - Over/Under buts
  - Cartons et corners

D'autres marchés (BTTS, score exact) pourront être ajoutés dans une phase ultérieure (voir section 12).

## 4. Données nécessaires

Le modèle s'appuie sur deux sources complémentaires :

| Source | Rôle | Contenu |
|---|---|---|
| Football-Data.co.uk (ou équivalent) | Historique / entraînement | Plusieurs saisons de résultats, buts, cartons, corners, cotes de bookmakers |
| 5DollarFootballAPI (palier gratuit) | Temps réel / inférence | Calendrier des matchs à venir et cotes Bet365 (1X2, buts) ; voir section 11bis pour la cadence de rafraîchissement, le quota et la protection contre les réponses incomplètes |

Niveau de complexité des données visé : intermédiaire — au-delà des stats basiques (buts, forme, classement), le modèle intègre :

- xG (expected goals), quand disponible
- Historique des confrontations directes (face-à-face)
- Compositions probables (estimées à partir des habitudes du coach et des sources disponibles) et blessures/suspensions connues au moment du batch

Précision importante : le batch tournant avant 00h la veille des matchs (voir section 11), et la composition officielle n'étant annoncée qu'environ 1h avant le coup d'envoi, le moteur ne peut structurellement jamais disposer de la composition officielle confirmée au moment de son analyse. Il travaille donc uniquement sur des compositions probables et des informations de blessures/suspensions connues à l'avance — voir aussi la limite associée en section 13.

Le modèle stocke et enrichit progressivement sa propre base de données au fil du temps, à partir des flux live collectés.

Système de stockage à deux niveaux (voir détail section 11) :

- Un cache brut des analyses journalières, qui réduit la dépendance aux appels API payants (le moteur vérifie le stockage avant d'interroger une API externe).
- Un registre léger et permanent qui conserve le suivi des pronostics dans le temps.

## 5. Fonctionnalités d'analyse

Pour chaque match à venir, le modèle doit :

1. Récupérer les données pertinentes (forme récente, xG, face-à-face, cotes actuelles).
2. Calculer une probabilité pour chaque marché ciblé (1N2, Over/Under, cartons/corners). Le Double Chance est dérivé directement des probabilités du 1N2 (ex : proba(1X) = proba(victoire domicile) + proba(match nul)) — aucun modèle séparé n'est nécessaire pour ce marché.
3. Comparer cette probabilité à la cote du marché pour détecter un éventuel value bet.
4. Associer un score de confiance à la prédiction.

## 6. Méthodes statistiques

Approche hybride à deux couches :

- **Couche de base — modèle statistique classique (Poisson / Dixon-Coles)** Les buts marqués/encaissés par équipe suivent approximativement une loi de Poisson. Cette couche donne une probabilité de référence, interprétable, pour le 1N2 et l'Over/Under.
- **Couche d'ajustement — Machine Learning léger (gradient boosting)** Vient affiner la probabilité de base avec les facteurs additionnels (xG, forme, face-à-face) et couvrir les marchés que Poisson pur modélise moins bien (cartons, corners).

Le modèle réentraîne périodiquement sa couche ML à mesure que de nouvelles données sont collectées.

## 7. Gestion des données manquantes

Logique en cascade :

- Si un facteur important manque (ex : pas de xG disponible pour ce championnat), le modèle bascule sur un facteur de repli (stats de buts classiques) et dégrade automatiquement son score de confiance.
- Si plus de 40 % des données clés d'un match sont absentes, le modèle refuse de produire une prédiction plutôt que de sortir une estimation peu fiable.

### 7bis. Système de stockage et de cache

Pour réduire la dépendance et le coût des appels API, le moteur intègre un stockage interne à deux niveaux distincts :

- **Cache brut d'analyse (temporaire, expiration 48h)** Contient les données détaillées utilisées pour chaque analyse journalière (réponses API, facteurs calculés). Avant tout appel API externe, le moteur vérifie si une analyse valide existe déjà pour ce match. Ce cache expire automatiquement après 48h afin de garder un volume de stockage maîtrisé et un coût faible dans la durée.
- **Registre de suivi des pronostics (permanent, léger)** Table distincte qui conserve, sur le long terme, l'essentiel de chaque prédiction : match, marché, probabilité prédite, cote au moment de l'analyse, et résultat réel une fois le match terminé. Ce registre ne dépend pas du cache brut et n'expire pas — il permet de suivre la performance réelle du moteur dans le temps (taux de réussite, calibration prédite vs réelle) sans reconstituer les données lourdes d'origine.

## 8. Production des résultats

Pour chaque match/marché analysé, le modèle produit :

- Une probabilité par issue possible.
- Une comparaison avec la cote du bookmaker (écart de valeur, value bet détecté ou non).
- Un score de confiance (dépendant de la disponibilité et qualité des données utilisées).

## 9. Validation et backtesting

- Version simplifiée dès le départ : test du modèle sur les saisons historiques disponibles via Football-Data.co.uk.
- Principe central : la qualité du moteur se mesure par la calibration de ses probabilités, pas par un taux de réussite fixe. Le moteur estime une probabilité propre à chaque prédiction (voir section 8) — deux matchs différents peuvent légitimement avoir des probabilités très différentes selon leur niveau de prévisibilité. Un objectif de réussite unique et fixe (ex : "70% partout") n'a pas de sens statistique dans ce contexte.
- Vérification de la calibration par tranche de probabilité : si le moteur annonce "70 %" sur un ensemble de prédictions comparables, l'issue doit se réaliser environ 70 % du temps sur cet ensemble précis (et de même pour les autres tranches : 50 %, 60 %, 80 %...).
- Le backtesting complet et automatisé (multi-saisons, multi-marchés, calibration par tranche) pourra être renforcé dans une phase ultérieure.

Critères de sortie de la phase v1 (phase de test) : plutôt qu'une durée calendaire fixe, le passage à l'étape suivante (extension multi-championnats, voir section 12) est conditionné à l'atteinte de ces critères :

- Volume de données suffisant : assez de prédictions comparées à des résultats réels pour que le backtesting et la calibration aient un sens statistique (quelques centaines de prédictions, pas quelques dizaines).
- Pipeline stable bout-en-bout : le cycle complet (batch avant 00h → stockage → prédiction → résultat réel enregistré) tourne sans intervention manuelle sur plusieurs semaines.
- Calibration validée : les probabilités annoncées correspondent à peu près aux fréquences réelles observées, sur les tranches définies plus haut.

> **Amendement décidé en cours de développement (non présent dans le document original) :** pas de passage aux phases suivantes (stockage définitif, exposition API) tant que le ROI du backtest de rentabilité n'est pas proche de l'équilibre ou positif, indépendamment de la forme finale du moteur. Convenu que cette règle encadre la mise en ligne réelle, pas le développement — le moteur peut être construit jusqu'au bout, le jugement se fait à la fin sur le moteur complet.

## 10. Gestion des erreurs

- Échec de récupération de données (API indisponible, changement de structure de réponse) → le modèle log l'erreur et n'émet pas de prédiction pour le(s) match(s) concerné(s) plutôt que d'utiliser des données incomplètes silencieusement.
- Incohérences de données (ex : score aberrant, doublons) → filtrage avant tout calcul.

## 11. Architecture technique

- Moteur autonome et réutilisable, sans interface intégrée : conçu pour être appelé (en fonction/méthode directe dans cette première version, via API dans une phase ultérieure) par un ou plusieurs services consommateurs (SaaS, application mobile, bot Telegram...).
- Séparation stricte entre la logique d'analyse (moteur) et toute logique de présentation ou de diffusion, qui reste hors périmètre de ce cahier des charges.
- Deux pipelines séparés :
  - **Pipeline d'entraînement** : utilise l'historique (Football-Data.co.uk) pour calibrer les modèles Poisson et ML.
  - **Pipeline d'inférence** : utilise le flux live (5DollarFootballAPI, voir section 11bis) pour produire des prédictions sur les matchs à venir.
- Composant de stockage/cache (voir section 7bis) : cache brut à expiration 48h + registre permanent de suivi des pronostics. Ce composant est central dans l'architecture, pas accessoire — il conditionne le coût d'exploitation du moteur dans la durée.

### 11bis. Cadence de traitement et volumétrie

- **Pipeline d'entraînement (historique)** : batch quotidien planifié avant 00h (ex : 22h-23h) pour le calibrage et la production de pronostics à partir de l'historique. Pas de rafraîchissement intra-journée de ce pipeline : décision assumée pour limiter la consommation de requêtes API. Une mise à jour manuelle ponctuelle reste possible techniquement (ex : correction exceptionnelle), mais ce n'est pas un mécanisme utilisé au quotidien — voir section 13.
- **Couche live (calendrier + cotes, exposée via l'API)** : à la différence du pipeline d'entraînement, cette couche se rafraîchit en cours de journée, via un cache à deux niveaux (table de cache brut) : calendrier toutes les 12h, cotes toutes les 2h. Chaque rafraîchissement **fusionne** avec les données déjà connues plutôt que de les remplacer : un match ou une cote déjà connue n'est jamais perdue à cause d'une réponse API vide ou incomplète (panne passagère du fournisseur) — seule une donnée effectivement reconfirmée par un appel réussi écrase l'ancienne valeur.
- **Choix d'API finalisé** : 5DollarFootballAPI, palier gratuit (60 requêtes/heure), avec une protection de quota interne fixée à 50/heure (marge de sécurité) pour ne jamais dépasser la limite réelle du fournisseur même en cas d'usage concurrent. API-Football reste une option de repli identifiée (abonnement Pro, 7 500 requêtes/jour) si le volume d'usage dépassait un jour le palier gratuit — non utilisée actuellement, son palier gratuit ne couvrant pas la saison en cours.
- Volumétrie estimée (périmètre v1 — 1 championnat + coupes) : environ 10-15 matchs par week-end complet, jusqu'à 20-30 en semaine de coupe chargée. Avec la cadence ci-dessus et la protection de quota, ce volume reste largement sous la limite du palier gratuit.
- **Couche API légère (FastAPI), endpoints disponibles** : `/health` (état de santé), `GET /fixtures` (calendrier et cotes à venir, avec cache), `POST /analyze` (analyse d'un match ; le moteur récupère lui-même calendrier et cotes si le client ne les fournit pas), `POST /daily-batch` (construction de combinés sur une fourchette de cote donnée, avec option de ne pas enregistrer en base). Lecture et récupération live seulement — aucun entraînement n'est déclenché par ces appels.

## 12. Évolutivité

Le modèle est conçu pour évoluer progressivement :

- Ajout d'autres marchés (BTTS, score exact).
- Extension à d'autres championnats ou sports.
- Passage à une interface (dashboard) ou à un système d'alertes automatiques si le besoin apparaît.
- Couverture toute l'année : avec un seul championnat national + coupes associées, le moteur sera inactif plusieurs mois par an durant la trêve estivale (généralement juin à août en Europe). Si une activité continue toute l'année est souhaitée à terme, il faudra ajouter un ou plusieurs championnats aux calendriers décalés (ex : compétitions d'Amérique du Sud). Le moteur est déjà conçu pour être agnostique au nombre de championnats (ajouter une ligue est une question de configuration/données, pas une refonte d'architecture) — c'est une décision de roadmap produit à prendre le moment venu, pas une contrainte technique.

## 13. Limites du modèle

- Le modèle ne garantit aucun gain : il s'agit d'un outil d'aide à la décision basé sur des probabilités, pas d'une martingale.
- Il ne prend pas en compte automatiquement les informations de dernière minute (ex : composition officielle annoncée ~1h avant le coup d'envoi) : le batch tournant avant 00h la veille, il travaille uniquement sur des compositions probables et des blessures/suspensions connues à l'avance. Une mise à jour manuelle ponctuelle reste possible techniquement, mais ce n'est pas un mécanisme automatique ni utilisé au quotidien.
- Il nécessite un minimum d'historique par équipe pour produire une prédiction fiable (ex : fiabilité réduite en tout début de saison).
- Il ne capture pas automatiquement les changements structurels (nouvel entraîneur, transferts majeurs, réorganisation tactique).
- Il n'est pas conçu pour anticiper des événements rares ou extrêmes (upsets exceptionnels, incidents de match).
- Les probabilités produites sont des estimations statistiques et doivent être interprétées comme telles, pas comme des certitudes.
- Activité saisonnière limitée en v1 : le périmètre actuel (1 championnat + coupes) implique une inactivité du moteur pendant la trêve estivale, faute de matchs à analyser (voir section 12).

---

*Décisions prises depuis la rédaction de ce document, non couvertes par les sections ci-dessus (voir `FEUILLE_DE_ROUTE.md` et `JOURNAL_PROJET.md` pour le détail) : championnat retenu pour la v1 = La Liga ; sources de données historiques finales = football-data.co.uk et Understat (xG), toutes deux gratuites ; Elo calculé via clubelo.com (actuellement indisponible) ; la portée d'engine.py a été clarifiée pour exclure toute décision de "meilleur marché à exploiter", réservée au système récepteur ; les marchés cartons et corners ont été ajoutés en Poisson et intégrés dans engine.py ; un seuil de suspicion sur les edges flagrants a été ajouté (un edge jugé trop beau pour être vrai est signalé, pas automatiquement écarté) ; l'API expose désormais concrètement `GET /fixtures`, `POST /analyze` et `POST /daily-batch` à plusieurs récepteurs (bot Telegram de test, futur bot commercial), toujours sans aucune règle propre à un récepteur codée en dur dans le moteur (ex : fourchettes de cote SAFE/MEDIUM).*
