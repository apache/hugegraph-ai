#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""
HugeGraph Logger Util
======================

A unified logging module that provides consistent logging functionality across the HugeGraph project.

Key Features:
- Uses "Rich" library for enhanced console output with proper formatting and colors
- Provides both console and file logging capabilities with rotation
- Includes utility functions for controlled logging frequency

Best Practices:
- Other modules should reuse this logger instead of creating new logging configurations
- Use the provided init_logger() function to maintain consistent log formatting
- If additional functionality is needed, extend this module rather than creating new loggers

Example Usage:
    from pyhugegraph.utils.log import init_logger

    # Initialize logger with both console and file output
    log = init_logger(
        log_output="logs/myapp.log",
        log_level=logging.INFO,
        logger_name="myapp"
    )

    # Use the log/logger
    log.info("Application started")
    log.debug("Processing data...")
    log.error("Error occurred: %s", error_msg)
"""

import atexit
import logging
import os
import sys
import time
from collections import Counter
from functools import cache, lru_cache
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler

__all__ = [
    "fetch_log_level",
    "init_logger",
    "log_every_n_secs",
    "log_every_n_times",
    "log_first_n_times",
]

LOG_BUFFER_SIZE_ENV: str = "LOG_BUFFER_SIZE"
DEFAULT_BUFFER_SIZE: int = 1024 * 1024  # 1MB


@lru_cache  # avoid creating multiple handlers when calling init_logger()
def init_logger(
    log_output=None,
    log_level=logging.INFO,
    rank=0,
    *,
    logger_name="client",  # users should set logger name for modules
    propagate_logs: bool = False,
    stdout_logging: bool = True,
    max_log_size=50 * 1024 * 1024,  # 50 MB
    backup_logs=5,
):
    """
    Initialize the logger and set its verbosity level to "DEBUG".

    Args:
        log_output (str): a file name or a directory to save log. If None, will not save a log file.
            If it ends with ".txt" or ".log", assumed to be a file name.
            Otherwise, logs will be saved to `log_output/log.txt`.
        logger_name (str): the root module name of this logger
        propagate_logs (bool): whether to propagate logs to the parent logger.
        stdout_logging (bool): whether to configure logging to stdout.

    Returns:
        logging.Logger: a logger
    """
    log_instance = logging.getLogger(logger_name)
    log_instance.setLevel(log_level)
    log_instance.propagate = propagate_logs

    if log_instance.hasHandlers():
        log_instance.handlers.clear()

    # stdout logging: master only
    if stdout_logging and rank == 0:
        rich_handler = RichHandler(log_level)
        rich_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        log_instance.addHandler(rich_handler)

    # file logging: all workers
    if log_output is not None:
        if log_output.endswith(".txt") or log_output.endswith(".log"):
            log_filename = log_output
        else:
            log_filename = os.path.join(log_output, "log.txt")

        if rank > 0:
            log_filename = f"{log_filename}.rank{rank}"

        try:
            log_directory = os.path.dirname(log_filename)
            if log_directory:
                os.makedirs(log_directory, exist_ok=True)
        except OSError:
            # If we can't create the log directory (e.g., read-only filesystem),
            # fall back to console-only logging
            if stdout_logging:
                # Already have console handler, just skip file logging
                pass
            else:
                # No stdout logging and can't create file - create a null handler
                null_handler = logging.NullHandler()
                log_instance.addHandler(null_handler)
            return log_instance
        file_handler = RotatingFileHandler(
            log_filename,
            maxBytes=max_log_size,
            backupCount=backup_logs,
        )
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s:%(filename)s:%(lineno)d] %(message)s",
            datefmt="%m/%d/%y %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        log_instance.addHandler(file_handler)
    return log_instance


# Cache the opened file object, so that different calls to `initialize_logger`
# with the same file name can safely write to the same file.
@cache
def _cached_log_file(filename):
    """Cache the opened file object"""
    # Use 1K buffer if writing to cloud storage
    with open(filename, "a", buffering=_determine_buffer_size(filename), encoding="utf-8") as file_io:
        atexit.register(file_io.close)
        return file_io


def _determine_buffer_size(filename: str) -> int:
    """Determine the buffer size for the log stream"""
    if "://" not in filename:
        # Local file, no extra caching is necessary
        return -1
    # Remote file requires a larger cache to avoid many smalls writes.
    if LOG_BUFFER_SIZE_ENV in os.environ:
        return int(os.environ[LOG_BUFFER_SIZE_ENV])
    return DEFAULT_BUFFER_SIZE


def _identify_caller():
    """
    Returns:
        str: module name of the caller
        tuple: a hashable key to be used to identify different callers
    """
    frame = sys._getframe(2)  # pylint: disable=protected-access
    while frame:
        code = frame.f_code
        if os.path.join("utils", "logger.") not in code.co_filename:
            module_name = frame.f_globals["__name__"]
            if module_name == "__main__":
                module_name = "core"
            return module_name, (code.co_filename, frame.f_lineno, code.co_name)
        frame = frame.f_back
    return None, None


LOG_COUNTER = Counter()
LOG_TIMERS = {}


def log_first_n_times(level, message, n=1, *, logger_name=None, key="caller"):
    """
    Log only for the first n times.

    Args:
        logger_name (str): name of the logger to use. Will use the caller's module by default.
        key (str or tuple[str]): the string(s) can be one of "callers" or
            "message", which defines how to identify duplicated logs.
            For example, if called with `n=1, key="caller"`, this function
            will only log the first call from the same caller, regardless of
            the message content.
            If called with `n=1, key="message"`, this function will log the
            same content only once, even if they are called from different places.
            If called with `n=1, key=("caller", "message")`, this function
            will not log only if the same caller has logged the same message before.
    """
    if isinstance(key, str):
        key = (key,)
    assert len(key) > 0

    caller_module, caller_key = _identify_caller()
    hash_key = ()
    if "caller" in key:
        hash_key = hash_key + caller_key
    if "message" in key:
        hash_key = (*hash_key, message)

    LOG_COUNTER[hash_key] += 1
    if LOG_COUNTER[hash_key] <= n:
        logging.getLogger(logger_name or caller_module).log(level, message)


def log_every_n_times(level, message, n=1, *, logger_name=None):
    caller_module, key = _identify_caller()
    LOG_COUNTER[key] += 1
    if n == 1 or LOG_COUNTER[key] % n == 1:
        logging.getLogger(logger_name or caller_module).log(level, message)


def log_every_n_secs(level, message, n=1, *, logger_name=None):
    caller_module, key = _identify_caller()
    last_logged = LOG_TIMERS.get(key)
    current_time = time.time()
    if last_logged is None or current_time - last_logged >= n:
        logging.getLogger(logger_name or caller_module).log(level, message)
        LOG_TIMERS[key] = current_time


def fetch_log_level(level_name: str):
    """Fetch the logging level by its name"""
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {level_name}")
    return level


# Importing a library must not replace the host process' logging configuration.
# Applications that want Rich or file handlers can opt in with init_logger().
log = logging.getLogger("client")
