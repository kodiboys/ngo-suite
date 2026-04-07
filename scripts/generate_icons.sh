# FILE: scripts/generate_icons.sh
# MODULE: Icon Generation Script
# Konvertiert SVG zu PNG (benötigt ImageMagick oder Inkscape)

#!/bin/bash

# Verzeichnis
ICON_DIR="public/icons"
mkdir -p $ICON_DIR

# SVG zu PNG konvertieren (mit Inkscape)
if command -v inkscape &> /dev/null; then
    echo "Converting SVGs to PNGs using Inkscape..."
    for size in 72 96 128 144 152 192 384 512; do
        inkscape --export-filename="$ICON_DIR/icon-$size.png" \
                 --export-width=$size \
                 --export-height=$size \
                 "$ICON_DIR/icon-$size.svg"
    done
    echo "PNG icons generated!"
elif command -v convert &> /dev/null; then
    echo "Converting SVGs to PNGs using ImageMagick..."
    for size in 72 96 128 144 152 192 384 512; do
        convert -background none -resize ${size}x${size} \
                "$ICON_DIR/icon-$size.svg" \
                "$ICON_DIR/icon-$size.png"
    done
    echo "PNG icons generated!"
else
    echo "Warning: Neither Inkscape nor ImageMagick found. Install one to generate PNG icons."
    echo "Ubuntu/Debian: sudo apt-get install inkscape"
    echo "Ubuntu/Debian: sudo apt-get install imagemagick"
fi

echo "Icon generation complete!"