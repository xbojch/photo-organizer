"""Entry point. Implementation lives in the photo_organizer/ package.

Double-click this (rename to run.pyw on Windows for no console window), or
run `python run.py` / `python -m photo_organizer`. This is also what the
build scripts (build_windows.bat, build_unix.sh, Dockerfiles, CI) point
PyInstaller at.
"""
import multiprocessing

from photo_organizer.gui import main

if __name__ == '__main__':
    # Required for the PyInstaller --onefile --windowed build: without it, any
    # multiprocessing worker spawned at runtime (e.g. reverse_geocoder) would
    # re-execute this frozen exe from scratch instead of running as a plain
    # worker, popping open a duplicate GUI window per worker process.
    multiprocessing.freeze_support()
    main()
