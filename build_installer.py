import os
import PyInstaller.__main__
from pathlib import Path

def build():
    base_dir = Path(__file__).parent.absolute()
    src_dir = base_dir / "src"
    main_script = src_dir / "main.py"
    ffmpeg_dir = base_dir / "ffmpeg"
    
    print(f"Building VideoEditorLite from: {main_script}")
    
    if not ffmpeg_dir.exists():
        print("Warning: 'ffmpeg' folder not found in project root!")
        print("The app will build, but users will need to provide their own ffmpeg.exe")
    
    args = [
        str(main_script),
        '--name=VideoEditorLite',
        '--noconsole',       # Hides the terminal window on Windows
        '--windowed',        # Same as --noconsole
        '--onedir',          # Creates a directory with the .exe (best for large media apps)
        '--clean',
        '--noconfirm',       # Overwrite existing build
        '--icon=' + str(src_dir / 'LOGO.ico'),
        '--paths=' + str(src_dir),
        '--add-data=' + str(src_dir / 'LOGO.ico') + ';.',
    ]
    
    # Add ffmpeg bundle if it exists
    if ffmpeg_dir.exists():
        # In PyInstaller Windows, the separator for add-data is ';'
        args.append(f'--add-data={ffmpeg_dir};ffmpeg')
        
    print(f"Running PyInstaller with args: {args}")
    PyInstaller.__main__.run(args)
    
    print("\n" + "="*50)
    print("Build Complete!")
    print("Your production-ready application is located in the 'dist/VideoEditorLite' folder.")
    print("You can zip that entire folder and distribute it to any Windows PC.")
    print("="*50)

if __name__ == "__main__":
    build()
