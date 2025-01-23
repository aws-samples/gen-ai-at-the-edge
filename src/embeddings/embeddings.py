# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
import gevent.monkey

gevent.monkey.patch_all()

from gevent.pywsgi import WSGIServer
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import numpy as np
import json
import os
import logging
from flask_wtf.csrf import CSRFProtect

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)
csrf = CSRFProtect(app)

# A secret key is required to use CSRF
app.config["WTF_CSRF_ENABLED"] = True
SECRET_KEY = os.urandom(32)
app.config["SECRET_KEY"] = SECRET_KEY


# Custom JSON encoder to handle numpy arrays
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)


# Initialize the model globally
model = None
try:
    model = SentenceTransformer("/opt/slm/models/all-MiniLM-L6-v2/")
    logger.info("Loaded model from local path")
except Exception as e:
    # Changed to info level since we're handling the exception with a fallback
    logger.info(f"Could not load local model, attempting download: {e}")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


@app.route("/get_embeddings", methods=["POST"])
@csrf.exempt
def get_embeddings():
    try:
        data = request.get_json()

        if not data or "text" not in data:
            return (
                jsonify(
                    {
                        "error": 'No text provided. Please send a JSON with a "text" field.'
                    }
                ),
                400,
            )

        text = data["text"]
        if not isinstance(text, str):
            return jsonify({"error": "Text must be a string"}), 400

        embeddings = model.encode(text)

        # Changed from json.dumps to jsonify
        return jsonify(
            {
                "success": True,
                "embeddings": embeddings.tolist(),  # Convert numpy array to list
            }
        )

    except Exception as e:
        # Changed to warning level since we're handling the exception by returning an error response
        logger.warning(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    http_server = WSGIServer(("", 5050), app)
    logger.info("Starting server on port 5050")
    http_server.serve_forever()
