"""LumaTRX's automated tests. Run from the project folder:  .venv\\Scripts\\python -m unittest discover tests
They never touch your own looks or settings: LumaTRX runs on a throwaway data folder (--selftest) while they run."""
import sys

if "--selftest" not in sys.argv:
    sys.argv.append("--selftest")
