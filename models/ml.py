import numpy as np
from db.database import get_connection
from features.form import compute_match_features
from models.poisson import compute_team_strengths, predict_match_from_strengths
from sklearn.ensemble import HistGradientBoostingClassifier

FEATURE_KEYS = [
    "home_form_goals_scored", "home_form_goals_conceded",
    "away_form_goals_scored", "away_form_goals_conceded",
    "home_form_matches", "away_form_matches",
    "home_xg_for", "home_xg_against",
    "away_xg_for", "away_xg_against",
    "h2h_matches", "h2h_home_wins", "h2h_draws", "h2h_away_wins",
]

ALL_SEASONS = ["2122", "2223", "2324", "2425", "2526"]


def _result_to_label(result):
    return {"H": "1", "D": "X", "A": "2"}[result]


def build_dataset(season_pairs):
    conn = get_connection()
    rows_X, rows_y = [], []

    for train_season, test_season in season_pairs:
        strengths = compute_team_strengths(train_season)
        matches = conn.execute(
            "SELECT home_team, away_team, date, result FROM matches "
            "WHERE season = ? AND home_goals IS NOT NULL",
            (test_season,),
        ).fetchall()

        for m in matches:
            try:
                poisson_probs = predict_match_from_strengths(strengths, m["home_team"], m["away_team"])
            except ValueError:
                continue

            feats = compute_match_features(m["home_team"], m["away_team"], m["date"])

            row = [feats.get(k) for k in FEATURE_KEYS]
            row += [poisson_probs["1"], poisson_probs["X"], poisson_probs["2"]]
            rows_X.append(row)
            rows_y.append(_result_to_label(m["result"]))

    return np.array(rows_X, dtype=float), np.array(rows_y)


def make_model():
    return HistGradientBoostingClassifier(
        max_iter=40,
        max_depth=2,
        learning_rate=0.03,
        min_samples_leaf=50,
        l2_regularization=3.0,
        random_state=42,
    )


def walk_forward_evaluation():
    """
    Entraine sur toutes les saisons connues jusque-la, teste sur la saison suivante,
    jamais l'inverse. Trois plis : test sur 2324, 2425, 2526 tour a tour.
    """
    results = []
    for i in range(2, len(ALL_SEASONS)):
        test_season = ALL_SEASONS[i]
        train_seasons = ALL_SEASONS[:i]
        train_pairs = [(train_seasons[j], train_seasons[j + 1]) for j in range(len(train_seasons) - 1)]
        train_pairs.append((train_seasons[-1], test_season))

        X_train, y_train = build_dataset(train_pairs[:-1] + [(train_seasons[-1], train_seasons[-1])] if False else train_pairs)
        # Le jeu d'entrainement utilise les saisons connues comme couples (train_i -> train_i+1)
        X_train, y_train = build_dataset([(train_seasons[j], train_seasons[j + 1]) for j in range(len(train_seasons) - 1)])
        X_test, y_test = build_dataset([(train_seasons[-1], test_season)])

        model = make_model()
        model.fit(X_train, y_train)

        train_acc = model.score(X_train, y_train)
        test_acc = model.score(X_test, y_test)
        results.append((test_season, len(y_train), len(y_test), train_acc, test_acc))

    return results


if __name__ == "__main__":
    print("=== Evaluation en cascade (walk-forward) ===\n")
    results = walk_forward_evaluation()
    total_test_matches = 0
    total_correct = 0
    for test_season, n_train, n_test, train_acc, test_acc in results:
        print(f"Test sur {test_season} : entrainement={n_train} matchs, test={n_test} matchs")
        print(f"  Reussite entrainement : {train_acc:.1%} | Reussite test : {test_acc:.1%}\n")
        total_test_matches += n_test
        total_correct += round(test_acc * n_test)

    global_rate = total_correct / total_test_matches
    print(f"=== Reussite globale sur tous les holdouts cumules : {global_rate:.1%} (sur {total_test_matches} matchs) ===")
