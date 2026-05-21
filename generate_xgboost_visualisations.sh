#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_DIR="${OUTPUT_DIR:-models/visualisations}"
TOP_N="${TOP_N:-25}"
MAX_ROWS="${MAX_ROWS:-10000}"

MODELS=(
  xg_for
  shots_for
  shots_against
  shots_on_target
  corners_for
  shot_quality
  fragility
)

SCRIPT_PATH="xgboost_model_visualisation.py"
if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Could not find $SCRIPT_PATH in current directory: $(pwd)" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Generating XGBoost visualisations"
echo "Python: $PYTHON_BIN"
echo "Output dir: $OUTPUT_DIR"
echo "Top N: $TOP_N"
echo "Max rows: $MAX_ROWS"

for model in "${MODELS[@]}"; do
  echo ""
  echo "[$model] gain importance"
  "$PYTHON_BIN" "$SCRIPT_PATH" \
    --model "$model" \
    --output-dir "$OUTPUT_DIR" \
    --top-n "$TOP_N" \
    gain

  echo "[$model] contribution summaries"
  "$PYTHON_BIN" "$SCRIPT_PATH" \
    --model "$model" \
    --output-dir "$OUTPUT_DIR" \
    --top-n "$TOP_N" \
    contrib \
    --max-rows "$MAX_ROWS"
done

echo ""
echo "Done. Visualisations written to $OUTPUT_DIR"
