# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Import gevent monkey patching to make async operations work properly
import gevent.monkey

# Apply monkey patching to all modules
gevent.monkey.patch_all()

# Import required libraries
from flask import Flask, render_template, request
import requests
import json
import threading
from queue import Queue
from gevent.pywsgi import WSGIServer
import numpy as np
from common.VectorEmbeddings import VectorEmbeddings
from common.VectorDatabase import VectorDatabase
import configparser
import sys
import logging
import os
from flask_wtf.csrf import CSRFProtect


# Initialize Flask application
app = Flask(__name__)
csrf = CSRFProtect(app)

# A secret key is required to use CSRF
app.config["WTF_CSRF_ENABLED"] = True
SECRET_KEY = os.urandom(32)
app.config["SECRET_KEY"] = SECRET_KEY

# Configuration file handling
# Read config.ini file
config_file_name = "config.ini"
config = configparser.ConfigParser()
config.read(config_file_name)

# Exit if config file not found
if not config:
    print("Error: Config file not found")
    sys.exit(-1)

# Get logging configuration from config file
LOG_FOLDER = config.get("DEFAULT", "LOG_Folder")
LOG_LEVEL = config.get("DEFAULT", "LOG_Level")

# Create log directory if it doesn't exist
if not os.path.isdir(LOG_FOLDER):
    os.mkdir(LOG_FOLDER)

# Validate log level
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    print("Error: Config file not found")
    sys.exit(-1)

# Set up logging configuration
logger = logging.getLogger("rag")
logging.basicConfig(
    filename=LOG_FOLDER + "rag.log",
    level=LOG_LEVEL,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %I:%M:%S %p",
)

# Get model names from config
SLM1_MODEL_NAME = config.get("DEFAULT", "SLM1_model_name")
SLM2_MODEL_NAME = config.get("DEFAULT", "SLM2_model_name")

# SLM parameters and endpoints for different models
MODEL_ENDPOINTS = {
    SLM1_MODEL_NAME: config.get("DEFAULT", "SLM1_endpoint"),
    SLM2_MODEL_NAME: config.get("DEFAULT", "SLM2_endpoint"),
}
INITIAL_PROMPT = config.get("DEFAULT", "Initial_prompt")

# Get RAG configuration parameters
PORT = config.getint("RAG", "Port")
TOKENS_TO_PREDICT = config.getint("RAG", "TokensToPredict")
STREAM_OUTPUT = config.getboolean("RAG", "StreamOutput")
TIMEOUT = config.getint("RAG", "Timeout")
SIMILAR_THRESHOLD = config.getfloat("RAG", "SimilarityThreshold")
LIMIT = config.getint("RAG", "Limit")

# Initialize vector embeddings and database
vector_embeddings = VectorEmbeddings(config_file_name)
vector_database = VectorDatabase(config_file_name)


# Route for home page
@app.route("/")
def home():
    return render_template("RAG.html")


# Route for handling streaming responses
@app.route("/stream", methods=["POST"])
def stream_response():
    # Get request parameters
    prompt = request.json["message"]
    bot_id = request.json["bot_id"]
    use_rag = request.json["use_rag"]
    service_url = MODEL_ENDPOINTS[SLM1_MODEL_NAME]

    rag_text = ""

    # If RAG is enabled, get similar texts from vector database
    if use_rag:
        # Get vector embeddings for the query
        query_embeddings = vector_embeddings.get_vector_embeddings(prompt)
        query_embedding = np.array(query_embeddings)

        # Search for similar texts
        similar_texts = vector_database.search_similar_texts(
            query_embedding, limit=LIMIT, similarity_threshold=SIMILAR_THRESHOLD
        )

        # Process similar texts
        for text, distance in similar_texts:
            rag_text = text
            message = f"RAG: {rag_text}, Distance: {distance}"
            print(message)
            logger.info(message)

    # Prepare payload for the language model
    payload = {
        "prompt": INITIAL_PROMPT + " " + rag_text + " " + prompt,
        "n_predict": TOKENS_TO_PREDICT,
        "stream": STREAM_OUTPUT,
    }

    headers = {"Content-Type": "application/json"}

    # Function to process the streaming response
    def process_stream(queue):
        buffer = ""

        try:
            # Make POST request to the service
            response = requests.post(
                service_url, json=payload, headers=headers, stream=True, timeout=TIMEOUT
            )
            response.raise_for_status()

            with response:
                response.raise_for_status()

                # Process response stream chunk by chunk
                for chunk in response.iter_content(chunk_size=1):
                    if chunk:
                        chunk_str = chunk.decode("utf-8", errors="ignore")
                        buffer += chunk_str

                        # Process complete JSON objects
                        if buffer.endswith("\n"):
                            try:
                                data = json.loads(buffer.strip())
                                queue.put(json.dumps(data) + "\n")
                                if data.get("stop", False):
                                    break
                            except json.JSONDecodeError as jdc:
                                error_message = f"E: {str(jdc)} {buffer}"
                                print(error_message)
                                logger.error(error_message)
                                queue.put(buffer)
                            buffer = ""

                # Process any remaining data
                if buffer:
                    queue.put(buffer)

        # Handle various exceptions
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            queue.put(json.dumps({"error": f"HTTP error occurred: {http_err}"}) + "\n")
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Connection error occurred: {conn_err}")
            queue.put(
                json.dumps({"error": f"Connection error occurred: {conn_err}"}) + "\n"
            )
        except requests.exceptions.Timeout as timeout_err:
            logger.error(f"Timeout error occurred: {timeout_err}")
            queue.put(
                json.dumps({"error": f"Timeout error occurred: {timeout_err}"}) + "\n"
            )
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Request error occurred: {req_err}")
            queue.put(
                json.dumps({"error": f"Request error occurred: {req_err}"}) + "\n"
            )
        except Exception as e:
            logger.error(str(e))
            queue.put(json.dumps({"error": str(e)}) + "\n")
        finally:
            queue.put(None)

    # Generator function to yield streaming response
    def generate_stream():
        queue = Queue()
        thread = threading.Thread(target=process_stream, args=(queue,))
        thread.start()

        while True:
            data = queue.get()
            if data is None:  # Check for the end signal
                break
            yield data

        thread.join()  # Wait for the thread to complete

    return app.response_class(generate_stream(), mimetype="application/json")


# Start the server if running as main
if __name__ == "__main__":
    http_server = WSGIServer(("", PORT), app)
    http_server.serve_forever()
