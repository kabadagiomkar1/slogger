"""Private isolated reference worker; never reexecutes a consumer's main module."""

import os
import pickle
import sys
from multiprocessing.connection import Connection

from .filters import _filter_worker


def main() -> None:
    connection = Connection(os.dup(sys.stdout.fileno()), readable=False, writable=True)
    try:
        arguments = pickle.load(sys.stdin.buffer)
        _filter_worker(connection, *arguments)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
