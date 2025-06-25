import os
import shutil
import tempfile
from config import TEMP_DIR

def setup_temp_dir():
    """Create and clean temporary directory"""
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR, exist_ok=True)
    return TEMP_DIR

def create_temp_file(extension=".pdf"):
    """Create a temporary file with given extension"""
    return tempfile.mktemp(suffix=extension, dir=setup_temp_dir())