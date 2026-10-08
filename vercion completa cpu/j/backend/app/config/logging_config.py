import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("httpx", "urllib3", "PIL", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
