# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
import requests
import configparser


class VectorEmbeddings:
    def __init__(self, configfile_name):
        # ----------------------------------------------------------------------------------------------------------------------
        # Load the configuration file
        #
        config = configparser.ConfigParser()
        config.read(configfile_name)
        self.VECTOR_EMBEDDINGS_URL = config.get(
            "VectorEmbeddings", "VectorEmbeddingsURL"
        )
        self.TIMEOUT = config.getint("VectorEmbeddings", "Timeout")

    def get_vector_embeddings(self, text_data):
        response = requests.post(
            self.VECTOR_EMBEDDINGS_URL, json={"text": text_data}, timeout=self.TIMEOUT
        )

        # Check for HTTP errors
        response.raise_for_status()

        # Parse the JSON response
        result = response.json()

        if "success" in result:
            print("Embeddings:", result["embeddings"])
        else:
            print("Error:", result.get("error"))
            return result.get("error")

        return result["embeddings"]
