# Rapport de suivi — Moteur d'analyse et de pronostic football

Ce document complète le journal existant (`journal du projet`) et sert de point de reprise si la conversation avec Claude s'interrompt. À relire avant de reprendre le développement.

**Cahier des charges** : document séparé, tenu à jour sur claude.ai (13 sections + compléments budget/volumétrie). Le lien exact est dans l'historique de conversation — si la session est perdue, redemander à Claude de le retrouver ou le reconstruire à partir de ce rapport.

---

## 1. Où on en est par rapport au journal précédent

Le journal (section 8) listait 7 grandes étapes. État mis à jour :

1. Base de données SQLite — fait
2. Collecte football-data.co.uk (6 saisons, La Liga) — fait
3. Understat (xG) fait ; Elo en pause (service clubelo.com en erreur 502 persistante)
4. Modèle Poisson + Dixon-Coles implémenté et validé cette session (voir section 3bis)
5. Backtest de calibration et de rentabilité fonctionnels, corrigés cette session, résultats reproductibles confirmés
6. Couche machine learning (gradient boosting) — pas commencée
7. Moteur complet (engine.py) + API FastAPI — pas commencés

## 2. Bug résolu cette session : backtest.py silencieux

**Symptôme** : python -m backtest s'exécutait sans erreur (code de sortie 0) mais n'affichait rien.

**Cause identifiée** : le fichier fourni par l'utilisateur n'avait aucun bloc if __name__ == "__main__": à la fin — les fonctions run_full_backtest() et run_full_value_backtest() étaient définies mais jamais appelées. La boucle de détail par marché était aussi incomplète.

**Corrections apportées** :
- Ajout du bloc if __name__ == "__main__": en fin de fichier.
- Complétion de la boucle de détail par marché (taux de réussite, misé/rendu, profit, ROI par marché).

## 3. Dixon-Coles implémenté cette session

**Fichier modifié** : models/poisson.py

**Approche retenue** : les forces d'attaque/défense existantes (ratios + shrinkage 0.85, inchangées) sont conservées. La correction Dixon-Coles est ajoutée par-dessus via un paramètre rho, ajusté par maximum de vraisemblance.

**Changements techniques** :
- _dixon_coles_tau() : corrige la sous-estimation des scores 0-0, 1-0, 0-1, 1-1.
- fit_global_rho() : ajuste rho UNE SEULE FOIS sur toutes les saisons regroupées (mis en cache) — remplace un premier essai instable (fit par saison individuelle).
- compute_team_strengths(season) : signature inchangée, retourne aussi "rho".
- predict_match_from_strengths(strengths_data, home_team, away_team) : nouvelle fonction, à utiliser dans les boucles/backtests (évite de refitter à chaque match).
- predict_match(home_team, away_team, season) : signature inchangée, usage ponctuel.

**Fichier modifié en cascade** : backtest.py — calibration et rentabilité unifiées sur le même modèle (predict_match_from_strengths), forces calculées une fois par couple de saisons.

## 3bis. Résultats obtenus avec Dixon-Coles — deux tentatives

**Tentative 1 — rho par saison individuelle : échec.**

| Marché | Avant DC | DC par saison |
|---|---|---|
| ROI global | -6,0% | -7,1% |
| Nul (X) | -25,5% | -24,8% |

Diagnostic (diagnostic_rho.py) : rho oscillait entre -0,11 et +0,08 selon la saison (signe changeant) — instabilité due à trop peu de données par saison (~272 matchs).

**Tentative 2 — rho global stabilisé : amélioration réelle, concentrée sur le nul.**

| Marché | Avant DC | DC global (rho stabilisé) |
|---|---|---|
| ROI global | -6,0% | -5,1% |
| Nul (X) — ROI | -25,5% | -14,7% |
| Nul (X) — réussite | 17,5% | 20,9% |
| Domicile (1) — ROI | -12,1% | -11,2% |
| Extérieur (2) — ROI | -5,7% | -5,2% |
| Under 2.5 — ROI | +0,6% | +0,6% (inchangé, normal) |

**Confirmé reproductible** : relancé une seconde fois en session suivante, résultats strictement identiques (déterminisme du pipeline confirmé).

**Conclusion honnête** : Dixon-Coles apporte une amélioration réelle mais partielle. Le ROI reste négatif globalement. La calibration sur les tranches basses (10-30% annoncé) n'a quasiment pas bougé — ce n'est pas un problème que Dixon-Coles peut résoudre. Piste suivante logique : la couche Machine Learning (étape 6), censée affiner ce que le Poisson pur laisse passer.

## 4. Résultats de référence — AVANT Dixon-Coles

Sur les vraies données La Liga (1088 matchs calibration, 1182 paris rentabilité) :

Calibration : taux de réussite brut 50,0%. Bien calibré 40-80%. Sous-estime la victoire domicile sur tranches basses (10% annoncé → 28,6% réalisé).

Rentabilité globale : ROI -6,0%.

| Marché | Paris | Réussite | ROI |
|---|---|---|---|
| Victoire domicile (1) | 247 | 35,2% | -12,1% |
| Nul (X) | 80 | 17,5% | -25,5% |
| Victoire extérieur (2) | 281 | 26,0% | -5,7% |
| Over 2.5 | 185 | 45,4% | -3,9% |
| Under 2.5 | 389 | 51,7% | +0,6% |

## 5. Décisions et contraintes à ne pas oublier

- Championnat v1 : La Liga (SP1 sur football-data.co.uk).
- Budget : quasi nul, sources gratuites (football-data.co.uk, Understat). Elo bloqué (502).
- Stratégie de déploiement : dev/tests en local avant mise en ligne. VPS envisagé seulement une fois les critères de sortie v1 atteints (cahier des charges section 9).
- Structure du projet : celle du journal utilisateur fait foi (db/, sources/, models/, features/, api/).
- Habitudes de travail : fichiers complets plutôt que patchs partiels. Toujours python -m module, jamais exécution directe du fichier.
- Marché Double Chance : ajouté au périmètre, dérivé du 1N2, aucun modèle séparé nécessaire.
- Dépôt Git : semianteheivan-code/moteur-d-analyse-et-de-pronostic-football-2. git add . && git commit -m "..." && git push après chaque étape validée.

## 6. Décision en attente (à trancher)

ML (gradient boosting, xG déjà disponible) vs pousser le Poisson pur plus loin (MLE conjointe complète attaque/défense/rho). Le plan initial prévoyait le ML comme étape suivante.

## 7. Historique des fichiers échangés cette session

- backtest.py — corrigé (bug __main__), puis re-modifié (Dixon-Coles + unification).
- models/poisson.py — modifié deux fois (Dixon-Coles par saison, puis rho global stabilisé).
- diagnostic_rho.py — script ponctuel de diagnostic, pas un module permanent.
- rapport.md — ce document.