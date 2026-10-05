"""
Which install of the extension this is: one per WebUI.

Two WebUIs can share one database (Settings -> Model Manager -> database
path), each with its own copy of the extension. What only one of them can
act on is kept under its copy's key - a download it was making (its models
folders differ), a task it queued (its extensions differ) - so the other
never takes it up. The key is the copy's folder, hashed.
"""
import hashlib
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_KEY = hashlib.sha1(os.path.normcase(_ROOT).encode("utf-8")).hexdigest()[:12]
