import sys
from pathlib import Path

# Make the shared test doubles importable as `fakes`.
sys.path.insert(0, str(Path(__file__).parent))
