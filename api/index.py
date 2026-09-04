import sys
import os

# Add parent directory to python path for Vercel Serverless Function
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pk_ogiri import app
