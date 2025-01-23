# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
import gevent.monkey

gevent.monkey.patch_all()

from flask import Flask, render_template, request, jsonify
import boto3
from werkzeug.utils import secure_filename
from botocore.exceptions import ClientError
from gevent.pywsgi import WSGIServer
from utils.PDFToJSON import PDFToJSON
from common.VectorEmbeddings import VectorEmbeddings
from common.VectorDatabase import VectorDatabase
import configparser
import sys
import json
from typing import List
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
logger = logging.getLogger("Knowledgebase")
logging.basicConfig(
    filename=LOG_FOLDER + "knowledgebase.log",
    level=LOG_LEVEL,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %I:%M:%S %p",
)

app.config["MAX_CONTENT_LENGTH"] = config.getint("KnowledgeBase", "PDFMaxSize")
BUCKET_NAME = config.get("KnowledgeBase", "BucketName")
REGION_NAME = config.get("KnowledgeBase", "RegionName")
PORT = config.getint("KnowledgeBase", "Port")
CHUNK_SIZE = config.getint("KnowledgeBase", "ChunkSize")
OVERLAP = config.getfloat("KnowledgeBase", "Overlap")
SAVEFILETOS3 = config.getboolean("KnowledgeBase", "SavePDFFileToS3")

vector_embeddings = VectorEmbeddings(config_file_name)
vector_database = VectorDatabase(config_file_name)


def read_and_concatenate_text(json_data):
    try:
        # Check if the required structure exists
        if not isinstance(json_data, dict) or "pages" not in json_data:
            error_message = "Invalid JSON structure: 'pages' key not found"
            logger.error(error_message)
            raise ValueError(error_message)

        # Initialize empty string for concatenated text
        concatenated_text = ""

        # Iterate through all pages and concatenate full_text
        for page_num in sorted(json_data["pages"].keys(), key=int):
            page = json_data["pages"][page_num]
            if "full_text" in page:
                concatenated_text += page["full_text"] + "\n"
            else:
                message = f"Warning: 'full_text' not found in page {page_num}"
                print(message)
                logger.error(message)

        return concatenated_text.strip()

    except FileNotFoundError as fnfe:
        error_message = f"Error: {str(fnfe)} File not found"
        logger.error(error_message)
        print(error_message)
        return None
    except json.JSONDecodeError as jdc:
        error_message = f"Error: {str(jdc)} Invalid JSON format in file"
        logger.error(error_message)
        print(error_message)
        return None
    except Exception as e:
        error_message = f"Error: An unexpected error occurred: {str(e)}"
        logger.error(error_message)
        print(error_message)
        return None


def create_chunks(text: str, chunk_size: int = 1024, overlap: float = 0.1) -> List[str]:
    """
    Splits text into chunks of specified size with overlap.

    Args:
        text (str): Text to be split into chunks
        chunk_size (int): Size of each chunk in characters
        overlap (float): Overlap percentage between chunks (0.0 to 1.0)

    Returns:
        List[str]: List of text chunks
    """
    if not text:
        return []

    # Calculate overlap size in characters
    overlap_size = int(chunk_size * overlap)

    # Initialize variables
    chunks = []
    start_pos = 0
    text_length = len(text)

    while start_pos < text_length:
        # Calculate end position for current chunk
        end_pos = start_pos + chunk_size

        # If this is not the last chunk, try to break at a space
        if end_pos < text_length:
            # Look for the last space within the chunk
            space_pos = text[start_pos:end_pos].rfind(" ")
            if space_pos != -1:
                end_pos = start_pos + space_pos

        # Extract the chunk
        chunk = text[start_pos:end_pos].strip()
        if chunk:  # Only add non-empty chunks
            chunks.append(chunk)

        # Calculate next start position considering overlap
        start_pos = end_pos - overlap_size if end_pos < text_length else text_length

    return chunks


def upload_to_outposts(file_path, bucket_name, object_name, region):
    """
    Upload a file to an S3 bucket on Outposts

    Parameters:
    - file_path: Path to the file to upload
    - bucket_name: Name of the S3 bucket on Outposts
    - object_name: S3 object name (if None, file_path's basename will be used)
    - region: AWS region name
    """
    try:
        # Create S3 client for Outposts
        s3_client = boto3.client("s3", region_name=region)
        # Upload file
        print(f"Starting upload of {file_path} to {bucket_name}")
        s3_client.upload_file(file_path, bucket_name, object_name)
        print(f"Successfully uploaded {file_path} to {bucket_name}/{object_name}")
        return True

    except ClientError as e:
        error_message = f"Error uploading file: {str(e)}"
        logger.error(error_message)
        print(error_message)
        return False
    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        logger.error(error_message)
        print(error_message)
        return False


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() == "pdf"


def convert_pdf_to_json(folder_path):
    converter = PDFToJSON(folder_path, folder_path)
    json_data = converter.convert_pdf_to_json(folder_path)

    if json_data:
        converter.save_json(json_data, folder_path)

    return json_data


@app.route("/")
def index():
    return render_template("knowledgebase.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    print("Starting the upload...")

    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file part"})

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"success": False, "message": "No selected file"})

    if not allowed_file(file.filename):
        return jsonify({"success": False, "message": "Invalid file type"})

    filename = secure_filename(file.filename)

    # Create a temporary file
    import tempfile
    import os

    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, filename)

    try:
        # Save the uploaded file temporarily
        file.save(temp_file_path)

        # Configuration
        config = {
            "file_path": temp_file_path,
            "bucket_name": BUCKET_NAME,
            "object_name": filename,
            "region": REGION_NAME,
        }

        # 1. Upload file
        if SAVEFILETOS3:
            print(f"Saving {filename} file to S3 on Outposts")
            success = upload_to_outposts(**config)

        # 2. Convert PDF to JSON
        print(f"Converting {filename} PDF to JSON")
        json_data = convert_pdf_to_json(temp_file_path)

        # 3. Read and concatenate the text
        full_text = read_and_concatenate_text(json_data)

        # 4. Create chunks of the full_text and store than in the RDS database (pgvector)
        if full_text:
            chunks = create_chunks(full_text, chunk_size=CHUNK_SIZE, overlap=OVERLAP)

            # Print the chunks
            print(f"Text split into {len(chunks)} chunks:")
            print("-" * 50)

            for i, chunk in enumerate(chunks, 1):
                print(f"\nChunk {i}:")
                print("-" * 20)
                print(chunk)
                print(f"Length: {len(chunk)} characters")
                print("-" * 20)
                vec_embeddings = vector_embeddings.get_vector_embeddings(chunk)
                print(vec_embeddings)
                vector_database.insert_text_and_embedding(chunk, vec_embeddings)

        # Clean up - remove temporary file
        print(f"Removing temporary file")
        os.remove(temp_file_path)

        print("Upload completed successfully")
        return jsonify({"success": True, "message": "File uploaded successfully"})

    except Exception as e:
        print(f"Error: {str(e)}")
        # Clean up in case of error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        return jsonify({"success": False, "message": f"An error occurred: {str(e)}"})


if __name__ == "__main__":
    http_server = WSGIServer(("", PORT), app)
    http_server.serve_forever()
