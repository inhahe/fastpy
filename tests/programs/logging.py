"""Test native logging module."""
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s - %(message)s")

# Root logger convenience functions
logging.debug("this is debug")
logging.info("this is info")
logging.warning("this is a warning")
logging.error("this is an error")
logging.critical("this is critical")

# With format args
logging.info("count = %d", 42)
logging.warning("name is %s", "Alice")

# Named logger
logger = logging.getLogger("myapp")
logger.setLevel(logging.WARNING)
logger.debug("should not appear")
logger.warning("logger warning")
logger.error("logger error")

print("logging tests done")
