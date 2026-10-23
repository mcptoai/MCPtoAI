from .cli import main

def _configure_console_encoding():
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


if __name__ == "__main__":
    _configure_console_encoding()
    main()
