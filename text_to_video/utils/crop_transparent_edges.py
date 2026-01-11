#!/usr/bin/env python3
"""Crop transparent edges off PNG images, keeping only pixels that aren't transparent."""
import sys
import os
from pathlib import Path
from PIL import Image

def crop_transparent_edges(image_path):
    """
    Crop transparent edges from an image.
    Returns the cropped image, or None if there's an error.
    """
    try:
        img = Image.open(image_path)
        
        # Convert to RGBA if not already
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Get the bounding box of non-transparent pixels
        bbox = img.getbbox()
        
        if bbox is None:
            print(f"Warning: {image_path} is completely transparent, skipping...")
            return None
        
        # Crop the image to the bounding box
        cropped = img.crop(bbox)
        
        return cropped
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None

def process_file(image_path):
    """Process a single image file."""
    cropped = crop_transparent_edges(image_path)
    if cropped:
        # Save back to the same file
        cropped.save(image_path, 'PNG')
        print(f"Cropped: {image_path} (saved {cropped.size[0]}x{cropped.size[1]})")
        return True
    return False

def process_directory(directory_path):
    """Process all PNG files in a directory recursively."""
    directory = Path(directory_path)
    if not directory.exists():
        print(f"Error: Directory {directory_path} does not exist")
        return
    
    png_files = list(directory.rglob("*.png"))
    if not png_files:
        print(f"No PNG files found in {directory_path}")
        return
    
    print(f"Found {len(png_files)} PNG file(s) to process...")
    processed = 0
    
    for png_file in png_files:
        if process_file(str(png_file)):
            processed += 1
    
    print(f"\nProcessed {processed}/{len(png_files)} file(s)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python crop_transparent_edges.py <image_path>     # Process single file")
        print("  python crop_transparent_edges.py <directory_path> # Process directory recursively")
        sys.exit(1)
    
    path = sys.argv[1]
    
    if os.path.isfile(path):
        if not path.lower().endswith('.png'):
            print("Error: File must be a PNG image")
            sys.exit(1)
        process_file(path)
    elif os.path.isdir(path):
        process_directory(path)
    else:
        print(f"Error: {path} is not a valid file or directory")
        sys.exit(1)

