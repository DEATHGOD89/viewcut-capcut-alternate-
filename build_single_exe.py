import PyInstaller.__main__
from pathlib import Path

def build_single():
    base_dir = Path(__file__).parent.absolute()
    src_dir = base_dir / "src"
    main_script = src_dir / "main.py"
    ffmpeg_dir = base_dir / "ffmpeg"
    
    print("Building single standalone VideoEditorLite_Standalone.exe...")
    args = [
        str(main_script),
        '--name=VideoEditorLite_Standalone',
        '--noconsole',
        '--windowed',
        '--onefile',
        '--clean',
        '--noconfirm',
        '--icon=' + str(src_dir / 'LOGO.ico'),
        '--paths=' + str(src_dir),
        '--add-data=' + str(src_dir / 'LOGO.ico') + ';.',
    ]
    if ffmpeg_dir.exists():
        args.append(f'--add-data={ffmpeg_dir};ffmpeg')
        
    PyInstaller.__main__.run(args)
    print("Single Standalone EXE Build Complete!")

if __name__ == "__main__":
    build_single()
