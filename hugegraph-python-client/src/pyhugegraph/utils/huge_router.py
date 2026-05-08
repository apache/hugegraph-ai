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

import functools
import inspect
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pyhugegraph.utils.log import log
from pyhugegraph.utils.util import ResponseValidation

if TYPE_CHECKING:
    from pyhugegraph.api.common import HGraphContext


class SingletonMeta(type):
    _instances: ClassVar[dict] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __call__(cls, *args, **kwargs):
        """
        Ensure that only one instance of the class is created.
        If an instance already exists, return it; otherwise, create a new one.
        This method is thread-safe.
        """
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


@dataclass
class Route:
    method: str
    path: str
    request_func: Callable | None = None


class RouterRegistry(metaclass=SingletonMeta):
    def __init__(self):
        self._routers: dict[str, Route] = {}

    def register(self, key: str, route: Route):
        self._routers[key] = route

    @property
    def routers(self):
        return self._routers

    def __repr__(self) -> str:
        return str(self._routers)


def register(method: str, path: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        RouterRegistry().register(
            func.__qualname__,
            Route(method, path),
        )

        @functools.wraps(func)
        def wrapper(self: "HGraphContext", *args: Any, **kwargs: Any) -> Any:
            route = RouterRegistry().routers.get(func.__qualname__)

            if route.request_func is None:
                route.request_func = functools.partial(self.session.request, method=method)

            return func(self, *args, **kwargs)

        return wrapper

    return decorator


def http(method: str, path: str) -> Callable:
    """
    A decorator to format the pathinfo and inject a request function into the decorated method.

    Args:
        method (str): The HTTP method to be used (e.g., 'GET', 'POST').
        path (str): The pathinfo template to be formatted with function arguments.

    Returns:
        Callable: The decorator function.
    """

    def decorator(func: Callable) -> Callable:
        """Decorator function that modifies the original function."""
        RouterRegistry().register(func.__qualname__, Route(method, path))

        @functools.wraps(func)
        def wrapper(self: "HGraphContext", *args: Any, **kwargs: Any) -> Any:
            """
            Wrapper function to format the pathinfo and create a partial request function.

            Args:
                self (HGraphContext): The instance of the class.
                *args (Any): Positional arguments to the decorated function.
                **kwargs (Any): Keyword arguments to the decorated function.

            Returns:
                Any: The result of the decorated function.
            """
            # If the pathinfo contains placeholders, format it with the actual arguments
            if re.search(r"{\w+}", path):
                sig = inspect.signature(func)
                bound_args = sig.bind(self, *args, **kwargs)
                bound_args.apply_defaults()
                all_kwargs = dict(bound_args.arguments)
                # Remove 'self' from the arguments used to format the pathinfo
                all_kwargs.pop("self")

                # Graphspace-scoped auth paths require a graphspace: HugeGraph 1.7.0+
                # only mounts UserAPI/AccessAPI/BelongAPI/TargetAPI under
                # /graphspaces/{graphspace}/auth/..., so we fail fast when the
                # session lacks one rather than producing an unreachable URL.
                if "{graphspace}" in path:
                    graphspace_arg = all_kwargs.get("graphspace")
                    graphspace_cfg = getattr(self.session.cfg, "graphspace", None)
                    gs_supported = getattr(self.session.cfg, "gs_supported", False)

                    if not (graphspace_arg or (graphspace_cfg and gs_supported)):
                        raise ValueError(
                            "graphspace is required for auth endpoints on HugeGraph 1.7.0+. "
                            "Ensure gs_supported is True and graphspace is configured."
                        )

                    prefix = "/graphspaces/{graphspace}"
                    if not path.startswith(prefix + "/"):
                        raise ValueError(f"Expected graphspace-prefixed path, got: {path}")

                    all_kwargs["graphspace"] = graphspace_arg or graphspace_cfg
                    formatted_path = path.format(**all_kwargs)
                else:
                    formatted_path = path.format(**all_kwargs)
            else:
                formatted_path = path

            # Use functools.partial to create a partial function for making requests
            make_request = functools.partial(self.session.request, formatted_path, method)
            # Store the partial function on the instance
            setattr(self, f"_{func.__name__}_request", make_request)

            return func(self, *args, **kwargs)

        return wrapper

    return decorator


class RouterMixin:
    def _invoke_request_registered(self, placeholders: dict | None = None, validator=None, **kwargs: Any):
        """
        Make an HTTP request using the stored partial request function.
        Args:
            **kwargs (Any): Keyword arguments to be passed to the request function.
        Returns:
            Any: The response from the HTTP request.
        """
        if validator is None:
            validator = ResponseValidation()
        frame = inspect.currentframe().f_back
        fname = frame.f_code.co_name
        route = RouterRegistry().routers.get(f"{self.__class__.__name__}.{fname}")

        if re.search(r"{\w+}", route.path):
            assert placeholders is not None, "Placeholders must be provided"
            formatted_path = route.path.format(**placeholders)
        else:
            formatted_path = route.path

        log.debug(  # pylint: disable=logging-fstring-interpolation
            f"Invoke request registered with router: {route.method}: "
            f"{self.__class__.__name__}.{fname}: {formatted_path}"
        )
        return route.request_func(formatted_path, validator=validator, **kwargs)

    def _invoke_request(self, validator=None, **kwargs: Any):
        """
        Make an HTTP request using the stored partial request function.

        Args:
            **kwargs (Any): Keyword arguments to be passed to the request function.

        Returns:
            Any: The response from the HTTP request.
        """
        if validator is None:
            validator = ResponseValidation()
        frame = inspect.currentframe().f_back
        fname = frame.f_code.co_name
        log.debug(  # pylint: disable=logging-fstring-interpolation
            f"Invoke request: {self.__class__.__name__!s}.{fname}"
        )
        return getattr(self, f"_{fname}_request")(validator=validator, **kwargs)
