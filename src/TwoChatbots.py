# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Import gevent for async operations and patch Python's standard library
import gevent.monkey

gevent.monkey.patch_all()

# Import necessary libraries and modules
from flask import Flask, render_template, request
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

# Configuration Management
# Read the configuration file
config = configparser.ConfigParser()
config.read("config.ini")

# Exit if configuration file is not found
if not config:
    print("Error: Config file not found")
    sys.exit(-1)

# Get logging configuration parameters
LOG_FOLDER = config.get("DEFAULT", "LOG_Folder")
LOG_LEVEL = config.get("DEFAULT", "LOG_Level")

# Create logging directory if it doesn't exist
if not os.path.isdir(LOG_FOLDER):
    os.mkdir(LOG_FOLDER)

# Validate logging level
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    print("Error: Config file not found")
    sys.exit(-1)

# Configure logging settings
logger = logging.getLogger("TwoChatbots")
logging.basicConfig(
    filename=LOG_FOLDER + "twochatbots.log",
    level=LOG_LEVEL,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %I:%M:%S %p",
)

# Get model names from configuration
SLM1_MODEL_NAME = config.get("DEFAULT", "SLM1_model_name")
SLM2_MODEL_NAME = config.get("DEFAULT", "SLM2_model_name")

# Configure model endpoints
MODEL_ENDPOINTS = {
    SLM1_MODEL_NAME: config.get("DEFAULT", "SLM1_endpoint"),
    SLM2_MODEL_NAME: config.get("DEFAULT", "SLM2_endpoint"),
}

# Get application configuration parameters
PORT = config.getint("TwoChatbots", "Port")
TOKENS_TO_PREDICT = config.getint("TwoChatbots", "TokensToPredict")
STREAM_OUTPUT = config.getboolean("TwoChatbots", "StreamOutput")
TIMEOUT = config.getint("TwoChatbots", "Timeout")
INITIAL_PROMPT = config.get("DEFAULT", "Initial_prompt")


# Route Handlers
# Home page route
@app.route("/")
def home():
    return render_template("twochatbots.html")


# Streaming response route
@app.route("/stream", methods=["POST"])
def stream_response():
    # Get request parameters
    prompt = request.json["message"]
    bot_id = request.json["bot_id"]
    # Select appropriate model endpoint based on bot_id
    service_url = (
        MODEL_ENDPOINTS[SLM1_MODEL_NAME]
        if bot_id == 1
        else MODEL_ENDPOINTS[SLM2_MODEL_NAME]
    )

    # Prepare request payload
    payload = {
        "prompt": "USER:\n" + INITIAL_PROMPT + prompt + "\nASSISTANT:",
        "n_predict": TOKENS_TO_PREDICT,
        "stream": STREAM_OUTPUT,
    }

    headers = {"Content-Type": "application/json"}

    # Function to process streaming response
    def process_stream(queue):
        buffer = ""

        try:
            # Make HTTP request to model endpoint
            response = requests.post(
                service_url, json=payload, headers=headers, stream=True, timeout=TIMEOUT
            )
            response.raise_for_status()

            with response:
                # Process response stream chunk by chunk
                for chunk in response.iter_content(chunk_size=1):
                    if chunk:
                        chunk_str = chunk.decode("utf-8", errors="ignore")
                        buffer += chunk_str

                        # Process complete messages (ending with newline)
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

                # Process any remaining data in buffer
                if buffer:
                    queue.put(buffer)

        # Exception handling for various HTTP and connection errors
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
            queue.put(None)  # Signal end of stream

    # Generator function for streaming response
    def generate_stream():
        queue = Queue()
        thread = threading.Thread(target=process_stream, args=(queue,))
        thread.start()
        while True:
            data = queue.get()
            if data is None:  # Check for end signal
                break
            yield data

        thread.join()  # Wait for processing thread to complete

    return app.response_class(generate_stream(), mimetype="application/json")


# Main entry point
if __name__ == "__main__":
    # Start WSGI server
    http_server = WSGIServer(("", PORT), app)
    http_server.serve_forever()
