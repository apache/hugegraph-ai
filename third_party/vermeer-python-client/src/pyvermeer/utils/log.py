# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import sys


class VermeerLogger:
    """vermeer API log"""

    _instance = None

    def __new__(cls, name: str = "VermeerClient"):
        """new api logger"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(name)
        return cls._instance

    def _initialize(self, name: str):
        """Initialize log configuration"""
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)  # Default level

        if not self.logger.handlers:
            # Console output format
            console_format = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )

            # Console handler
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)  # Console default level
            console_handler.setFormatter(console_format)

            # file_handler = logging.FileHandler('api_client.log')
            # file_handler.setLevel(logging.DEBUG)
            # file_handler.setFormatter(
            #     logging.Formatter(
            #         '[%(asctime)s] [%(levelname)s] [%(threadName)s] %(name)s - %(message)s'
            #     )
            # )

            self.logger.addHandler(console_handler)
            # self.logger.addHandler(file_handler)

            self.logger.propagate = False

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """Get configured logger"""
        return cls().logger


# Global log instance
log = VermeerLogger.get_logger()
