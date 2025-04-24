#!/usr/bin/env python3

import os
import sys
import argparse
import random
import shutil
import subprocess
import time

# Parse command line arguments
parser = argparse.ArgumentParser(description='Generate variants of a furniture model')
parser.add_argument('--base-model', required=True, help='Path to the base model file')
parser.add_argument('--count', type=int, default=10, help='Number of variants to generate')
parser.add_argument('--prefix', default='variant', help='Prefix for variant names')
args = parser.parse_args()

# Project paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, 'models_raw')

def generate_variant(base_model, variant_num):
    """Generate a variant of the base model."""
    base_name = os.path.splitext(os.path.basename(base_model))[0]
    base_ext = os.path.splitext(base_model)[1]
    
    # Create variant name
    variant_name = f"{args.prefix}_{base_name}_{variant_num:03d}{base_ext}"
    variant_path = os.path.join(MODELS_DIR, variant_name)
    
    # For demonstration, we'll just copy the base model
    # In a real implementation, you would modify the 3D model parameters
    shutil.copy2(base_model, variant_path)
    
    print(f"Generated variant: {variant_path}")
    return variant_path

def main():
    # Make sure the base model exists
    if not os.path.exists(args.base_model):
        print(f"Error: Base model file not found: {args.base_model}")
        sys.exit(1)
    
    # Generate variants
    for i in range(args.count):
        variant_path = generate_variant(args.base_model, i+1)
        
        # Wait briefly to ensure file watcher processes each file
        time.sleep(1)

if __name__ == "__main__":
    main()
