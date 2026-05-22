import os
import urllib.request
import zipfile
import sys

def download_godot():
    version = "4.3"
    url = f"https://github.com/godotengine/godot/releases/download/{version}-stable/Godot_v{version}-stable_win64.exe.zip"
    
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    godot_dir = os.path.join(tools_dir, "godot")
    zip_path = os.path.join(tools_dir, "godot.zip")
    
    os.makedirs(godot_dir, exist_ok=True)
    
    expected_exe = os.path.join(godot_dir, f"Godot_v{version}-stable_win64.exe")
    
    if os.path.exists(expected_exe):
        print(f"Godot {version} is already installed at {expected_exe}")
        return
        
    print(f"Downloading Godot {version} from {url}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
        print("Download complete. Extracting...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(godot_dir)
            
        print("Extraction complete.")
    except Exception as e:
        print(f"Failed to download/extract: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
    print(f"Godot successfully installed to {godot_dir}")

if __name__ == "__main__":
    download_godot()
