# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Public errors shared by the SDK and optional model adapters."""

from typing import Literal


class LLMOutputTruncatedError(RuntimeError):
    """A provider stopped generation before completing its output."""

    def __init__(self, reason: Literal["finish_reason=length", "done_reason=length"] = "finish_reason=length") -> None:
        self.reason = reason
        super().__init__(f"LLM output was truncated ({reason}).")

    def __reduce__(self):
        return type(self), (self.reason,), self.__dict__


class ModelOutputError(ValueError):
    """The model did not return the requested structured output."""


class SchemaValidationError(ValueError):
    """An extraction schema is invalid; no model calls have been made."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        super().__init__(f"Invalid graph schema: {message}")

    def __reduce__(self):
        return type(self), (self.issues,), self.__dict__
