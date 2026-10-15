"""Jeff's lead pipeline. Run with the scraper venv python (the dump step needs its supabase client):

    C:\\Users\\Hi\\AcroGrowth\\scraper\\gmaps-scraper\\.venv\\Scripts\\python.exe jeff.py status
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jeffpipe.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
