"""Public PWA assets, served with explicit types and update-friendly headers."""
from pathlib import Path
from django.http import FileResponse
from django.views.decorators.http import require_GET

ROOT = Path(__file__).resolve().parent / 'static' / 'bills' / 'pwa'

@require_GET
def asset(request, filename, content_type):
    # Filenames come exclusively from fixed URL patterns, never user input.
    response = FileResponse((ROOT / filename).open('rb'), content_type=content_type)
    response['Cache-Control'] = 'no-cache'
    return response
