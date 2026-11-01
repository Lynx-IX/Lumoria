"""Build Lumoria for Windows: dist/Lumoria/Lumoria.exe (PyInstaller), then installer/Lumoria-Setup-<version>.exe
(Inno Setup, if it's installed). Run from this folder:  .venv\\Scripts\\python build.py
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "shared.py"), encoding="utf8") as _fh:   # the version lives in shared.py
    VERSION = re.search(r'^VERSION = "([^"]+)"', _fh.read(), re.M).group(1)
ISCC = [os.path.join(os.environ.get(v, ""), r"Inno Setup 6\ISCC.exe")
        for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")] + \
       [os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Inno Setup 6\ISCC.exe")]


def pyinstaller():
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
            "--name", "Lumoria", "--icon", os.path.join(HERE, "assets", "lumoria.ico"),
            "--distpath", "dist", "--workpath", "build", "--specpath", "build",
            "--add-data", f"{HERE}/assets;assets", "--add-data", f"{HERE}/models;models",
            "--add-data", f"{HERE}/samples;samples"]
    # packages with DLLs or data files PyInstaller can't see by reading the code
    for pkg in ("imgui_bundle", "onnxruntime", "glfw", "cv2_enumerate_cameras", "sounddevice",
                "mss", "windows_capture", "av"):
        args += ["--collect-all", pkg]
    subprocess.run(args + ["app.py"], cwd=HERE, check=True)


def installer():
    iscc = next((p for p in ISCC if os.path.exists(p)), None)
    if not iscc:
        print("Inno Setup not found: skipping the installer (dist\\Lumoria is ready to zip).")
        return
    subprocess.run([iscc, f"/DMyVersion={VERSION}", "lumoria.iss"], cwd=HERE, check=True)


if __name__ == "__main__":
    shutil.rmtree(os.path.join(HERE, "dist", "Lumoria"), ignore_errors=True)
    pyinstaller()
    installer()
