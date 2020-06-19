import os

import flair
import redis
from flair.embeddings import FlairEmbeddings
from flask import Flask, jsonify, request
from rq import Queue

# choose some flair language models
model_names = ["de-forward", "de-backward"]

app = Flask(__name__)

if app.debug:
    r = redis.Redis()
    flair.cache_root = "flair_cache"
else:
    r = redis.from_url(os.environ["REDIS_URL"])
    flair.cache_root = "/flair_cache"

q = Queue(connection=r)


def get_scores(texts):
    lms = [FlairEmbeddings(x).lm for x in model_names]

    results = map(lambda x: sum([lm.calculate_perplexity(x) for lm in lms]), texts)
    return [float(r) for r in results]


@app.route("/score", methods=["POST"])
def flair_score():
    input_texts = request.get_json()["texts"]

    results = get_scores(input_texts)

    return jsonify(results)


@app.route("/score_async", methods=["POST"])
def flair_score_async():
    input_texts = request.get_json()["texts"]

    job = q.enqueue(get_scores, input_texts)

    return jsonify({"id": job.get_id()})


@app.route("/results/<id>", methods=["GET"])
def get_results(id):
    j = q.fetch_job(id)

    if j.is_finished:
        return jsonify(j.result)
    else:
        return "Nay!", 202
