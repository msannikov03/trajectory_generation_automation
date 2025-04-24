#!/usr/bin/env python3

import os
import sys
import json
import argparse
import csv
import subprocess
import datetime
import re
import logging

# Add special import handling for IDE warnings
try:
    import pandas as pd
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("Warning: pandas or jinja2 not found. Make sure to run this script in the virtual environment with all dependencies installed.")
    print("Run: pip install pandas jinja2")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Parse command line arguments
parser = argparse.ArgumentParser(description='Build PDF assembly manual')
parser.add_argument('--model', required=True, help='Path to the source 3D model file')
args = parser.parse_args()

# Project paths
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODEL_FILENAME = os.path.basename(args.model)
    MODEL_NAME = os.path.splitext(MODEL_FILENAME)[0]
    MODEL_IMG_DIR = os.path.join(BASE_DIR, 'build', 'img', MODEL_NAME)
    TEX_DIR = os.path.join(BASE_DIR, 'build', 'tex')
    PDF_DIR = os.path.join(BASE_DIR, 'build', 'pdf')
    MANUALS_CSV = os.path.join(BASE_DIR, 'manuals.csv')
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'assets', 'templates') # Ensure this path is correct
    LATEX_TEMPLATE = 'template.tex.j2' # Ensure template exists in TEMPLATE_DIR
except Exception as e:
    logging.error(f"Error setting up project paths: {e}")
    sys.exit(1)

# Ensure output directories exist
os.makedirs(TEX_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)

# Load the metadata
metadata_file = os.path.join(MODEL_IMG_DIR, 'metadata.json')
if not os.path.exists(metadata_file):
    logging.error(f"Metadata file not found: {metadata_file}")
    logging.error("Ensure blender_explode.py ran successfully first.")
    sys.exit(1)

try:
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
except Exception as e:
    logging.error(f"Error loading metadata from {metadata_file}: {e}")
    sys.exit(1)

# --- Optional: Image Post-Processing ---
# If you removed 3D text labels in Blender, this is where you could add them
# using Pillow or another library before generating the LaTeX file.
# Example:
# try:
#     from PIL import Image, ImageDraw, ImageFont
#     parts_diagram_path = os.path.join(MODEL_IMG_DIR, 'parts_diagram.png')
#     if os.path.exists(parts_diagram_path):
#         logging.info("Attempting to add labels to parts_diagram.png...")
#         # Add your Pillow code here to load image, get part coordinates (need to store them), draw text.
#         pass # Replace with actual implementation
# except ImportError:
#     logging.warning("Pillow library not found. Skipping label post-processing. pip install Pillow")
# except Exception as e:
#     logging.error(f"Error during image post-processing: {e}")
# --- End Optional Post-Processing ---


# Load or create manuals CSV
if os.path.exists(MANUALS_CSV):
    try:
        manuals_df = pd.read_csv(MANUALS_CSV)
    except pd.errors.EmptyDataError:
        logging.warning(f"Manuals CSV file is empty: {MANUALS_CSV}")
        manuals_df = pd.DataFrame(columns=['model_id', 'title', 'source_file', 'time_estimate', 'created_date'])
    except Exception as e:
        logging.error(f"Error reading manuals CSV {MANUALS_CSV}: {e}")
        manuals_df = pd.DataFrame(columns=['model_id', 'title', 'source_file', 'time_estimate', 'created_date'])
else:
    logging.info(f"Manuals CSV file not found. Creating new one: {MANUALS_CSV}")
    manuals_df = pd.DataFrame(columns=['model_id', 'title', 'source_file', 'time_estimate', 'created_date'])

# Ensure required columns exist
required_cols = ['model_id', 'title', 'source_file', 'time_estimate', 'created_date']
for col in required_cols:
    if col not in manuals_df.columns:
        manuals_df[col] = None # Add missing columns

# Generate a unique model ID using source filename if not already present
source_filename_key = os.path.basename(args.model) # Use filename as key
existing_entry = manuals_df[manuals_df['source_file'] == source_filename_key]

if existing_entry.empty:
    logging.info(f"No existing entry found for {source_filename_key}. Generating new ID.")
    # Generate A-001, A-002, etc. style ID
    numeric_ids = pd.to_numeric(manuals_df['model_id'].str.extract(r'^[A-Z]-(\d+)$', expand=False), errors='coerce')
    last_id_num = numeric_ids.max()
    next_id_num = int(last_id_num + 1) if pd.notna(last_id_num) else 1
    new_model_id = f"A-{next_id_num:03d}"

    metadata['model_id'] = new_model_id # Update metadata with the generated ID

    # Add new entry to DataFrame
    new_row = pd.DataFrame([{
        'model_id': new_model_id,
        'title': metadata.get('title', MODEL_NAME),
        'source_file': source_filename_key,
        'time_estimate': metadata.get('time_estimate', 'N/A'),
        'created_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }])
    manuals_df = pd.concat([manuals_df, new_row], ignore_index=True)

    # Save updated CSV
    try:
        manuals_df.to_csv(MANUALS_CSV, index=False, quoting=csv.QUOTE_MINIMAL)
        logging.info(f"Added new entry {new_model_id} to {MANUALS_CSV}")
    except Exception as e:
        logging.error(f"Error writing updated manuals CSV {MANUALS_CSV}: {e}")
else:
    # Use existing ID from the first match
    existing_model_id = existing_entry['model_id'].iloc[0]
    logging.info(f"Found existing entry for {source_filename_key} with ID: {existing_model_id}")
    metadata['model_id'] = existing_model_id

# Set up Jinja2 environment
try:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string='\\BLOCK{',
        block_end_string='}',
        variable_start_string='\\VAR{',
        variable_end_string='}',
        comment_start_string='\\#{',
        comment_end_string='}',
        line_statement_prefix='%%',
        line_comment_prefix='%#',
        trim_blocks=True,
        autoescape=False, # Important for LaTeX
        lstrip_blocks=True
    )
    template = env.get_template(LATEX_TEMPLATE)
except Exception as e:
    logging.error(f"Error setting up Jinja2 environment or loading template {LATEX_TEMPLATE} from {TEMPLATE_DIR}: {e}")
    sys.exit(1)

# Prepare data for template, ensuring paths are relative to the TEX_DIR where latex runs
# Or use absolute paths if latex setup handles it. Relative is safer.
img_dir_relative_to_tex = os.path.relpath(MODEL_IMG_DIR, TEX_DIR)

def sanitize_path_for_latex(path):
    # Convert to forward slashes, which LaTeX generally prefers even on Windows
    return path.replace(os.sep, '/')

overview_image_path = sanitize_path_for_latex(os.path.join(img_dir_relative_to_tex, 'overview.png'))
parts_diagram_path = sanitize_path_for_latex(os.path.join(img_dir_relative_to_tex, 'parts_diagram.png'))
has_parts_diagram = os.path.exists(os.path.join(MODEL_IMG_DIR, 'parts_diagram.png')) # Check absolute path

template_data = {
    'title': metadata.get('title', 'Assembly Manual'),
    'model_id': metadata.get('model_id', 'N/A'),
    'time_estimate': metadata.get('time_estimate', 'N/A'),
    'overview_image': overview_image_path,
    'has_parts_diagram': has_parts_diagram,
    'parts_diagram_image': parts_diagram_path if has_parts_diagram else None,
    'steps': [],
    'parts': metadata.get('parts', [])
}

# Add steps with relative image paths
for i, step in enumerate(metadata.get('steps', [])):
    step_image_path = sanitize_path_for_latex(os.path.join(img_dir_relative_to_tex, step.get('image', '')))
    # Basic check if the source image exists
    if not os.path.exists(os.path.join(MODEL_IMG_DIR, step.get('image', ''))):
         logging.warning(f"Image file not found for step {i+1}: {step.get('image', '')}. Skipping image in PDF.")
         step_image_path = None # Don't include non-existent image

    template_data['steps'].append({
        'image': step_image_path,
        'caption': step.get('caption', f'Step {i+1}')
    })


# Generate LaTeX file
tex_filename = f"{metadata['model_id']}.tex"
tex_filepath = os.path.join(TEX_DIR, tex_filename)
try:
    rendered_tex = template.render(template_data)
    with open(tex_filepath, 'w', encoding='utf-8') as f:
        f.write(rendered_tex)
    logging.info(f"LaTeX file generated: {tex_filepath}")
except Exception as e:
    logging.error(f"Error rendering or writing LaTeX file {tex_filepath}: {e}")
    sys.exit(1)

# Compile LaTeX to PDF (requires pdflatex installed and in PATH)
latex_command = 'pdflatex'
# Check if pdflatex exists
try:
    subprocess.run([latex_command, '--version'], check=True, capture_output=True, text=True)
except (subprocess.CalledProcessError, FileNotFoundError):
    logging.warning(f"'{latex_command}' command not found or failed.")
    logging.warning("PDF generation skipped. Please install a LaTeX distribution (like TeX Live or MiKTeX) and ensure pdflatex is in your system's PATH.")
    logging.warning(f"LaTeX source saved to: {tex_filepath}")
    sys.exit(0) # Exit gracefully, as PDF generation is optional

try:
    logging.info(f"Compiling {tex_filename} to PDF...")
    # Run twice for references (like table of contents, page numbers)
    cmd_args = [latex_command, '-interaction=nonstopmode', '-output-directory=' + TEX_DIR, tex_filename]

    process1 = subprocess.run(cmd_args, capture_output=True, text=True, cwd=TEX_DIR, timeout=120) # 2 min timeout
    if process1.returncode != 0:
        logging.error(f"First LaTeX compilation failed. Return code: {process1.returncode}")
        logging.error("LaTeX Output:\n" + process1.stdout[-1000:]) # Show last bit of log
        logging.error("LaTeX Error:\n" + process1.stderr)
        # Optional: copy .log file for detailed debugging
        # log_file = os.path.join(TEX_DIR, tex_filename.replace('.tex', '.log'))
        # if os.path.exists(log_file): shutil.copy(log_file, log_file + ".err")
        sys.exit(1)

    process2 = subprocess.run(cmd_args, capture_output=True, text=True, cwd=TEX_DIR, timeout=120)
    if process2.returncode != 0:
        logging.error(f"Second LaTeX compilation failed. Return code: {process2.returncode}")
        logging.error("LaTeX Output:\n" + process2.stdout[-1000:])
        logging.error("LaTeX Error:\n" + process2.stderr)
        sys.exit(1)

    # Move the generated PDF to the PDF directory
    generated_pdf_path = os.path.join(TEX_DIR, f"{metadata['model_id']}.pdf")
    final_pdf_path = os.path.join(PDF_DIR, f"{metadata['model_id']}.pdf")

    if os.path.exists(generated_pdf_path):
        os.rename(generated_pdf_path, final_pdf_path)
        logging.info(f"PDF manual successfully created: {final_pdf_path}")
        # Clean up auxiliary files
        aux_extensions = ['.aux', '.log', '.out', '.toc']
        for ext in aux_extensions:
            aux_file = os.path.join(TEX_DIR, f"{metadata['model_id']}{ext}")
            if os.path.exists(aux_file):
                os.remove(aux_file)
    else:
        logging.error(f"PDF file was not generated at {generated_pdf_path}")
        sys.exit(1)

except subprocess.TimeoutExpired:
    logging.error("LaTeX compilation timed out.")
    sys.exit(1)
except Exception as e:
    logging.error(f"Error during PDF compilation or cleanup: {e}")
    sys.exit(1)