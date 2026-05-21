import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"
ALL_MODELS = [
    "xg_for",
    "shots_for",
    "shots_against",
    "shots_on_target",
    "corners_for",
    "shot_quality",
    "fragility",
]
MODEL_COLORS = {
    "xg_for": "#1f77b4",
    "shots_for": "#ff7f0e",
    "shots_against": "#2ca02c",
    "shots_on_target": "#17becf",
    "corners_for": "#8c564b",
    "shot_quality": "#d62728",
    "fragility": "#9467bd",
}


def _require_plotting_dependencies():
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "matplotlib is required for chart output. Install with: pip install matplotlib"
        ) from exc
    return plt


def _require_runtime():
    try:
        import numpy as np
        import pandas as pd
        from xgboost import DMatrix, XGBRegressor
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing runtime dependencies. Install requirements with: pip install -r requirements.txt"
        ) from exc
    return np, pd, DMatrix, XGBRegressor


def _load_training_module():
    try:
        import xgboost_xg_model as train_mod
    except ModuleNotFoundError as exc:
        raise SystemExit("Could not import xgboost_xg_model.py from the project root") from exc
    return train_mod


def _load_model(model_dir: Path, XGBRegressor):
    model_path = model_dir / "model.json"
    feature_columns_path = model_dir / "feature_columns.json"
    metadata_path = model_dir / "metadata.json"

    if not model_path.exists() or not feature_columns_path.exists():
        raise SystemExit(f"Model artifacts not found in {model_dir}. Run training first.")

    model = XGBRegressor()
    model.load_model(model_path)
    feature_columns = json.loads(feature_columns_path.read_text(encoding="utf-8"))
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    )
    return model, feature_columns, metadata


def _write_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _plot_barh(plt, labels: list[str], values: list[float], title: str, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(6.0, min(24.0, 0.35 * max(1, len(labels))))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.barh(labels, values, color="#2b6cb0")
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("Contribution")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _plot_signed_barh(plt, labels: list[str], values: list[float], title: str, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(6.0, min(24.0, 0.35 * max(1, len(labels))))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    max_abs = max(abs(value) for value in values) if values else 1.0
    max_abs = max(max_abs, 1e-12)
    neutral_rgb = (0.65, 0.69, 0.75)  # grey
    pos_rgb = (0.10, 0.62, 0.35)      # green
    neg_rgb = (0.84, 0.22, 0.22)      # red
    colors = []
    for value in values:
        ratio = min(abs(value) / max_abs, 1.0)
        target = pos_rgb if value > 0 else neg_rgb if value < 0 else neutral_rgb
        # Proportional blend from neutral -> target by contribution magnitude.
        color = tuple(
            neutral_rgb[i] + ratio * (target[i] - neutral_rgb[i])
            for i in range(3)
        )
        colors.append(color)
    ax.barh(labels, values, color=colors)
    ax.invert_yaxis()
    ax.axvline(0.0, color="#1a202c", linewidth=1.0)
    ax.set_title(title)
    ax.set_xlabel("Mean signed contribution")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _compute_model_mean_abs_contrib(
    train_mod,
    model_name: str,
    model_dir_override: Path | None,
    db_url: str,
    max_rows: int,
    min_shots: int | None,
):
    np, pd, DMatrix, XGBRegressor = _require_runtime()
    model_spec = train_mod.resolve_model_spec(model_name)
    model_dir = model_dir_override or model_spec.default_final_model_dir
    model, feature_columns, metadata = _load_model(model_dir, XGBRegressor)

    effective_min_shots = min_shots
    if effective_min_shots is None:
        effective_min_shots = metadata.get("min_shots")

    df = train_mod.load_dataset(
        db_url=db_url,
        labelled_only=True,
        model_spec=model_spec,
        min_shots=effective_min_shots,
    )
    if df.empty:
        raise SystemExit(f"No labelled rows returned for model '{model_name}'")

    df = train_mod.prepare_model_dataframe(df, pd, model_spec=model_spec)
    if max_rows > 0 and len(df) > max_rows:
        df = df.sample(n=max_rows, random_state=42)

    X = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    dmatrix = DMatrix(X, feature_names=feature_columns)
    contrib_matrix = model.get_booster().predict(dmatrix, pred_contribs=True)
    feature_contribs = contrib_matrix[:, : len(feature_columns)]
    mean_abs = np.abs(feature_contribs).mean(axis=0)
    mean_signed = feature_contribs.mean(axis=0)

    rows = []
    for idx, feature in enumerate(feature_columns):
        rows.append(
            {
                "feature": feature,
                "mean_abs_contribution": float(mean_abs[idx]),
                "mean_signed_contribution": float(mean_signed[idx]),
            }
        )
    return rows, len(df)


def _match_identifier(match_id: int | None, sofascore_event_id: int | None) -> str:
    if match_id is not None:
        return f"match_{match_id}"
    return f"sofascore_event_{sofascore_event_id}"


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def _plot_match_contrib(
    plt,
    labels: list[str],
    values: list[float],
    title: str,
    output: Path,
    base_value: float,
    predicted_value: float,
    actual_value: float | None,
):
    output.parent.mkdir(parents=True, exist_ok=True)
    fig_height = max(7.0, min(26.0, 0.36 * max(1, len(labels)) + 1.2))
    fig, ax = plt.subplots(figsize=(13, fig_height))
    colors = ["#2f855a" if value >= 0 else "#c53030" for value in values]
    ax.barh(labels, values, color=colors)
    ax.axvline(0.0, color="#1a202c", linewidth=1.0)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("Per-feature contribution to prediction")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    actual_text = "n/a" if actual_value is None else f"{actual_value:.4f}"
    subtitle = (
        f"base={base_value:.4f}  predicted={predicted_value:.4f}  actual={actual_text}"
    )
    fig.text(0.01, 0.01, subtitle, fontsize=10)
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(output, dpi=180)
    plt.close(fig)


def gain_importance(args) -> None:
    plt = _require_plotting_dependencies()
    _, _, _, XGBRegressor = _require_runtime()
    train_mod = _load_training_module()

    model_spec = train_mod.resolve_model_spec(args.model)
    model_dir = args.model_dir or model_spec.default_final_model_dir
    model, feature_columns, _ = _load_model(model_dir, XGBRegressor)

    scores = model.get_booster().get_score(importance_type="gain")
    rows = [
        {"feature": feature, "gain": float(scores.get(feature, 0.0))}
        for feature in feature_columns
    ]
    rows.sort(key=lambda row: row["gain"], reverse=True)
    if args.top_n > 0:
        rows = rows[: args.top_n]

    csv_path = args.output_dir / f"{model_spec.name}_gain_importance.csv"
    _write_rows(csv_path, rows, ["feature", "gain"])

    labels = [row["feature"] for row in rows]
    values = [row["gain"] for row in rows]
    png_path = args.output_dir / f"{model_spec.name}_gain_importance.png"
    _plot_barh(
        plt,
        labels=labels,
        values=values,
        title=f"{model_spec.name}: XGBoost Gain Importance",
        output=png_path,
    )

    print(f"Saved gain importance CSV: {csv_path}")
    print(f"Saved gain importance plot: {png_path}")


def mean_abs_contributions(args) -> None:
    plt = _require_plotting_dependencies()
    train_mod = _load_training_module()

    model_spec = train_mod.resolve_model_spec(args.model)
    rows, used_rows = _compute_model_mean_abs_contrib(
        train_mod=train_mod,
        model_name=model_spec.name,
        model_dir_override=args.model_dir,
        db_url=args.db_url,
        max_rows=args.max_rows,
        min_shots=args.min_shots,
    )

    rows.sort(key=lambda row: row["mean_abs_contribution"], reverse=True)
    if args.top_n > 0:
        rows = rows[: args.top_n]

    csv_path = args.output_dir / f"{model_spec.name}_mean_abs_contributions.csv"
    _write_rows(
        csv_path,
        rows,
        ["feature", "mean_abs_contribution", "mean_signed_contribution"],
    )

    labels = [row["feature"] for row in rows]
    values = [row["mean_abs_contribution"] for row in rows]
    png_path = args.output_dir / f"{model_spec.name}_mean_abs_contributions.png"
    _plot_barh(
        plt,
        labels=labels,
        values=values,
        title=f"{model_spec.name}: Mean Absolute Feature Contribution",
        output=png_path,
    )

    signed_rows = sorted(rows, key=lambda row: row["mean_signed_contribution"], reverse=True)
    signed_csv_path = args.output_dir / f"{model_spec.name}_signed_contributions.csv"
    _write_rows(
        signed_csv_path,
        signed_rows,
        ["feature", "mean_abs_contribution", "mean_signed_contribution"],
    )

    signed_labels = [row["feature"] for row in signed_rows]
    signed_values = [row["mean_signed_contribution"] for row in signed_rows]
    signed_png_path = args.output_dir / f"{model_spec.name}_signed_contributions.png"
    _plot_signed_barh(
        plt,
        labels=signed_labels,
        values=signed_values,
        title=f"{model_spec.name}: Mean Signed Feature Contribution",
        output=signed_png_path,
    )

    print(f"Rows used for contribution summary: {used_rows}")
    print(f"Saved contribution CSV: {csv_path}")
    print(f"Saved contribution plot: {png_path}")
    print(f"Saved signed contribution CSV: {signed_csv_path}")
    print(f"Saved signed contribution plot: {signed_png_path}")


def compare_abs_contributions(args) -> None:
    plt = _require_plotting_dependencies()
    train_mod = _load_training_module()

    model_rows: dict[str, dict[str, float]] = {}
    row_counts: dict[str, int] = {}
    for model_name in ALL_MODELS:
        rows, used_rows = _compute_model_mean_abs_contrib(
            train_mod=train_mod,
            model_name=model_name,
            model_dir_override=None,
            db_url=args.db_url,
            max_rows=args.max_rows,
            min_shots=args.min_shots,
        )
        model_rows[model_name] = {
            row["feature"]: row["mean_abs_contribution"] for row in rows
        }
        row_counts[model_name] = used_rows

    feature_order = sorted(
        model_rows["xg_for"].keys(),
        key=lambda feature: sum(model_rows[model].get(feature, 0.0) for model in ALL_MODELS),
        reverse=True,
    )

    csv_rows: list[dict[str, Any]] = []
    for feature in feature_order:
        row = {"feature": feature}
        for model_name in ALL_MODELS:
            row[f"{model_name}_mean_abs_contribution"] = model_rows[model_name].get(
                feature,
                0.0,
            )
        csv_rows.append(row)

    csv_path = args.output_dir / "all_models_mean_abs_contributions_side_by_side.csv"
    contribution_fields = [
        f"{model_name}_mean_abs_contribution" for model_name in ALL_MODELS
    ]
    _write_rows(
        csv_path,
        csv_rows,
        ["feature", *contribution_fields],
    )

    # One horizontal grouped-bar figure containing all features.
    fig_height = max(18.0, 0.32 * len(feature_order))
    fig, ax = plt.subplots(figsize=(18, fig_height))
    y_positions = list(range(len(feature_order)))
    bar_width = min(0.8 / max(1, len(ALL_MODELS)), 0.16)
    center = (len(ALL_MODELS) - 1) / 2.0

    for idx, model_name in enumerate(ALL_MODELS):
        values = [model_rows[model_name].get(feature, 0.0) for feature in feature_order]
        offset = (idx - center) * bar_width
        y = [position + offset for position in y_positions]
        ax.barh(
            y,
            values,
            height=bar_width,
            color=MODEL_COLORS.get(model_name, "#4a5568"),
            label=model_name,
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(feature_order)
    ax.invert_yaxis()
    ax.set_xlabel("Mean absolute contribution")
    ax.set_title("Mean Absolute Feature Contributions Across All XGBoost Models")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()

    png_path = args.output_dir / "all_models_mean_abs_contributions_side_by_side.png"
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=180)
    plt.close(fig)

    print(f"Saved combined CSV: {csv_path}")
    print(f"Saved combined plot: {png_path}")
    print("Rows used per model:")
    for model_name in ALL_MODELS:
        print(f"  {model_name}: {row_counts[model_name]}")


def match_shap(args) -> None:
    plt = _require_plotting_dependencies()
    np, pd, DMatrix, XGBRegressor = _require_runtime()
    train_mod = _load_training_module()

    if args.match_id is None and args.sofascore_event_id is None:
        raise SystemExit("match-shap requires --match-id or --sofascore-event-id")

    match_tag = _match_identifier(args.match_id, args.sofascore_event_id)
    match_output_dir = args.output_dir / match_tag
    match_output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []

    for model_name in ALL_MODELS:
        model_spec = train_mod.resolve_model_spec(model_name)
        model_dir = model_spec.default_final_model_dir
        model, feature_columns, metadata = _load_model(model_dir, XGBRegressor)
        clip_min = float(metadata.get("clip_min", model_spec.clip_min))
        clip_max = float(metadata.get("clip_max", model_spec.clip_max))

        min_shots = args.min_shots
        if min_shots is None:
            min_shots = metadata.get("min_shots")

        df = train_mod.load_dataset(
            db_url=args.db_url,
            labelled_only=False,
            match_id=args.match_id,
            sofascore_event_id=args.sofascore_event_id,
            model_spec=model_spec,
            min_shots=min_shots,
        )
        if df.empty:
            raise SystemExit(f"No feature rows found for {match_tag}")
        df = train_mod.prepare_model_dataframe(df, pd, model_spec=model_spec)
        X = df[feature_columns].apply(pd.to_numeric, errors="coerce")

        predictions = model.predict(X)
        predictions = train_mod.clip_predictions(
            predictions,
            clip_min=clip_min,
            clip_max=clip_max,
            np=np,
        )

        dmatrix = DMatrix(X, feature_names=feature_columns)
        contrib_matrix = model.get_booster().predict(dmatrix, pred_contribs=True)
        feature_contribs = contrib_matrix[:, : len(feature_columns)]
        bias_values = contrib_matrix[:, len(feature_columns)]

        for row_idx, row in df.reset_index(drop=True).iterrows():
            contrib_pairs = [
                (feature_columns[i], float(feature_contribs[row_idx, i]))
                for i in range(len(feature_columns))
            ]
            contrib_pairs.sort(key=lambda item: abs(item[1]), reverse=True)
            if args.top_n > 0:
                contrib_pairs = contrib_pairs[: args.top_n]

            side = str(row.get("side", "team"))
            team_name = str(row.get("team_name", f"team_{row_idx+1}"))
            team_slug = _safe_slug(f"{side}_{team_name}")

            predicted_value = float(predictions[row_idx])
            actual_raw = row.get(model_spec.target_column)
            actual_value = None
            if pd.notna(actual_raw):
                actual_value = float(actual_raw)

            chart_path = (
                match_output_dir
                / f"{match_tag}_{team_slug}_{model_name}_match_shap.png"
            )
            _plot_match_contrib(
                plt=plt,
                labels=[item[0] for item in contrib_pairs],
                values=[item[1] for item in contrib_pairs],
                title=f"{team_name} ({side}) - {model_name}",
                output=chart_path,
                base_value=float(bias_values[row_idx]),
                predicted_value=predicted_value,
                actual_value=actual_value,
            )

            csv_path = (
                match_output_dir
                / f"{match_tag}_{team_slug}_{model_name}_match_shap.csv"
            )
            csv_rows = [
                {"feature": feature, "contribution": contribution}
                for feature, contribution in contrib_pairs
            ]
            _write_rows(csv_path, csv_rows, ["feature", "contribution"])

            summary_rows.append(
                {
                    "match_tag": match_tag,
                    "team_name": team_name,
                    "side": side,
                    "model": model_name,
                    "target_column": model_spec.target_column,
                    "actual_value": actual_value,
                    "predicted_value": predicted_value,
                    "base_value": float(bias_values[row_idx]),
                    "chart_path": str(chart_path),
                    "csv_path": str(csv_path),
                }
            )

    summary_path = match_output_dir / f"{match_tag}_team_model_predictions_summary.csv"
    _write_rows(
        summary_path,
        summary_rows,
        [
            "match_tag",
            "team_name",
            "side",
            "model",
            "target_column",
            "actual_value",
            "predicted_value",
            "base_value",
            "chart_path",
            "csv_path",
        ],
    )
    print(f"Saved match SHAP outputs to: {match_output_dir}")
    print(f"Saved summary CSV: {summary_path}")


def main() -> None:
    train_mod = _load_training_module()

    parser = argparse.ArgumentParser(
        description=(
            "Visualize feature influence for trained XGBoost rate models. "
            "Supports gain importance and SHAP-style contribution summaries."
        )
    )
    parser.add_argument(
        "--model",
        choices=sorted(train_mod.MODEL_SPECS),
        default="xg_for",
        help="Model target to inspect.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Directory containing model.json and feature_columns.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/visualisations"),
        help="Directory to write CSV and PNG files.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="Top features to include in chart and CSV. Use <=0 for all features.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "gain",
        help="Plot built-in XGBoost gain importance from the trained model booster.",
    )

    contrib_parser = subparsers.add_parser(
        "contrib",
        help=(
            "Compute mean absolute per-feature contributions over labelled rows "
            "using booster pred_contribs output."
        ),
    )
    contrib_parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL.",
    )
    contrib_parser.add_argument(
        "--max-rows",
        type=int,
        default=10000,
        help="Maximum labelled rows to sample for contributions. Use <=0 for all rows.",
    )
    contrib_parser.add_argument(
        "--min-shots",
        type=int,
        default=None,
        help="Optional min shots override for shot_quality/fragility rows.",
    )
    compare_parser = subparsers.add_parser(
        "compare-abs",
        help=(
            "Create one side-by-side chart of mean absolute contributions for all features "
            "across all configured models."
        ),
    )
    compare_parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL.",
    )
    compare_parser.add_argument(
        "--max-rows",
        type=int,
        default=10000,
        help="Maximum labelled rows to sample per model. Use <=0 for all rows.",
    )
    compare_parser.add_argument(
        "--min-shots",
        type=int,
        default=None,
        help="Optional min shots override for shot_quality/fragility rows.",
    )
    match_parser = subparsers.add_parser(
        "match-shap",
        help=(
            "Create per-team SHAP-style contribution plots for a single match, "
            "plus actual/predicted summary values for each model."
        ),
    )
    match_parser.add_argument(
        "--db-url",
        default=os.getenv("DB_URL", DEFAULT_DB_URL),
        help="Postgres connection URL.",
    )
    match_parser.add_argument("--match-id", type=int)
    match_parser.add_argument("--sofascore-event-id", type=int)
    match_parser.add_argument(
        "--min-shots",
        type=int,
        default=None,
        help="Optional min shots override for shot_quality/fragility rows.",
    )
    match_parser.add_argument(
        "--top-n",
        type=int,
        default=25,
        help="Top contribution features per team chart. Use <=0 for all features.",
    )

    args = parser.parse_args()

    if args.command == "gain":
        gain_importance(args)
    elif args.command == "contrib":
        mean_abs_contributions(args)
    elif args.command == "compare-abs":
        compare_abs_contributions(args)
    elif args.command == "match-shap":
        match_shap(args)


if __name__ == "__main__":
    main()
