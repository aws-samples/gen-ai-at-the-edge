# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
import json
from pypdf import PdfReader
from typing import Dict, List, Any
import logging
from datetime import datetime
import re
from pathlib import Path


class PDFToJSON:
    """A class to handle reading PDF files and converting content to JSON format."""

    def __init__(self, folder_path: str, output_folder: str = None):
        """
        Initialize the PDFToJSON converter.

        Args:
            folder_path (str): Path to the folder containing PDF files
            output_folder (str): Path to save JSON files (defaults to 'pdf_json' in folder_path)
        """
        self.logger = logging.getLogger(__name__)
        self.folder_path = Path(folder_path)
        self.output_folder = (
            Path(output_folder) if output_folder else self.folder_path / "pdf_json"
        )

    def get_pdf_files(self) -> List[Path]:
        """
        Get all PDF files from the specified folder.

        Returns:
            List[Path]: List of PDF file paths
        """
        try:
            return list(self.folder_path.glob("*.pdf"))
        except Exception as e:
            self.logger.error(f"Error accessing folder: {str(e)}")
            return []

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean and normalize text content.

        Args:
            text (str): Raw text content

        Returns:
            str: Cleaned text content
        """
        if not text:
            return ""

        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text.strip())
        # Remove special characters but keep basic punctuation
        text = re.sub(r"[^\w\s.,!?-]", "", text)
        return text

    def extract_metadata(self, pdf_reader: PdfReader) -> Dict[str, Any]:
        """
        Extract PDF metadata.

        Args:
            pdf_reader (PdfReader): pypdf reader object

        Returns:
            Dict[str, Any]: Dictionary containing metadata
        """
        metadata = {}
        try:
            if pdf_reader.metadata:
                for key, value in pdf_reader.metadata.items():
                    # Remove the leading '/' from keys and convert to lowercase
                    clean_key = key[1:].lower() if key.startswith("/") else key.lower()
                    metadata[clean_key] = str(value)
        except Exception as e:
            self.logger.warning(f"Error extracting metadata: {str(e)}")

        return metadata

    def process_page_content(self, page_content: str) -> Dict[str, Any]:
        """
        Process and structure page content.

        Args:
            page_content (str): Raw page content

        Returns:
            Dict[str, Any]: Structured page content
        """
        cleaned_text = self.clean_text(page_content)

        # Split content into paragraphs (simple approach)
        paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]

        # Basic content analysis
        word_count = len(cleaned_text.split())
        char_count = len(cleaned_text)

        return {
            "full_text": cleaned_text,
            "paragraphs": paragraphs,
            "statistics": {"word_count": word_count, "character_count": char_count},
        }

    def convert_pdf_to_json(self, pdf_path: Path) -> Dict[str, Any]:
        """
        Convert a single PDF file to JSON format.

        Args:
            pdf_path (Path): Path to the PDF file

        Returns:
            Dict[str, Any]: JSON-compatible dictionary with PDF content
        """
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PdfReader(file)

                # Initialize the JSON structure
                pdf_data = {
                    "filename": pdf_path,
                    "conversion_timestamp": datetime.now().isoformat(),
                    "total_pages": len(pdf_reader.pages),
                    "metadata": self.extract_metadata(pdf_reader),
                    "pages": {},
                }

                # Process each page
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    content = page.extract_text()

                    pdf_data["pages"][str(page_num + 1)] = self.process_page_content(
                        content
                    )

                return pdf_data

        except Exception as e:
            self.logger.error(f"Error processing PDF {pdf_path}: {str(e)}")
            return {}

    def save_json(self, data: Dict[str, Any], original_filename: str) -> None:
        """
        Save JSON data to file.

        Args:
            data (Dict[str, Any]): JSON data to save
            original_filename (str): Original PDF filename
        """
        json_filename = self.output_folder / f"{original_filename[:-4]}.json"
        try:
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Successfully saved JSON: {json_filename}")
        except Exception as e:
            self.logger.error(f"Error saving JSON file {json_filename}: {str(e)}")

    def convert_all_pdfs(self) -> None:
        """Convert all PDF files in the specified folder to JSON."""
        pdf_files = self.get_pdf_files()

        if not pdf_files:
            self.logger.warning(f"No PDF files found in {self.folder_path}")
            return

        for pdf_file in pdf_files:
            self.logger.info(f"Processing {pdf_file.name}")
            json_data = self.convert_pdf_to_json(pdf_file)
            if json_data:
                self.save_json(json_data, pdf_file.name)
