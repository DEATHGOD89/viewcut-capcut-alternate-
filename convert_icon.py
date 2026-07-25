from PySide6.QtGui import QImage
import os

img = QImage(r"C:\Users\Death_God\Downloads\projects\VIDEO EDITOR\src\LOGO.jpg")
if img.isNull():
    print("Failed to load LOGO.jpg")
else:
    # Scale to typical icon sizes and save as ico
    scaled = img.scaled(256, 256)
    success = scaled.save(r"C:\Users\Death_God\Downloads\projects\VIDEO EDITOR\src\LOGO.ico", "ICO")
    print("Saved LOGO.ico:", success)
