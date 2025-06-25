import pdfplumber
import docx
import re
from utils.logger import logger

class FileProcessor:
    @staticmethod
    def extract_text(file_path):
        """
        Extracts and cleans text from a file, supporting both PDF and DOCX formats.
        """
        try:
            if file_path.lower().endswith('.pdf'):
                return PDFProcessor.extract_text(file_path)
            elif file_path.lower().endswith('.docx'):
                return WordProcessor.extract_text(file_path)
            else:
                logger.warning(f"Unsupported file type for: {file_path}")
                return ""
        except Exception as e:
            logger.error(f"Failed to process file {file_path}. Error: {e}", exc_info=True)
            return ""

    @staticmethod
    def clean_text(text):
        """Cleans extracted text by removing non-ASCII characters and excessive whitespace."""
        text = re.sub(r'[^\x00-\x7F]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

class PDFProcessor:
    @staticmethod
    def extract_text(file_path):
        """Extracts text from a PDF file."""
        full_text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)
        return FileProcessor.clean_text("\n".join(full_text))

class WordProcessor:
    @staticmethod
    def extract_text(file_path):
        """Extracts text from a DOCX file."""
        doc = docx.Document(file_path)
        full_text = [para.text for para in doc.paragraphs]
        return FileProcessor.clean_text("\n".join(full_text))