"""Module for getting proxy object for AWS SSM parameter store object."""

import logging
from typing import Dict, Optional

from botocore.exceptions import ClientError, ParamValidationError
from pydantic import TypeAdapter, ValidationError
from ssm_parameter_store import EC2ParameterStore
from typing_extensions import Type, TypedDict, TypeVar

from .environment import get_environment_variable

log = logging.getLogger(__name__)


class REDCapParameters(TypedDict):
    """Dictionary type for parameters needed to access a REDCap project."""

    url: str
    token: str


class REDCapReportParameters(TypedDict):
    """Dictionary type for parameters needed to access a REDCap report."""

    url: str
    token: str
    reportid: str


class S3Parameters(TypedDict):
    """Dictionary type for parameters to access an S3 bucket."""

    accesskey: str
    secretkey: str
    region: str
    bucket: str


class RDSParameters(TypedDict):
    """Dictionary type for parameters to access MySQL RDS."""

    host: str
    user: str
    password: str


class CoManageParameters(TypedDict):
    """Dictionary type for parameters to access CoManage registry."""

    host: str
    username: str
    apikey: str
    coid: str


class NotificationParameters(TypedDict):
    """Dictionary type for email sender."""

    sender: str


class URLParameter(TypedDict):
    """Dictionary type for url parameter."""

    url: str


class ParameterError(Exception):
    """Error class for errors that occur when reading parameters."""


# TODO: remove type ignore when using python 3.12 or above
P = TypeVar("P", bound=TypedDict)  # type: ignore


class ParameterStore:
    """Wrapper class for parameter store to pull particular parameters."""

    def __init__(self, parameter_store: EC2ParameterStore) -> None:
        self.__store = parameter_store
        self.__client = parameter_store.client  # type: ignore

    @classmethod
    def create_from_environment(cls) -> "ParameterStore":
        """Gets a proxy object for the parameter store if AWS credentials are
        set. Expects AWS_SECRET_ACCESS_KEY, AWS_ACCESS_KEY_ID, and
        AWS_DEFAULT_REGION.

        Returns:
            parameter store object if credentials are valid, and None otherwise
        Raises:
            ParameterError if any of the environment variables are missing
        """
        secret_key = get_environment_variable("AWS_SECRET_ACCESS_KEY")
        access_id = get_environment_variable("AWS_ACCESS_KEY_ID")
        region = get_environment_variable("AWS_DEFAULT_REGION")
        if not secret_key or not access_id or not region:
            raise ParameterError("Environment variables not found")

        return ParameterStore(
            EC2ParameterStore(
                aws_access_key_id=access_id,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
        )

    def get_parameters(self, *, param_type: Type[P], parameter_path: str) -> P:
        """Pulls the parameters at the path and checks that they match the
        given TypedDict.

        Args:
          type: the subclass of TypedDict
          parameter_path: the path in the parameter store
        Returns:
          the dictionary of parameters
        Raises:
          ParameterError if the parameters don't match the type
        """
        parameter_path = (
            parameter_path if parameter_path.endswith("/") else parameter_path + "/"
        )

        parameters = self.__store.get_parameters_by_path(path=parameter_path)
        type_adapter = TypeAdapter(param_type)
        try:
            return type_adapter.validate_python(parameters)
        except ValidationError as error:
            raise ParameterError(
                f"Incorrect parameters at {parameter_path}: {error}"
            ) from error

    # pylint disable=(line-to-long)
    def get_api_key(self, path_prefix: str) -> str:
        """Returns the GearBot API key.

        Args:
          path_prefix: the prefix for the parameter path
        Returns:
          the GearBot API key
        Raises:
          ParameterError: if the API key is not found
        """
        parameter_name = "apikey"
        path_prefix = path_prefix[:-1] if path_prefix.endswith("/") else path_prefix
        parameter_path = f"{path_prefix}/{parameter_name}"
        try:
            parameter = self.__store.get_parameter(parameter_path, decrypt=True)

        except self.__store.client.exceptions.ParameterNotFound as error:  # type: ignore
            raise ParameterError("No API Key found") from error

        apikey = parameter.get(parameter_name)
        if not apikey:
            raise ParameterError("No API Key found")

        return apikey

    def get_all_redcap_parameters_at_path(
        self, *, base_path: str, prefix: Optional[str] = None
    ) -> Dict[str, REDCapParameters]:
        """Pulls URLs and Tokens for all the REDCap projects stored under a
        base path in AWS parameter store.

        Args:
            base_path: base path in the parameter store
            prefix (optional): parameter name prefix

        Returns:
            Dict[str, REDCapParameters]: Dictionary of REDCap parameters by PID

        Raises:
          ParameterError: if errors occur while retrieving parameters
        """

        if not base_path.endswith("/"):
            base_path += "/"

        redcap_params = {}
        try:
            parameters = self.__store.get_parameters_with_hierarchy(
                base_path, decrypt=True
            )
        except (ClientError, ParamValidationError) as error:
            raise ParameterError(
                f"Failed to retrieve parameters at {base_path}: {error}"
            ) from error

        for key, prj_params in parameters.items():
            if prefix and not key.startswith(prefix):
                log.warning("Unexpected parameter %s at path %s", key, base_path)
                continue

            type_adapter = TypeAdapter(REDCapParameters)
            try:
                redcap_params[key] = type_adapter.validate_python(prj_params)
            except ValidationError as error:
                raise ParameterError(
                    f"Incorrect parameters at {base_path}/{key}: {error}"
                ) from error

        return redcap_params

    def get_redcap_parameters(self, *, base_path: str, pid: int) -> REDCapParameters:
        """Pulls URL and Token for the respective REDCap project from SSM
        parameter store.

        Args:
            base_path: base path in the parameter store
            pid: REDCap project ID

        Returns:
          the REDCap credentials stored at the parameter path

        Raises:
          ParameterError if any of the parameters are missing
        """

        if not base_path.endswith("/"):
            base_path += "/"

        param_path = base_path + "pid_" + str(pid)

        return self.get_parameters(
            param_type=REDCapParameters, parameter_path=param_path
        )

    def get_redcap_report_params_for_project(
        self, *, base_path: str, pid: int, report_id: int
    ) -> REDCapReportParameters:
        """Pulls URL and Token for the respective REDCap project from SSM
        parameter store.

        Args:
          base_path: base path in the parameter store
          pid: REDCap project ID
          report_id: REDCap report ID
        Returns:
          the REDCap credentials stored at the parameter path
        Raises:
          ParameterError if any of the credentials are missing
        """

        if not base_path.endswith("/"):
            base_path += "/"

        param_path = base_path + "pid_" + str(pid)
        try:
            prj_params = self.__store.get_parameters_by_path(param_path, decrypt=True)
        except (ClientError, ParamValidationError) as error:
            raise ParameterError(
                f"Failed to retrieve parameters at {param_path}"
            ) from error

        if not prj_params or "url" not in prj_params or "token" not in prj_params:
            raise ParameterError(f"Incorrect parameters at {param_path}")

        url = prj_params.get("url")
        token = prj_params.get("token")

        if not url or not token:
            raise ParameterError(f"Incorrect parameters at {param_path}")

        return REDCapReportParameters(url=url, token=token, reportid=str(report_id))

    def get_redcap_report_parameters(self, param_path: str) -> REDCapReportParameters:
        """Pulls URL, Token, and ReportID for REDCap report from SSM parameter
        store.

        Args:
          param_path: the path in the parameter store
        Returns:
          the REDCap report credentials stored at the parameter path
        Raises:
          ParameterError if any of the credentials are missing
        """
        return self.get_parameters(
            param_type=REDCapReportParameters, parameter_path=param_path
        )

    def get_s3_parameters(self, param_path: str) -> S3Parameters:
        """Pulls S3 access credentials from the SSM parameter store at the
        given path.

        Args:
          param_path: the path in the parameter store
        Returns:
          the S3 credentials stored at the parameter path
        Raises:
          ParameterError if any of the credentials are missing
        """
        return self.get_parameters(param_type=S3Parameters, parameter_path=param_path)

    def get_rds_parameters(self, param_path: str) -> RDSParameters:
        """Pulls RDS parameters from the SSM parameter store at the given path.

        Args:
          param_path: the path in the parameter store
        Returns:
          the RDS credentials stored at the parameter path
        Raises:
          ParameterError if any of the credentials are missing
        """
        return self.get_parameters(param_type=RDSParameters, parameter_path=param_path)

    def set_redcap_project_parameters(
        self, *, base_path: str, pid: int, url: str, token: str
    ):
        """Store API URL and token for the respective REDCap project in AWS
        parameter store.

        Args:
          base_path: base path in the parameter store
          pid: REDCap project ID
          url: REDCap API url
          token: REDCap API token for the specified project
        Raises:
          ParameterError if failed to update parameter store
        """

        if not base_path.endswith("/"):
            base_path += "/"

        param_path = base_path + "pid_" + str(pid)
        try:
            param_name_url = param_path + "/url"
            self.__client.put_parameter(
                Name=param_name_url, Value=url, Type="String", Overwrite=True
            )

            param_name_token = param_path + "/token"
            self.__client.put_parameter(
                Name=param_name_token, Value=token, Type="SecureString", Overwrite=True
            )
        except Exception as error:
            raise ParameterError(
                f"Failed to store parameters at {param_path}"
            ) from error

    def get_comanage_parameters(self, param_path: str) -> CoManageParameters:
        """Pulls comanage parameters from the SSM parameter store at the given
        path.

        Args:
          param_path: the path in the parameter store
        Returns:
          the comanage parameters stored at the path
        Raises:
          ParameterError if any of the parameters are missing
        """
        return self.get_parameters(
            param_type=CoManageParameters, parameter_path=param_path
        )

    def get_notification_parameters(self, param_path: str) -> NotificationParameters:
        """Pulls notification email parameters from the SSM parameter store at
        the given path.

        Args:
          param_path: the path in the parameter store
        Returns:
          the notification parameters stored at the path
        Raises:
          ParameterError if any of the parameters are missing
        """
        return self.get_parameters(
            param_type=NotificationParameters, parameter_path=param_path
        )

    def get_portal_url(self, param_path: str) -> URLParameter:
        """Pulls the portal URL parameter from the SSM parameter store at the
        given path.

        Args:
          param_path: the path in the parameter store
        Returns:
          the portal URL parameter stored at the path
        Raises:
          ParameterError if the parameter is missing
        """
        return self.get_parameters(param_type=URLParameter, parameter_path=param_path)
