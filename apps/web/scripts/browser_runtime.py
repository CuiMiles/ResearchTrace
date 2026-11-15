"""Portable browser discovery; never installs or downloads a browser implicitly."""
import os
import shutil
from pathlib import Path


def launch_chromium(playwright):
    explicit = os.environ.get('RT_BROWSER_EXECUTABLE')
    executable = explicit or next((shutil.which(name) for name in
                                  ('chromium', 'chromium-browser', 'google-chrome')
                                  if shutil.which(name)), None)
    if explicit and not Path(explicit).is_file():
        raise RuntimeError('RT_BROWSER_EXECUTABLE does not point to a browser file')
    options = {'headless': True, 'args': ['--disable-gpu', '--disable-dev-shm-usage']}
    if executable:
        options['executable_path'] = executable
    # Otherwise use Playwright's installed browser for the current host.
    return playwright.chromium.launch(**options)
