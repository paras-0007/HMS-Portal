import os
import tempfile
import logging

# Configure a basic logger for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_temp_file(original_filename):
    
    try:
        # Extract the suffix (e.g., '.pdf') from the original filename
        _, suffix = os.path.splitext(original_filename)
        
        file_descriptor, path = tempfile.mkstemp(suffix=suffix)
        
        os.close(file_descriptor)
        
        logging.info(f"Created temporary file at: {path}")
        return path
    except Exception as e:
        logging.error(f"Failed to create temporary file for {original_filename}: {e}", exc_info=True)
        return None
