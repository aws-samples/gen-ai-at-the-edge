# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
import psycopg2
from psycopg2.extensions import register_adapter, AsIs
import numpy as np
import boto3
import json
import configparser
import logging


class VectorDatabase:
    def __init__(self, configfile_name):
        self.logger = logging.getLogger(__name__)
        # ----------------------------------------------------------------------------------------------------------------------
        # Load the configuration file
        #
        config = configparser.ConfigParser()
        config.read(configfile_name)

        self.SECRET_NAME = config.get("RDS_Connection", "secret_name")
        self.REGION_NAME = config.get("RDS_Connection", "region_name")
        self.DBNAME = config.get("RDS_Connection", "db_name")
        self.HOST = config.get("RDS_Connection", "host")
        self.PORT = config.getint("RDS_Connection", "port")

        register_adapter(np.ndarray, self.adapt_numpy_array)

    def get_secret(self):
        """
        Get secret information from AWS Secrets Manager
        """
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name="secretsmanager", region_name=self.REGION_NAME
            )

            get_secret_value_response = client.get_secret_value(
                SecretId=self.SECRET_NAME
            )
        except Exception as e:
            error_message = f"An error occurred: {e}"
            print(error_message)
            self.logger.error(error_message)
            raise e
        else:
            if "SecretString" in get_secret_value_response:
                secret = json.loads(get_secret_value_response["SecretString"])
                return {
                    "dbname": self.DBNAME,
                    "user": secret.get("username"),
                    "password": secret.get("password"),
                    "host": self.HOST,
                    "port": self.PORT,
                }

        return {
            "dbname": None,
            "user": None,
            "password": None,
            "host": None,
            "port": None,
        }

    def get_db_connection(self):
        """
        Creates a database connection using credentials from Secrets Manager
        """
        db_credentials = self.get_secret()
        return psycopg2.connect(**db_credentials)

    @staticmethod
    def adapt_numpy_array(numpy_array):
        """
        Converts numpy array to a format suitable for PostgreSQL vector type
        """
        return AsIs(f"'[{','.join(map(str, numpy_array))}]'")

    def create_vector_table(self):
        """
        Creates a table with vector support in PostgreSQL
        """

        try:
            conn = self.get_db_connection()
            cur = conn.cursor()

            # Create the vector extension if it doesn't exist
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Create the table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS text_embeddings (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding vector(384),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """
            )

            # Create an index for better vector similarity search performance
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS text_embeddings_embedding_idx
                ON text_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """
            )

            conn.commit()
            print("Table and index created successfully!")

        except Exception as e:
            error_message = f"An error occurred: {e}"
            print(error_message)
            self.logger.error(error_message)
            if conn:
                conn.rollback()
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def insert_text_and_embedding(self, text, vector_embeddings):
        """
        Inserts a text and its embedding into the database
        """
        try:
            embedding = np.array(vector_embeddings)

            conn = self.get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO text_embeddings (text, embedding)
                VALUES (%s, %s)
                RETURNING id;
            """,
                (text, embedding),
            )

            inserted_id = cur.fetchone()[0]
            conn.commit()
            print(f"Successfully inserted with ID: {inserted_id}")
            return inserted_id

        except Exception as e:
            error_message = f"An error occurred: {e}"
            print(error_message)
            self.logger.error(error_message)

            if conn:
                conn.rollback()
            return None
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def search_similar_texts(self, query_embedding, limit=5, similarity_threshold=0.8):
        """
        Searches for similar texts using vector similarity
        """
        try:
            conn = self.get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """
                SELECT text, 1 - (embedding <=> %s) as similarity
                FROM text_embeddings
                WHERE 1 - (embedding <=> %s) > %s
                ORDER BY similarity DESC
                LIMIT %s;
            """,
                (query_embedding, query_embedding, similarity_threshold, limit),
            )

            results = cur.fetchall()
            return results

        except Exception as e:
            error_message = f"An error occurred: {e}"
            print(error_message)
            self.logger.error(error_message)

            return []
        finally:
            if conn:
                conn.close()
