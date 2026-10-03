"""Serve the throwaway TUI sketch: python3 examples/prototypes/serve_tui.py."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).parent))
    server = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    print("TUI prototype: http://127.0.0.1:8765/tui-prototype.html?variant=A", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
