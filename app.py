from flask import Flask, request, jsonify
from flair.embeddings import FlairEmbeddings
import flair


app = Flask(__name__)


model_names = ["de-forward", "de-backward"]

if app.debug:
    flair.cache_root = "flair_cache"
else:
    flair.cache_root = "/flair_cache"


@app.route("/score", methods=["POST"])
def flair_score():
    input_texts = request.get_json()["texts"]

    lms = [FlairEmbeddings(x).lm for x in model_names]

    results = map(
        lambda x: sum([lm.calculate_perplexity(x) for lm in lms]), input_texts
    )

    return jsonify([float(r) for r in results])
