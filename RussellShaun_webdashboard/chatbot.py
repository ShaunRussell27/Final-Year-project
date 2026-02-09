import os
import time
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS

from burnout_model import BurnoutIsolationForestModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_PATH = os.path.join(BASE_DIR, "burnout_model.joblib")

os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)
CORS(app)

model = BurnoutIsolationForestModel(MODEL_PATH)
model.load()


def _load_training_data():
	csv_files = [
		os.path.join(DATA_DIR, f)
		for f in os.listdir(DATA_DIR)
		if f.lower().endswith(".csv")
	]
	if not csv_files:
		return None

	frames = []
	for path in csv_files:
		try:
			frames.append(pd.read_csv(path))
		except Exception:
			continue

	if not frames:
		return None
	return pd.concat(frames, ignore_index=True)


@app.route("/health", methods=["GET"])
def health():
	return jsonify({"status": "ok", "model_loaded": model.model is not None})


@app.route("/train", methods=["POST"])
def train():
	df = _load_training_data()
	if df is None or df.empty:
		return jsonify({"error": "No training data found in data/ folder"}), 400

	try:
		model.fit_from_dataframe(df)
		return jsonify({
			"status": "trained",
			"rows": int(len(df)),
			"metrics_used": model.metrics,
		})
	except Exception as exc:
		return jsonify({"error": str(exc)}), 500


@app.route("/upload", methods=["POST"])
def upload():
	if "file" in request.files:
		file = request.files["file"]
		if not file.filename:
			return jsonify({"error": "Empty filename"}), 400

		filename = f"upload_{int(time.time())}.csv"
		save_path = os.path.join(DATA_DIR, filename)
		file.save(save_path)
		return jsonify({"status": "uploaded", "file": filename})

	payload = request.get_json(silent=True) or {}
	records = payload.get("records") or payload.get("data")
	if not records:
		return jsonify({"error": "No file or JSON records provided"}), 400

	try:
		df = pd.DataFrame(records)
		filename = f"upload_{int(time.time())}.csv"
		save_path = os.path.join(DATA_DIR, filename)
		df.to_csv(save_path, index=False)
		return jsonify({"status": "uploaded", "file": filename, "rows": int(len(df))})
	except Exception as exc:
		return jsonify({"error": str(exc)}), 500


@app.route("/predict", methods=["POST"])
def predict():
	if model.model is None:
		return jsonify({"error": "Model not trained. Upload data and call /train first."}), 400

	data = request.get_json(silent=True) or {}
	if not data:
		return jsonify({"error": "Missing JSON body"}), 400

	try:
		result = model.predict_from_dict(data)
		return jsonify(result)
	except Exception as exc:
		return jsonify({"error": str(exc)}), 500


@app.route("/", methods=["GET"])
def index():
	return jsonify({
		"message": "Burnout Detection API",
		"endpoints": {
			"/upload": "POST - upload CSV or JSON records",
			"/train": "POST - train the Isolation Forest model",
			"/predict": "POST - predict burnout risk",
			"/health": "GET - health check",
		},
	})


if __name__ == "__main__":
	print("Starting Burnout Detection API...")
	print("Data folder:", DATA_DIR)
	app.run(debug=True, host="127.0.0.1", port=5000)
