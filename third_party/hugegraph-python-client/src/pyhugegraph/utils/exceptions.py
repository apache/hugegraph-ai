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


class NotAuthorizedError(Exception):
    """
    Not Authorized
    """


class InvalidParameterError(Exception):
    """
    Parameter setting error
    """


class NotFoundError(Exception):
    """
    no content found
    """


class CreateError(Exception):
    """
    Failed to create vertex or edge
    """


class RemoveError(Exception):
    """
    Failed to delete vertex or edge
    """


class UpdateError(Exception):
    """
    Failed to modify node
    """


class DataFormatError(Exception):
    """
    Input data format error
    """


class ServiceUnavailableError(Exception):
    """
    The server is too busy to be available
    """


class ResponseParseError(Exception):
    """
    Failed to parse a successful server response
    """


class ServerError(Exception):
    """
    Server returned an error response
    """
