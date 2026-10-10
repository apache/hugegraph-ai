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

"""Document module providing Document and Metadata classes for document handling.

This module implements classes for representing documents and their associated metadata
in the HugeGraph LLM system.
"""

from typing import Any, Dict, Optional, Union


class Metadata:
    """A class representing metadata for a document.

    This class stores metadata information like source, author, page, etc.
    """

    def __init__(self, **kwargs):
        """Initialize metadata with arbitrary key-value pairs.

        Args:
            **kwargs: Arbitrary keyword arguments to be stored as metadata.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)

    def as_dict(self) -> Dict[str, Any]:
        """Convert metadata to a dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of metadata.
        """
        return dict(self.__dict__)


class Document:
    """A class representing a document with content and metadata.

    This class stores document content along with its associated metadata.
    """

    def __init__(self, content: str, metadata: Optional[Union[Dict[str, Any], Metadata]] = None):
        """Initialize a document with content and metadata.
        Args:
            content: The text content of the document.
            metadata: Metadata associated with the document. Can be a dictionary or Metadata object.

        Raises:
            ValueError: If content is None or empty string.
        """
        if not content:
            raise ValueError("Document content cannot be None or empty")
        self.content = content
        if metadata is None:
            self.metadata = {}
        elif isinstance(metadata, Metadata):
            self.metadata = metadata.as_dict()
        else:
            self.metadata = metadata
