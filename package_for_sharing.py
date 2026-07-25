import shutil
import os
from pathlib import Path

def package():
    base_dir = Path(__file__).parent.absolute()
    dist_dir = base_dir / "dist" / "VideoEditorLite"
    output_zip = base_dir / "dist" / "VideoEditorLite_Portable_Setup"
    
    if not dist_dir.exists():
        print("Error: The build folder does not exist.")
        return
        
    print(f"Creating portable zip setup at {output_zip}.zip...")
    
    # Create a zip file containing the entire application folder
    shutil.make_archive(
        str(output_zip),
        'zip',
        root_dir=str(dist_dir.parent),
        base_dir="VideoEditorLite"
    )
    
    print("Successfully created!")
    print(f"You can send '{output_zip.name}.zip' to your friends!")

if __name__ == "__main__":
    package()
