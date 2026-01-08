"""
Installation script for Model Manager extension.
Installs required dependencies on first run.
"""
import importlib.util
import subprocess
import sys


def is_installed(package: str) -> bool:
    """Check if a package is installed."""
    try:
        spec = importlib.util.find_spec(package)
        return spec is not None
    except ModuleNotFoundError:
        return False


def run_pip(*args):
    """Run pip install with given arguments."""
    subprocess.run([sys.executable, "-m", "pip", "install", *args], check=True)


def install():
    """Install required dependencies."""
    deps = [
        ("blake3", "blake3"),  # (pip package name, import name)
        ("aria2", "aria2"),    # Fast parallel downloader
    ]

    pkgs = []
    for pip_name, import_name in deps:
        if not is_installed(import_name):
            pkgs.append(pip_name)

    if pkgs:
        print(f"[ModelManager] Installing dependencies: {', '.join(pkgs)}")
        run_pip(*pkgs)
        print("[ModelManager] Dependencies installed successfully")


try:
    import launch
    skip_install = launch.args.skip_install
except Exception:
    skip_install = False

if not skip_install:
    install()
