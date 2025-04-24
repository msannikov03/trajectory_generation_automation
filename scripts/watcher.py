#!/usr/bin/env python3

import os
import sys
import time
import json
import hashlib
import subprocess
import logging
import platform

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, LoggingEventHandler
except ImportError:
    print("Error: watchdog module not found. Please install it with:")
    print("pip install watchdog")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


DEFAULT_BLENDER_PATHS = {
    "Darwin": "/Applications/Blender.app/Contents/MacOS/Blender", 
    "Windows": "C:/Program Files/Blender Foundation/Blender/blender.exe",
    "Linux": "/usr/bin/blender"
}
BLENDER_PATH = os.environ.get("BLENDER_EXECUTABLE_PATH", DEFAULT_BLENDER_PATHS.get(platform.system()))


try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
    MODELS_DIR = os.path.join(BASE_DIR, 'models_raw')
    BUILD_DIR = os.path.join(BASE_DIR, 'build')
    CACHE_FILE = os.path.join(BUILD_DIR, 'cache.json')
    SCRIPTS_DIR = os.path.join(BASE_DIR, 'scripts') 
    VENV_DIR = os.path.join(BASE_DIR, '.venv') 
except Exception as e:
    logging.error(f"Critical error setting up base directories: {e}")
    sys.exit(1)


SUPPORTED_EXTENSIONS = ['.fbx', '.glb', '.gltf', '.step', '.stp', '.stl', '.obj']



def check_blender_path():
    """Checks if the configured Blender path is valid."""
    if not BLENDER_PATH:
        logging.error("BLENDER_PATH is not set for this operating system.")
        logging.error("Please set the BLENDER_EXECUTABLE_PATH environment variable or update DEFAULT_BLENDER_PATHS in watcher.py")
        return False
    if not os.path.exists(BLENDER_PATH):
        logging.error(f"Blender executable not found at configured path: {BLENDER_PATH}")
        logging.error("Please ensure Blender is installed and the path in watcher.py is correct.")
        return False
    logging.info(f"Using Blender executable found at: {BLENDER_PATH}")
    return True

def get_file_hash(file_path):
    """Generate SHA-256 hash for a file."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192): 
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as e:
        logging.error(f"Error reading file for hashing {file_path}: {e}")
        return None

def load_cache():
    """Load the cache of processed files."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                content = f.read()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            logging.warning(f"Cache file {CACHE_FILE} is invalid JSON. Starting with an empty cache.")
            
            return {}
        except OSError as e:
             logging.error(f"Error reading cache file {CACHE_FILE}: {e}")
             return {} 
    return {}

def save_cache(cache):
    """Save the cache of processed files."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True) 
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        logging.error(f"Error writing cache file {CACHE_FILE}: {e}")
    except TypeError as e:
        logging.error(f"Error serializing cache data to JSON: {e}")


def get_venv_python():
    """Finds the python executable in the virtual environment."""
    
    python_exe = 'python.exe' if platform.system() == "Windows" else 'python'
    scripts_dir = 'Scripts' if platform.system() == "Windows" else 'bin'
    venv_python_path = os.path.join(VENV_DIR, scripts_dir, python_exe)

    if not os.path.exists(venv_python_path):
        logging.warning(f"Virtual environment Python not found at expected path: {venv_python_path}")
    
        return python_exe 
    return venv_python_path


def run_subprocess(command_list, script_name, env=None, timeout=300):
    """Runs a subprocess, logs output, checks for errors."""
    logging.info(f"Running {script_name}: {' '.join(command_list)}")
    try:
        process = subprocess.run(
            command_list,
            check=False, 
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout
        )
        if process.stdout:
            logging.info(f"{script_name} STDOUT:\n{process.stdout[-1000:]}") 
        if process.stderr:
            logging.warning(f"{script_name} STDERR:\n{process.stderr[-1000:]}")
        if process.returncode != 0:
            logging.error(f"{script_name} failed with return code {process.returncode}")
            return False
        logging.info(f"{script_name} completed successfully.")
        return True
    except subprocess.TimeoutExpired:
         logging.error(f"{script_name} timed out after {timeout} seconds.")
         return False
    except FileNotFoundError:
        logging.error(f"Command not found: {command_list[0]}. Ensure it's installed and in PATH.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error running {script_name}: {e}\n{traceback.format_exc()}")
        return False


def process_model(file_path):
    """Process a new model file: run Blender script and PDF build script."""
    logging.info(f"--- Starting processing for: {file_path} ---")
    file_hash = get_file_hash(file_path)
    if file_hash is None:
        logging.error(f"Could not generate hash for {file_path}. Skipping.")
        return

    cache = load_cache()

    if file_hash in cache:
        logging.info(f"File hash {file_hash[:8]}... already processed ({cache[file_hash]['file']}). Skipping.")
        return

    blender_script = os.path.join(SCRIPTS_DIR, 'blender_explode.py')
    pdf_script = os.path.join(SCRIPTS_DIR, 'build_pdf.py')

    if not os.path.exists(blender_script):
        logging.error(f"Blender script not found: {blender_script}")
        return
    if not os.path.exists(pdf_script):
        logging.error(f"PDF build script not found: {pdf_script}")
        return

    blender_command = [
        BLENDER_PATH,
        '--background', 
        '--python', blender_script,
        '--', 
        file_path
    ]
    if not run_subprocess(blender_command, "blender_explode.py", timeout=600): # Longer timeout for Blender
        logging.error(f"Blender processing failed for {file_path}.")
        return 
    venv_python = get_venv_python()
    pdf_command = [
        venv_python,
        pdf_script,
        '--model', file_path
    ]
    
    if not run_subprocess(pdf_command, "build_pdf.py"):
        logging.error(f"PDF generation failed for {file_path}.")
    

   
    cache[file_hash] = {
        'file': os.path.basename(file_path),
        'processed_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    save_cache(cache)

    logging.info(f"--- Finished processing: {file_path} ---")


class ModelFileHandler(FileSystemEventHandler):
    """Handles file system events in the models_raw directory."""

    def __init__(self, processed_cache):
        super().__init__()
        
        self.cache = processed_cache
        self.recently_processed = set() 

    def process(self, event):
        """Common processing logic for detected file events."""
        if event.is_directory:
            return

        file_path = event.src_path
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()

        
        if file_name.startswith('.') or file_ext not in SUPPORTED_EXTENSIONS:
            return

        
        if file_path in self.recently_processed:
             
             return

        logging.info(f"{event.event_type.capitalize()} detected: {file_name}")

        
        time.sleep(2)

        
        current_hash = get_file_hash(file_path)
        if current_hash and current_hash in self.cache:
             logging.info(f"File {file_name} hash matches processed cache. Skipping.")
             
             self.recently_processed.add(file_path)
             
             return

        if current_hash:
             process_model(file_path)
             
             self.cache[current_hash] = { 'file': file_name, 'processed_at': time.strftime('%Y-%m-%d %H:%M:%S')}
             
             self.recently_processed.add(file_path)


    def on_created(self, event):
        self.process(event)

    def on_modified(self, event): 
        logging.info(f"File modified: {event.src_path}. Re-checking for processing.")
        self.process(event)


def initial_scan(directory, cache):
    """Processes any existing unprocessed files in the directory on startup."""
    logging.info(f"Performing initial scan of directory: {directory}")
    processed_count = 0
    skipped_count = 0
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        file_ext = os.path.splitext(filename)[1].lower()

        if os.path.isfile(file_path) and not filename.startswith('.') and file_ext in SUPPORTED_EXTENSIONS:
            file_hash = get_file_hash(file_path)
            if file_hash and file_hash not in cache:
                logging.info(f"Found unprocessed file during initial scan: {filename}")
                process_model(file_path)
                processed_count += 1

                cache[file_hash] = { 'file': filename, 'processed_at': time.strftime('%Y-%m-%d %H:%M:%S')}
            elif file_hash:
                 skipped_count +=1
            else:
                 logging.warning(f"Could not hash file during initial scan: {filename}")


    logging.info(f"Initial scan complete. Processed: {processed_count}, Skipped (already cached): {skipped_count}")


def main():
    """Main function to set up directories and start the file watcher."""
    logging.info("--- Starting Furniture Manual Watcher ---")

    if not check_blender_path():
        sys.exit(1)

    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(os.path.join(BUILD_DIR, 'img'), exist_ok=True)
    os.makedirs(os.path.join(BUILD_DIR, 'tex'), exist_ok=True)
    os.makedirs(os.path.join(BUILD_DIR, 'pdf'), exist_ok=True)
    logging.info(f"Monitoring directory: {MODELS_DIR}")

    cache = load_cache()
    initial_scan(MODELS_DIR, cache)

    event_handler = ModelFileHandler(cache)
    observer = Observer()
    observer.schedule(event_handler, MODELS_DIR, recursive=False) 

    observer.start()
    logging.info("Watcher started. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(60)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Stopping watcher...")
        observer.stop()
    except Exception as e:
        logging.error(f"An unexpected error occurred in the main loop: {e}")
        observer.stop()

    observer.join()
    logging.info("--- Watcher stopped ---")

if __name__ == "__main__":
    if sys.prefix == sys.base_prefix:
         logging.warning("It seems you are not running inside a Python virtual environment.")
         logging.warning("It's recommended to use a virtual environment (e.g., .venv) to manage dependencies.")

    main()