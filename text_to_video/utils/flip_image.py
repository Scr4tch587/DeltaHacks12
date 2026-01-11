#!/usr/bin/env python3
"""Flip a PNG image horizontally (like turning a page)."""
import sys
from PIL import Image

if len(sys.argv) != 2:
    print("Usage: python flip_image.py <image_path>")
    sys.exit(1)

image_path = sys.argv[1]

try:
    img = Image.open(image_path)
    flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
    
    # Replace original file
    flipped.save(image_path)
    print(f"Flipped image saved to: {image_path}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

