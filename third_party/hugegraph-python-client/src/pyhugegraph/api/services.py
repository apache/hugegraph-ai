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


from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.structure.services_data import ServiceCreateParameters
from pyhugegraph.utils import huge_router as router


class ServicesManager(HugeParamsBase):
    """
    Manages services within HugeGraph via HTTP endpoints.

    This class acts as an interface to manage different types of services such as online
    transaction processing (OLTP) and online analytical processing (OLAP)
    in HugeGraph. It currently supports dynamic creation and management of services,
    with a focus on OLTP services for now.

    Methods:
        create_service(graphspace: str, service_create_parameters: ServiceCreateParameters):
            Creates a new service within a specified graph space using the provided parameters.
            Returns a dictionary with the details of the created service.

        list_services(graphspace: str):
            Lists all services available within a specified graph space.
            Returns a dictionary containing a list of service names.

        get_service(graphspace: str, service: str):
            Retrieve detailed information about a specific service within a graph space.
            Returns a dictionary with the service details.

        delete_service(graphspace: str, service: str):
            Delete a specific service within a graph space after confirmation.
            No return value expected; the operation's success is indicated by an HTTP 204 status code.
    """

    @router.http("POST", "/graphspaces/{graphspace}/services")
    def create_services(
        self,
        graphspace: str,  # pylint: disable=unused-argument
        body_params: ServiceCreateParameters,
    ):
        """
        Create HugeGraph Servers.

        Args:
            service_create (ServiceCreate): The name of the service.

        Returns:
            dict: A dictionary containing the response from the HTTP request.
        """
        return self._invoke_request(data=body_params.dumps())

    @router.http("GET", "/graphspaces/{graphspace}/services")
    def list_services(self, graphspace: str):  # pylint: disable=unused-argument
        """
        List all services in a specified graph space.

        Args:
            graphspace (str): The name of the graph space to list services from.


        Response:
            A list of service names in the specified graph space.

        Returns:
            dict: A dictionary containing the list of service names.
            Example:
            {
                "services": ["service1", "service2"]
            }
        """
        return self._invoke_request()

    @router.http("GET", "/graphspaces/{graphspace}/services/{service}")
    def get_service(self, graphspace: str, service: str):  # pylint: disable=unused-argument
        """
        Retrieve the details of a specific service.

        Args:
            graphspace (str): The name of the graph space where the service is located.
            service (str): The name of the service to retrieve details for.

        Response:
            A dictionary containing the details of the specified service.

        Returns:
            dict: A dictionary with the service details.
            Example:
            {
                "name": "service1",
                "description": "This is a description of service1.",
                "type": "OLTP",
                // ... other service details
            }
        """
        return self._invoke_request()

    def delete_service(self, graphspace: str, service: str):  # pylint: disable=unused-argument
        """
        Delete a specific service within a graph space.

        Args:
            graphspace (str): The name of the graph space where the service is located.
            service (str): The name of the service to be deleted.

        Response:
            204

        Returns:
            None
        """
        return self._sess.request(
            f"/graphspaces/{graphspace}/services/{service}?confirm_message=I'm sure to delete the service",
            "DELETE",
        )
