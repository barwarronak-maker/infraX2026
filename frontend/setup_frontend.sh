#!/bin/bash
# ROADSoS Frontend Setup Script
# Run this from your Desktop: bash setup_frontend.sh

cd ~/Desktop/ROADSoS

# Create folders
mkdir -p frontend/icons
mkdir -p frontend/data

echo "✅ Folders created"

# Generate placeholder icons using Python (no external tools needed)
python3 - <<'PYEOF'
import struct, zlib, base64, os

def make_png(size, bg=(192,57,43), text_char='R'):
    """Generate a simple colored PNG icon"""
    w, h = size, size
    raw = []
    for y in range(h):
        row = [0]  # filter byte
        for x in range(w):
            # Simple circle pattern
            cx, cy = w//2, h//2
            r = w//2 - 4
            if (x-cx)**2 + (y-cy)**2 <= r**2:
                row.extend([bg[0], bg[1], bg[2], 255])
            else:
                row.extend([13, 13, 13, 255])
        raw.append(bytes(row))
    
    def chunk(name, data):
        c = name + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    idat_data = zlib.compress(b''.join(raw))
    
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr)
    png += chunk(b'IDAT', idat_data)
    png += chunk(b'IEND', b'')
    return png

# Create 192x192 icon
with open('frontend/icons/icon-192.png', 'wb') as f:
    f.write(make_png(192))
print("✅ icon-192.png created")

# Create 512x512 icon
with open('frontend/icons/icon-512.png', 'wb') as f:
    f.write(make_png(512))
print("✅ icon-512.png created")
PYEOF

echo ""
echo "✅ Setup complete! Now run:"
echo ""
echo "  cd ~/Desktop/ROADSoS/frontend"
echo "  python3 -m http.server 8080"
echo ""
echo "Then open: http://localhost:8080"
