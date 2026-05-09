import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DB_URL = "postgresql://user:pwd@localhost:5432/betting_historical_data"


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
    np, pd, DMatrix, XGBRegressor = _require_runtime()
    train_mod = _load_training_module()

    model_spec = train_mod.resolve_model_spec(args.model)
    model_dir = args.model_dir or model_spec.default_final_model_dir
    model, feature_columns, metadata = _load_model(model_dir, XGBRegressor)

    min_shots = args.min_shots
    if min_shots is None:
        min_shots = metadata.get("min_shots")

    df = train_mod.load_dataset(
        db_url=args.db_url,
        labelled_only=True,
        model_spec=model_spec,
        min_shots=min_shots,
    )
    if df.empty:
        raise SystemExit("No labelled rows returned from dataset")

    df = train_mod.prepare_model_dataframe(df, pd, model_spec=model_spec)
    if args.max_rows > 0 and len(df) > args.max_rows:
        df = df.sample(n=args.max_rows, random_state=42)

    X = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    dmatrix = DMatrix(X, feature_names=feature_columns)
    contrib_matrix = model.get_booster().predict(dmatrix, pred_contribs=True)

    # pred_contribs adds a final bias term; keep only feature columns.
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

    print(f"Rows used for contribution summary: {len(df)}")
    print(f"Saved contribution CSV: {csv_path}")
    print(f"Saved contribution plot: {png_path}")
    print(f"Saved signed contribution CSV: {signed_csv_path}")
    print(f"Saved signed contribution plot: {signed_png_path}")


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

    args = parser.parse_args()

    if args.command == "gain":
        gain_importance(args)
    elif args.command == "contrib":
        mean_abs_contributions(args)


if __name__ == "__main__":
    main()
