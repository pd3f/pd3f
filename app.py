from flask import Flask, request, jsonify
from flair.embeddings import FlairEmbeddings
import flair
flair.cache_root = '/mnt/data/flair_models'


app = Flask(__name__)


@app.route('/score/', methods=['POST'])
def flair_score():
    input_texts = request.get_json()['texts']

    lms = [FlairEmbeddings('de-forward').lm, FlairEmbeddings('de-backward').lm]

    results = map(lambda x: sum(
        [lm.calculate_perplexity(x) for lm in lms]), input_texts)

    return jsonify([float(r) for r in results])
