# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Import required libraries
import gevent.monkey

# Patch Python's standard library for gevent compatibility
gevent.monkey.patch_all()

# Import necessary modules
from flask import Flask, request, render_template
import requests
import json
import threading
from queue import Queue
from gevent.pywsgi import WSGIServer
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
config = configparser.ConfigParser()
config.read("config.ini")

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
logger = logging.getLogger("SimpleChatbot")
logging.basicConfig(
    filename=LOG_FOLDER + "simplechatbot.log",
    level=LOG_LEVEL,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %I:%M:%S %p",
)

SLM1_MODEL_NAME = config.get("DEFAULT", "SLM1_model_name")
SLM2_MODEL_NAME = config.get("DEFAULT", "SLM2_model_name")

# SLM parameters and endpoints for different models
MODEL_ENDPOINTS = {
    SLM1_MODEL_NAME: config.get("DEFAULT", "SLM1_endpoint"),
    SLM2_MODEL_NAME: config.get("DEFAULT", "SLM2_endpoint"),
}

# Get other configuration parameters
INITIAL_PROMPT = config.get("DEFAULT", "Initial_prompt")
PORT = config.getint("SimpleChatbot", "Port")
TOKENS_TO_PREDICT = config.getint("SimpleChatbot", "TokensToPredict")
STREAM_OUTPUT = config.getboolean("SimpleChatbot", "StreamOutput")
TIMEOUT = config.getint("SimpleChatbot", "Timeout")


# Route for the main page
@app.route("/")
def index():
    return render_template("simplechatbot.html")


# Route for text generation
@app.route("/generate", methods=["POST"])
def generate():
    # Get data from request
    data = request.json
    prompt = request.json["prompt"]
    model = data.get("model", SLM1_MODEL_NAME)

    # Prepare payload for the model
    payload = {
        "prompt": "USER:\n" + INITIAL_PROMPT + prompt + "\nASSISTANT:",
        "n_predict": TOKENS_TO_PREDICT,
        "stream": STREAM_OUTPUT,
    }

    headers = {"Content-Type": "application/json"}

    # Function to process the stream of data from the model
    def process_stream(queue):
        buffer = ""
        try:
            # Make request to model endpoint
            response = requests.post(
                MODEL_ENDPOINTS[model],
                json=payload,
                headers=headers,
                stream=STREAM_OUTPUT,
                timeout=TIMEOUT,
            )
            response.raise_for_status()

            # Process streaming response
            with response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=1):
                    if chunk:
                        chunk_str = chunk.decode("utf-8", errors="ignore")
                        buffer += chunk_str

                        # Process complete JSON objects
                        if buffer.endswith("\n"):
                            try:
                                data_json = json.loads(buffer.strip())
                                queue.put(json.dumps(data_json) + "\n")
                                if data_json.get("stop", False):
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

    # Generator function to yield streaming responses
    def generate_stream():
        queue = Queue()
        thread = threading.Thread(target=process_stream, args=(queue,))
        thread.start()

        while True:
            data_result = queue.get()
            if data_result is None:
                break
            yield data_result

        thread.join()

    return app.response_class(generate_stream(), mimetype="application/json")


# Start the server
if __name__ == "__main__":
    http_server = WSGIServer(("", PORT), app)
    http_server.serve_forever()
