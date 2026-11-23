# Season calendar files

The published fixture lists the file-based leagues are built from. They live in the repo so the
build is reproducible: `ingest/calendars.py` maps a filename fragment to a parser, so **the
filenames matter** — renaming one will either pick the wrong parser or fail outright.

Rebuild wholesale, passing every file:

    python3 ingest/calendars.py calendars/*

Fixture lists are not protected by copyright in the EU (CJEU C-604/10). They are kept here as
source data, not republished as a dataset.

Austria, Switzerland and Denmark are **partial seasons** — those leagues split into championship
and relegation rounds partway through, and the remaining fixtures are not published yet. Replace
those files when they are.
