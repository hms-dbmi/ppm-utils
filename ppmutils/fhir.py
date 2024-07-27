import collections
import json as libjson
import warnings
import uuid
import re
import base64
import string
import os
import traceback
from abc import ABC, abstractmethod
from typing import Optional, Union, Any, Literal, Callable, TypeAlias
from typing_extensions import Self
from datetime import datetime, date, timezone

import boto3
import requests
from furl import furl, Query
from dateutil.parser import parse
from dateutil.tz import tz
from google.oauth2 import service_account
from google.auth.transport import requests as google_requests
from requests_auth_aws_sigv4 import AWSSigV4
from django.utils.safestring import mark_safe
from django.conf import settings
from fhirclient.models.domainresource import DomainResource
from fhirclient.models.fhirdate import FHIRDate
from fhirclient.models.period import Period
from fhirclient.models.fhirinstant import FHIRInstant
from fhirclient.models.fhirdatetime import FHIRDateTime
from fhirclient.models.patient import Patient
from fhirclient.models.flag import Flag
from fhirclient.models.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhirclient.models.list import List as FHIRList, ListEntry
from fhirclient.models.organization import Organization
from fhirclient.models.documentreference import DocumentReference
from fhirclient.models.researchstudy import ResearchStudy
from fhirclient.models.researchsubject import ResearchSubject
from fhirclient.models.fhirreference import FHIRReference
from fhirclient.models.codeableconcept import CodeableConcept
from fhirclient.models.coding import Coding
from fhirclient.models.communication import Communication
from fhirclient.models.resource import Resource
from fhirclient.models.questionnaire import Questionnaire, QuestionnaireItem
from fhirclient.models.questionnaireresponse import QuestionnaireResponse
from fhirclient.models.humanname import HumanName
from fhirclient.models.relatedperson import RelatedPerson
from fhirclient.models.fhirelementfactory import FHIRElementFactory
from fhirclient.models.narrative import Narrative
from fhirclient.models.consent import Consent, ConsentPolicy
from fhirclient.models.contract import Contract, ContractSigner
from fhirclient.models.signature import Signature
from fhirclient.models.composition import Composition, CompositionSection
from fhirclient.models.questionnaireresponse import QuestionnaireResponseItemAnswer
from fhirclient.models.questionnaireresponse import QuestionnaireResponseItem
from fhirclient.models.extension import Extension
from fhirclient.models.fhirabstractbase import FHIRValidationError
from fhirclient.models.identifier import Identifier

from ppmutils.ppm import PPM

import logging

logger = logging.getLogger(__name__)

HttpMethod: TypeAlias = Literal["get", "post", "put", "patch", "delete", "head"]

# Constants
PPM_GCP_CREDENTIALS_KEY = "PPM_GCP_HEALTHCARE_CREDENTIALS"


class Backend(ABC):
    @classmethod
    def instance(cls, url: str) -> Self:
        """
        This method inspects the current setting for FHIR URL and returns
        an instance of the Backend class that is being used for FHIR.

        :param url: The URL of the FHIR backend instance
        :type url: str
        :return: An instance of the concrete Backend class
        :rtype: Backend
        """
        # Check for AWS
        if "amazonaws.com" in url:
            return AWSHealthlake()
        elif "googleapis.com" in url:
            return GCPHealthcareAPI()
        elif "azurehealthcareapis.com" in url:
            return AzureHealthcareAPI()
        else:
            return HAPIFHIR()

    @abstractmethod
    def request(self, method: HttpMethod, url: str, **kwargs) -> requests.Response:
        """
        A generic method implementation for an HTTP request to a FHIR instance.

        :param method: The HTTP request type to make
        :type method: HttpMethod
        :param url: The URL to make the request to
        :type url: str
        :return: The response object from the request
        :rtype: requests.Response
        """
        pass


class AWSHealthlake(Backend):
    def request(self, method: HttpMethod, url: str, **kwargs) -> requests.Response:
        """
        A generic method implementation for an HTTP GET to a Healthlake
        FHIR instance.

        :param method: The HTTP request type to make
        :type method: HttpMethod
        :param url: The URL to make the request to
        :type url: str
        :return: The response object from the request
        :rtype: requests.Response
        """
        # Get region
        region = os.environ.get("AWS_REGION", "us-east-1")
        session = boto3.session.Session(region_name=region)
        auth = AWSSigV4("healthlake", session=session)

        # Make the request
        return requests.request(method=method, url=url, auth=auth, **kwargs)


class GCPHealthcareAPI(Backend):

    _SETTINGS_CACHE_KEY = "_GOOGLE_OAUTH2_CACHED_TOKEN"
    _SETTINGS_CACHE_TOKEN_KEY = "token"
    _SETTINGS_CACHE_EXPIRY_KEY = "expiry"

    @property
    def session(self) -> requests.Session:

        # Check cache for token
        cache = getattr(settings, self._SETTINGS_CACHE_KEY, {})
        token = cache.get(self._SETTINGS_CACHE_TOKEN_KEY)
        expiry = cache.get(self._SETTINGS_CACHE_EXPIRY_KEY)
        if expiry:
            expiry = parse(expiry)
            logger.debug(f"PPM/FHIR/GCP: Token expires in: {int((expiry - datetime.utcnow()).total_seconds())}")

        if token is None or expiry is None or datetime.utcnow() >= expiry:

            # Check whether credentials are string or file
            if os.environ[PPM_GCP_CREDENTIALS_KEY].startswith("/"):
                logger.debug("PPM/FHIR: GCS credentials via file")
                credentials = service_account.Credentials.from_service_account_file(os.environ[PPM_GCP_CREDENTIALS_KEY])
            else:
                # Gets credentials from the environment.
                logger.debug("PPM/FHIR: GCS credentials via environment variable")
                credentials = service_account.Credentials.from_service_account_info(
                    libjson.loads(base64.b64decode(os.environ[PPM_GCP_CREDENTIALS_KEY].encode()).decode())
                )

            # Set scopes
            scoped_credentials = credentials.with_scopes(["https://www.googleapis.com/auth/cloud-platform"])

            # Get token
            logger.debug("PPM/FHIR/GCP: Refreshing credentials")
            scoped_credentials.refresh(google_requests.Request())

            # Set local variables
            token = scoped_credentials.token
            expiry = scoped_credentials.expiry.isoformat()

            # Save token and expiry in settings
            setattr(
                settings,
                self._SETTINGS_CACHE_KEY,
                {
                    self._SETTINGS_CACHE_TOKEN_KEY: token,
                    self._SETTINGS_CACHE_EXPIRY_KEY: expiry,
                },
            )
            logger.debug(f"PPM/FHIR/GCP: New token expiry: {expiry}")

        # Create a session
        session = requests.Session()
        session.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/fhir+json",
        }

        return session

    def request(self, method: HttpMethod, url: str, **kwargs) -> requests.Response:
        """
        A generic method implementation for an HTTP GET to a GCP Healthcare API
        FHIR instance.

        :param method: The HTTP request type to make
        :type method: HttpMethod
        :param url: The URL to make the request to
        :type url: str
        :return: The response object from the request
        :rtype: requests.Response
        """
        # Make the request
        response = self.session.request(method=method, url=url, **kwargs)

        # Check for a session reset
        if response and response.status_code in [401, 403]:

            # Reset and try again
            self._session = None

            response = self.session.request(method=method, url=url, **kwargs)

        return response


class AzureHealthcareAPI(Backend):
    def request(self, method: HttpMethod, url: str, **kwargs) -> requests.Response:
        """
        A generic method implementation for an HTTP GET to a Azure Healthcare
        APIs FHIR instance.

        :param method: The HTTP request type to make
        :type method: HttpMethod
        :param url: The URL to make the request to
        :type url: str
        :return: The response object from the request
        :rtype: requests.Response
        """
        raise NotImplementedError("Azure Healthcare APIs not yet supported")


class HAPIFHIR(Backend):
    def request(self, method: HttpMethod, url: str, **kwargs) -> requests.Response:
        """
        A generic method implementation for an HTTP GET to a HAPI-FHIR instance.

        :param method: The HTTP request type to make
        :type method: HttpMethod
        :param url: The URL to make the request to
        :type url: str
        :return: The response object from the request
        :rtype: requests.Response
        """
        # Make the request
        return requests.request(method=method, url=url, **kwargs)


class FHIR:

    #
    # CONSTANTS
    #

    # This is the system used for Patient identifiers based on email
    patient_email_identifier_system = "http://schema.org/email"
    patient_email_telecom_system = "email"
    patient_phone_telecom_system = "phone"
    patient_twitter_telecom_system = "other"

    # Set the coding types
    study_participant_identifier_system_base = "https://peoplepoweredmedicine.org/study/participant"
    patient_identifier_system = "https://peoplepoweredmedicine.org/fhir/patient"
    enrollment_flag_coding_system = "https://peoplepoweredmedicine.org/enrollment-status"
    enrollment_flag_study_identifier_system = "https://peoplepoweredmedicine.org/fhir/flag/study"
    enrollment_flag_patient_identifier_system = "https://peoplepoweredmedicine.org/fhir/flag/patient"

    research_study_identifier_system = "https://peoplepoweredmedicine.org/fhir/study"
    research_study_coding_system = "https://peoplepoweredmedicine.org/study"

    research_subject_study_identifier_system = "https://peoplepoweredmedicine.org/fhir/subject/study"
    research_subject_patient_identifier_system = "https://peoplepoweredmedicine.org/fhir/subject/patient"
    research_subject_coding_system = "https://peoplepoweredmedicine.org/subject"

    device_title_system = "https://peoplepoweredmedicine.org/fhir/device/title"
    device_tracking_system = "https://peoplepoweredmedicine.org/fhir/device/tracking"
    device_identifier_system = "https://peoplepoweredmedicine.org/fhir/device"
    device_coding_system = "https://peoplepoweredmedicine.org/device"
    device_study_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/study"

    # Questionnaire system URLs
    questionnaire_context_coding_system = "https://peoplepoweredmedicine.org/fhir/questionnaire/context"

    # Consent exception extension URL
    consent_exception_extension_url = "https://peoplepoweredmedicine.org/fhir/StructureDefinition/consent-exception"

    # Type system for PPM data documents
    data_document_reference_identifier_system = "https://peoplepoweredmedicine.org/document-type"

    # Type system for PPM documents
    ppm_document_reference_type_system = "https://peoplepoweredmedicine.org/fhir/ppm/document-type"

    # Type system for PPM consent resources
    ppm_consent_type_system = "http://loinc.org"
    ppm_consent_type_value = "83930-8"
    ppm_consent_type_display = "Research Consent"

    # Point of care codes
    SNOMED_LOCATION_CODE = "SNOMED:43741000"
    SNOMED_VERSION_URI = "http://snomed.info/sct/900000000000207008"
    points_of_care_list_identifier_system = "https://peoplepoweredmedicine.org/fhir/list/points-of-care"
    organization_identifier_system = "https://peoplepoweredmedicine.org/fhir/organization/name"

    # PicnicHealth notification flags
    ppm_comm_identifier_system = "https://peoplepoweredmedicine.org/fhir/communication"
    ppm_comm_coding_system = "https://peoplepoweredmedicine.org/ppm-notification"

    # Patient extension flags
    twitter_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/uses-twitter"
    fitbit_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/uses-fitbit"
    picnichealth_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/registered-picnichealth"
    facebook_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/uses-facebook"
    smart_on_fhir_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/uses-smart-on-fhir"
    referral_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/how-did-you-hear-about-us"
    admin_notified_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/admin-notified"
    procure_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/uses-procure"

    # Qualtrics IDs
    qualtrics_survey_identifier_system = "https://peoplepoweredmedicine.org/fhir/qualtrics/survey"
    qualtrics_survey_questionnaire_identifier_system = (
        "https://peoplepoweredmedicine.org/fhir/qualtrics/survey/questionnaire"
    )
    qualtrics_survey_version_identifier_system = "https://peoplepoweredmedicine.org/fhir/qualtrics/survey/version"
    qualtrics_response_identifier_system = "https://peoplepoweredmedicine.org/fhir/qualtrics/response"
    qualtrics_survey_coding_system = "https://peoplepoweredmedicine.org/qualtrics-survey"
    qualtrics_response_coding_system = "https://peoplepoweredmedicine.org/qualtrics-response"
    qualtrics_survey_extension_url = "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/qualtrics-survey"

    # This list specifies the set of resources that reference a Patient and
    # by what property that reference is set.
    PARTICIPANT_PATIENT_INCLUDES = ["*"]
    PARTICIPANT_PATIENT_REVINCLUDES = [
        "ResearchSubject:individual",
        "Flag:subject",
        "DocumentReference:subject",
        "QuestionnaireResponse:source",
        "Composition:subject",
        "Consent:patient",
        "Contract:signer",
        "List:subject",
        "Device:patient",
        "Communication:recipient",
        "RelatedPerson:patient",
    ]
    PARTICIPANT_PATIENT_REVINCLUDE_ITERATES = []
    PARTICIPANT_PATIENT_INCLUDE_ITERATES = [
        # BUG: GCP does not yet honor this reference: "QuestionnaireResponse:questionnaire",
        "QuestionnaireResponse:subject",  # TODO: For the time being, also reference Questionnaire via 'subject'
        "ResearchSubject:study",
        "List:item",
    ]

    #
    # META
    #

    _backend = None

    @classmethod
    def backend(cls):

        if cls._backend is None:

            # Get the backend class instance
            cls._backend = Backend.instance(url=PPM.fhir_url())

        return cls._backend

    #
    # FHIR HTTP
    #

    @staticmethod
    def get(url: str, params: dict = None, headers: dict = None, fail: bool = False) -> Optional[requests.Response]:
        """
        A generic method implementation for an HTTP GET to a Healthlake
        FHIR instance.

        :param url: The additional path components to GET from
        :type url: list[str]
        :param params: The query to include in the URL of the request
        :type params: dict, defaults to None
        :param headers: The headers to include in the request
        :type headers: dict, defaults to None
        :param fail: Whether to return None when an error is encountered
        :type fail: bool, defaults to False
        :return: The response object from the request
        :rtype: requests.Response, defaults to None
        """
        logger.debug(f"PPM/FHIR: GET '{url}'")
        content = response = None
        try:
            # Make the request
            response = FHIR.backend().request(
                "get",
                url=url,
                params=params,
                headers=headers,
            )
            content = response.content
            logger.debug(f"PPM/FHIR: HTTP GET Response {response.status_code}")

            # Check the response
            response.raise_for_status()

        except requests.HTTPError as e:
            # Attempt to format response (FHIR returns JSON in failed requests)
            try:
                reason = libjson.dumps(response.json(), indent=4)
            except requests.exceptions.JSONDecodeError:
                reason = str(content)
            logger.debug(f"PPM/FHIR: HTTP GET response: {reason}")
            logger.exception(
                f"PPM/FHIR: HTTP GET request error: {e}",
                extra={
                    "url": url,
                    "params": params,
                    "content": content,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: HTTP GET resource error: {e}",
                exc_info=True,
                extra={
                    "url": url,
                    "params": params,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        return response

    @staticmethod
    def post(
        url: str, data: dict = None, json: dict = None, params: dict = None, headers: dict = None, fail: bool = False
    ) -> Optional[requests.Response]:
        """
        A generic method implementation for an HTTP POST to a Healthlake
        FHIR instance.

        :param url: The URL to POST to
        :type url: str
        :param data: The form-encoded data to include in the body of the request
        :type data: dict, defaults to None
        :param json: The JSON data to include in the body of the request
        :type json: dict, defaults to None
        :param params: The query to include in the URL of the request
        :type params: dict, defaults to None
        :param headers: The headers to include in the request
        :type headers: dict, defaults to None
        :param fail: Whether to return None when an error is encountered
        :type fail: bool, defaults to False
        :return: The response object from the request
        :rtype: requests.Response, defaults to None
        """
        logger.debug(f"PPM/FHIR: POST {url}")
        content = response = None
        try:
            # Make the request
            response = FHIR.backend().request(
                "post",
                url=url,
                json=json,
                data=data,
                params=params,
                headers=headers,
            )
            content = response.content
            logger.debug(f"PPM/FHIR: HTTP POST Response {response.status_code}")

            # Check the response
            response.raise_for_status()

            return response

        except requests.HTTPError as e:
            # Attempt to format response (FHIR returns JSON in failed requests)
            try:
                reason = libjson.dumps(response.json(), indent=4)
            except requests.exceptions.JSONDecodeError:
                reason = str(content)
            logger.debug(f"PPM/FHIR: HTTP POST response: {reason}")
            logger.exception(
                f"PPM/FHIR: HTTP POST request error: {e}",
                extra={
                    "url": url,
                    "content": content,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: HTTP POST resource error: {e}",
                exc_info=True,
                extra={
                    "url": url,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        return response

    @staticmethod
    def patch(
        url: str, data: dict = None, json: dict = None, params: dict = None, headers: dict = None, fail: bool = False
    ) -> Optional[requests.Response]:
        """
        A generic method implementation for an HTTP PATCH to a Healthlake
        FHIR instance.

        :param url: The URL to PATCH to
        :type url: str
        :param data: The form-encoded data to include in the body of the request
        :type data: dict, defaults to None
        :param json: The JSON data to include in the body of the request
        :type json: dict, defaults to None
        :param params: The query to include in the URL of the request
        :type params: dict, defaults to None
        :param headers: The headers to include in the request
        :type headers: dict, defaults to None
        :param fail: Whether to return None when an error is encountered
        :type fail: bool, defaults to False
        :return: The response object from the request
        :rtype: requests.Response, defaults to None
        """
        logger.debug(f"PPM/FHIR: PATCH {url}")
        content = response = None
        try:
            # Make the request
            response = FHIR.backend().request(
                "patch",
                url=url,
                data=data,
                json=json,
                params=params,
                headers=headers,
            )
            content = response.content
            logger.debug(f"PPM/FHIR: HTTP PATCH Response {response.status_code}")

            # Check the response
            response.raise_for_status()

            return response

        except requests.HTTPError as e:
            # Attempt to format response (FHIR returns JSON in failed requests)
            try:
                reason = libjson.dumps(response.json(), indent=4)
            except requests.exceptions.JSONDecodeError:
                reason = str(content)
            logger.debug(f"PPM/FHIR: HTTP PATCH response: {reason}")
            logger.exception(
                f"PPM/FHIR: HTTP PATCH request error: {e}",
                extra={
                    "url": url,
                    "content": content,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: HTTP PATCH resource error: {e}",
                exc_info=True,
                extra={
                    "url": url,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        return response

    @staticmethod
    def put(
        url: str, data: dict = None, json: dict = None, params: dict = None, headers: dict = None, fail: bool = False
    ) -> Optional[requests.Response]:
        """
        A generic method implementation for an HTTP PUT to a Healthlake
        FHIR instance.

        :param url: The URL to POST to
        :type url: str
        :param data: The form-encoded data to include in the body of the request
        :type data: dict, defaults to None
        :param json: The JSON data to include in the body of the request
        :type json: dict, defaults to None
        :param params: The query to include in the URL of the request
        :type params: dict, defaults to None
        :param headers: The headers to include in the request
        :type headers: dict, defaults to None
        :param fail: Whether to return None when an error is encountered
        :type fail: bool, defaults to False
        :return: The response object from the request
        :rtype: requests.Response, defaults to None
        """
        logger.debug(f"PPM/FHIR: PUT {url}")
        content = response = None
        try:
            # Make the request
            response = FHIR.backend().request(
                "put",
                url=url,
                data=data,
                json=json,
                params=params,
                headers=headers,
            )
            content = response.content
            logger.debug(f"PPM/FHIR: HTTP PUT Response {response.status_code}")

            # Check the response
            response.raise_for_status()

            return response

        except requests.HTTPError as e:
            # Attempt to format response (FHIR returns JSON in failed requests)
            try:
                reason = libjson.dumps(response.json(), indent=4)
            except requests.exceptions.JSONDecodeError:
                reason = str(content)
            logger.debug(f"PPM/FHIR: HTTP PUT response: {reason}")
            logger.exception(
                f"PPM/FHIR: HTTP PUT request error: {e}",
                extra={
                    "url": url,
                    "params": params,
                    "content": content,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: HTTP PUT resource error: {e}",
                exc_info=True,
                extra={
                    "url": url,
                    "params": params,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        return response

    @staticmethod
    def delete(url: str, params: dict = None, headers: dict = None, fail: bool = False) -> Optional[requests.Response]:
        """
        A generic method implementation for an HTTP DELETE to a Healthlake
        FHIR instance.

        :param url: The URL to DELETE to
        :type url: str
        :param params: The query to include in the URL of the request
        :type params: dict, defaults to None
        :param headers: The headers to include in the request
        :type headers: dict, defaults to None
        :param fail: Whether to return None when an error is encountered
        :type fail: bool, defaults to False
        :return: The response object from the request
        :rtype: requests.Response, defaults to None
        """
        logger.debug(f"PPM/FHIR: DELETE '{url}'")
        content = response = None
        try:
            # Make the request
            response = FHIR.backend().request(
                "delete",
                url=url,
                params=params,
                headers=headers,
            )
            content = response.content
            logger.debug(f"PPM/FHIR: HTTP DELETE Response {response.status_code}")

            # Check the response
            response.raise_for_status()

        except requests.HTTPError as e:
            # Attempt to format response (FHIR returns JSON in failed requests)
            try:
                reason = libjson.dumps(response.json(), indent=4)
            except requests.exceptions.JSONDecodeError:
                reason = str(content)
            logger.debug(f"PPM/FHIR: HTTP DELETE response: {reason}")
            logger.exception(
                f"PPM/FHIR: HTTP DELETE request error: {e}",
                extra={
                    "url": url,
                    "params": params,
                    "content": content,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: HTTP DELETE resource error: {e}",
                exc_info=True,
                extra={
                    "url": url,
                    "params": params,
                },
            )
            traceback.print_stack()
            # If fail is set, return None to indicate failure
            if fail:
                return None

        return response

    #
    # FHIR HTTP
    #

    @staticmethod
    def fhir_get(path: list[str], query: dict = None, content: bool = True) -> Union[requests.Response, Optional[dict]]:
        """
        A generic method implementation for an HTTP GET to a Healthlake
        FHIR instance.

        :param path: The additional path components to GET from
        :type path: list[str]
        :param query: The query to include in the URL of the request
        :type query: dict, defaults to None
        :param content: Determines whether to return parsed
        response data or the response itself, defaults to True
        :typ content: bool, optional
        :return: The response content or None if request failed
        :rtype: Union[requests.Response, Optional[dict]]
        """
        logger.debug(f"PPM/FHIR: GET '{path}'")

        # Set the URL
        url = furl(PPM.fhir_url())
        url.path.segments.extend(path)

        # Make the request
        response = FHIR.get(url.url, params=query, fail=True)
        return response if not content else response.json() if response else None

    @staticmethod
    def fhir_post(
        resource: dict, path: list[str] = None, content: bool = True
    ) -> Union[requests.Response, Optional[dict]]:
        """
        A generic method implementation for an HTTP POST to a Healthlake
        FHIR instance.

        :param resource: The FHIR resource to persist
        :type resource: dict
        :param path: The additional path components to POST to
        :type path: list[str], defaults to None
        :param content: Determines whether to return parsed
        response data or the response itself, defaults to True
        :typ content: bool, optional
        :return: The response content or None if request failed
        :rtype: Union[requests.Response, Optional[dict]]
        """
        logger.debug(f"PPM/FHIR: POST {resource['resourceType']}")

        try:
            # Validate the resource
            FHIRElementFactory.instantiate(resource["resourceType"], resource)

        except FHIRValidationError as e:
            logger.exception(
                f"PPM/FHIR: Resource validation error: {e}",
                extra={
                    "resource_type": resource["resourceType"],
                },
            )

            return None

        # Set the URL
        url = furl(PPM.fhir_url())
        if path:
            url.path.segments.extend(path)

        # Make the request
        response = FHIR.post(url.url, json=resource, fail=True)
        return response if not content else response.json() if response else None

    @staticmethod
    def fhir_put(
        resource: dict, path: list[str] = None, content: bool = True
    ) -> Union[requests.Response, Optional[dict]]:
        """
        A generic method implementation for an HTTP PUT to a Healthlake
        FHIR instance.

        :param resource: The FHIR resource to persist
        :type resource: dict
        :param path: The additional path components to PUT to
        :type path: list[str], defaults to None
        :param content: Determines whether to return parsed
        response data or the response itself, defaults to True
        :typ content: bool, optional
        :return: The response content or None if request failed
        :rtype: Union[requests.Response, Optional[dict]]
        """
        logger.debug(f"PPM/FHIR: PUT {resource['resourceType']}")

        try:
            # Validate the resource
            FHIRElementFactory.instantiate(resource["resourceType"], resource)

        except FHIRValidationError as e:
            logger.exception(
                f"PPM/FHIR: Resource validation error: {e}",
                extra={
                    "resource_type": resource["resourceType"],
                },
            )

            return None

        # Set the URL
        url = furl(PPM.fhir_url())
        if path:
            url.path.segments.extend(path)

        # Make the request
        response = FHIR.put(url=url.url, json=resource, fail=True)
        return response if not content else response.json() if response else None

    @staticmethod
    def fhir_patch(path: list[str], patch: dict, content: bool = True) -> Union[requests.Response, Optional[dict]]:
        """
        A generic method implementation for an HTTP PATCH to a FHIR
        instance.

        :param path: The additional path components to DELETE to
        :type path: list[str]
        :param patch: The JSON patch object to pass along with the request
        :type patch: dict
        :param content: Determines whether to return parsed
        response data or the response itself, defaults to True
        :typ content: bool, optional
        :return: The response content or None if request failed
        :rtype: Union[requests.Response, Optional[dict]]
        """
        logger.debug(f"PPM/FHIR: PATCH '{path}'")

        # Set the URL
        url = furl(PPM.fhir_url())
        url.path.segments.extend(path)

        # Set the headers for JSON Patch
        headers = {"Content-Type": "application/json-patch+json"}

        # Make the request
        response = FHIR.patch(url.url, json=patch, headers=headers, fail=True)
        return response if not content else response.json() if response else None

    @staticmethod
    def fhir_delete(path: list[str], content: bool = True) -> Union[requests.Response, Optional[dict]]:
        """
        A generic method implementation for an HTTP DELETE to a Healthlake
        FHIR instance.

        :param path: The additional path components to DELETE to
        :type path: list[str]
        :param content: Determines whether to return parsed
        response data or the response itself, defaults to True
        :typ content: bool, optional
        :return: The response content or None if request failed
        :rtype: Union[requests.Response, Optional[dict]]
        """
        logger.debug(f"PPM/FHIR: DELETE '{path}'")

        # Set the URL
        url = furl(PPM.fhir_url())
        url.path.segments.extend(path)

        # Make the request
        response = FHIR.delete(url.url, fail=True)
        return response if not content else response.json() if response else None

    #
    # FHIR CRUD
    #

    @staticmethod
    def fhir_create(resource_type: str, resource: dict, resource_id: str = None) -> Optional[dict]:
        """
        A generic method implementation for creating a FHIR resource. This
        will replace an existing resource if it is found via the optional
        query.

        :param resource_type: The FHIR resource type
        :type resource_type: str
        :param resource: The FHIR resource to persist
        :type resource: dict
        :param resource_id: The FHIR resource ID to create
        :type resource_id: str, defaults to None
        :return: The response content or None if request failed
        :rtype: Optional[dict]
        """
        logger.debug(f"PPM/FHIR: Create resource: {resource_type}")

        # Create the questionnaire response
        path = [resource_type]
        action = getattr(FHIR, "fhir_put" if resource_id else "fhir_post", None)
        if resource_id:

            # Add QuestionnaireResponse path
            path.append(resource_id)

        # Call the appropriate HTTP method
        return action(resource, path)

    @staticmethod
    def fhir_create_and_get_id(resource: Union[dict, DomainResource]) -> Optional[str]:
        """
        A generic method implementation for creating a FHIR resource. This
        will return the ID of the newly created resource if the operation
        succeeded, otherwise it will return `None`.

        :param resource: The FHIR resource to persist
        :type resource: Union[dict, DomainResource]
        :return: The resource ID or None if request failed
        :rtype: Optional[str]
        """
        # Check type
        if type(resource) is not dict:
            resource = resource.as_json()
        logger.debug(f"PPM/FHIR: Create resource: {resource['resourceType']}")

        # Create the resource
        response = FHIR.fhir_post(resource=resource, path=[resource["resourceType"]], content=False)
        if not response.ok:
            return None

        # Fetch and return ID of the created resource
        return FHIR.get_created_resource_id(response=response, resource_type=resource["resourceType"])

    @staticmethod
    def fhir_create_and_get_ids(
        resources: list[Union[dict, DomainResource]], transaction: bool = False
    ) -> Optional[dict[str, list[str]]]:
        """
        A generic method implementation for creating a set of FHIR resources.
        Caller may dictate the type of bundle transaction to use. Please note
        that the "batch" transaction type may not be used with temporary IDs
        for resources. This will return the IDs of the newly created resources
        if the operation succeeded, otherwise it will return `None`.

        :param resources: The FHIR resources to persist
        :type resources: list[Union[dict, DomainResource]]
        :param transaction: Whether to process as a FHIR bundle transaction,
        defaults to False
        :type transaction: bool, optional
        :raises ValueError: If bundle type "batch" is passed with temporary
        resource IDs
        :return: The dict mapping resource types to a list of created
        resource IDs, defaults to None
        :rtype: Optional[dict[str, list[str]]]
        """
        # Check types
        resources = [FHIRElementFactory.instantiate(r["resourceType"], r) for r in resources if type(r) is dict]
        logger.debug(f"PPM/FHIR: Create resources: {', '.join([r.resource_type for r in resources])}")

        # Create the bundle
        bundle = FHIR.Resources.bundle(resources=resources, bundle_type="transaction" if transaction else "batch")

        # Create the resource
        response = FHIR.fhir_post(resource=bundle.as_json(), content=False)
        if not response.ok:
            return None

        # Fetch and return IDs of the created resource
        return FHIR.get_created_resource_ids(response=response)

    @staticmethod
    def fhir_read(resource_type: str, resource_id: str) -> Optional[dict]:
        """
        A generic method implementation for reading a FHIR resource.

        :param resource_type: The FHIR resource type
        :type resource_type: str
        :param resource_id: The FHIR resource to delete
        :type resource_id: str
        :return: The response content or None if request failed
        :rtype: Optional[dict]
        """
        logger.debug(f"PPM/FHIR: Read resource: {resource_type}/{resource_id}")

        # Check if resource exists
        response = FHIR.fhir_get([resource_type, resource_id])
        if not response:
            logger.debug(f"PPM/FHIR: Resource: {resource_type}/" f"{resource_id} does not exist")

        return response

    @staticmethod
    def fhir_update(resource_type: str, resource_id: str, resource: dict) -> Optional[dict]:
        """
        A generic method implementation for updating a FHIR resource via
        an HTTP PUT.

        :param resource_type: The FHIR resource type
        :type resource_type: str
        :param resource_id: The FHIR resource ID to create
        :type resource_id: str, defaults to None
        :param resource: The FHIR resource to persist
        :type resource: dict
        :return: The response content or None if request failed
        :rtype: Optional[dict]
        """
        logger.debug(f"PPM/FHIR: Update resource: {resource_type}/{resource_id}")

        return FHIR.fhir_put(resource, [resource_type, resource_id])

    @staticmethod
    def fhir_delete_resource(resource_type: str, resource_id: str) -> Optional[dict]:
        """
        A generic method implementation for creating a FHIR resource. This
        will replace an existing resource if it is found via the optional
        query.

        :param resource_type: The FHIR resource type
        :type resource_type: str
        :param resource_id: The FHIR resource to delete
        :type resource_id: str
        :return: The response content or None if request failed
        :rtype: Optional[dict]
        """
        logger.debug(f"PPM/FHIR: Delete resource: {resource_type}/{resource_id}")

        return FHIR.fhir_delete([resource_type, resource_id])

    @staticmethod
    def fhir_transaction(bundle: dict) -> Optional[dict]:
        """
        A generic method implementation for making a FHIR transaction.

        :param bundle: The FHIR Bundle to POST in the transaction
        :type bundle: dict
        :return: The response content or None if request failed
        :rtype: Optional[dict]
        """
        logger.debug("PPM/FHIR: Transaction")

        return FHIR.fhir_post(bundle)

    @staticmethod
    def fhir_search(path: list[str], query: dict = None) -> dict:
        """
        A generic method implementation for an FHIR search.

        :param path: The additional path components to search from
        :type path: list[str]
        :param query: The query to include in the URL of the request
        :type query: dict, defaults to None
        :return: The FHIR Bundle object from the search
        :rtype: dict
        """
        logger.debug(f"PPM/FHIR: Search '{path}'/'{query}'")

        # Set the URL
        url = furl(PPM.fhir_url())
        url.path.segments.extend(path)
        url.path.segments.append("_search")

        # Default to 100 resources
        if not query:
            query = {"_count": "100"}
        elif "_count" not in query:
            query["_count"] = "100"

        # Ensure we iterate all pages
        total_bundle = None
        while url is not None:

            # Make the request
            bundle = FHIR.post(url, data=query, fail=True)
            if not total_bundle:
                total_bundle = bundle
            else:
                total_bundle["entry"].extend(bundle.get("entry", []))

            # Check for a page.
            url = next((link["url"] for link in bundle.get("link", []) if link["relation"] == "next"), None)

            # Swap domain if necessary
            if furl(url).host != furl(PPM.fhir_url()).host:

                # Set it
                url = furl(url).set(host=furl(PPM.fhir_url()).host).url

        # Update count
        total_bundle["total"] = len(total_bundle.get("entry", []))

        return total_bundle

    @classmethod
    def default_url_for_env(cls, environment):
        """
        Give implementing classes an opportunity to list a default set of URLs
        based on the DBMI_ENV, if specified. Otherwise, return nothing
        :param environment: The DBMI_ENV string
        :return: A URL, if any
        """
        if "local" in environment:
            return "http://fhir:8008"
        elif "dev" in environment:
            return "https://fhir.ppm.aws.dbmi-dev.hms.harvard.edu"
        elif "prod" in environment:
            return "https://fhir.ppm.aws.dbmi.hms.harvard.edu"
        else:
            logger.error(f"Could not return a default URL for environment: {environment}")

        return None

    @staticmethod
    def find_resources(
        resource: Union[Resource, BundleEntry, dict, list],
        resource_types: list[str] = None,
        filter: Callable[[dict], bool] = None,
    ) -> list[dict]:
        """
        Accepts a FHIR object container (Bundle, Resource, dict, FHIRResource)
        or a list of the mentioned types and returns a list of FHIR resources
        matching the passed resource types or filter, if passed. Resources
        are filtered by resource type first before they are run through the
        optional filter lambda. Returned FHIR resources are "as JSON" Python
        dicts.

        :param resource: A resource that contains FHIR resources to be filtered
        and returned
        :type resource: Union[Resource, BundleEntry, dict, list]
        :param resource_types: A list of FHIR resource types to filter on
        :type resource_types: list[str]
        :param filter: A lambda method to provide a customized filter on the
        found resources.
        :type filter: Callable[[dict], bool]
        :return: A list of FHIR resources as JSON Python dicts, if any found
        :rtype: list[dict]
        """
        # Check for valid object
        if not resource:
            logger.warning('FHIR: Attempt to extract resource from nothing: "{}"'.format(resource))
            return []

        # Check type
        resources = []
        if isinstance(resource, Resource):

            # Check if in a search bundle
            if type(resource) is Bundle:

                # Get entries
                resources = FHIR.find_resources(
                    resource.entry,
                    resource_types=resource_types,
                    filter=filter,
                )

            else:

                # Object is resource, return it
                resources = [resource.as_json()]

        # Check if is a search bundle entry
        if type(resource) is BundleEntry:

            # Return its resource
            resources = FHIR.find_resources(resource.resource, resource_types=resource_types, filter=filter)

        if type(resource) is list:

            # Get all matching resources
            for r in resource:
                resources.extend(
                    FHIR.find_resources(
                        resource=r,
                        resource_types=resource_types,
                        filter=filter,
                    )
                )

        if type(resource) is dict:

            # Check for bundle
            if resource.get("resourceType") == "Bundle" and resource.get("entry"):

                # Call this with bundle entries
                resources = FHIR.find_resources(
                    resource["entry"],
                    resource_types=resource_types,
                    filter=filter,
                )

            # Check for bundle entry
            elif resource.get("resource") and resource.get("fullUrl"):

                # Call this with resource
                resources = FHIR.find_resources(
                    resource["resource"],
                    resource_types=resource_types,
                    filter=filter,
                )

            elif resource.get("resourceType"):

                # Object is a resource, return it
                resources = [resource]

            elif resource.get("resource") and resource.get("response"):

                # Object is a resource, return it
                resources = [resource["resource"]]

            else:
                logger.warning(
                    "FHIR: Requested resource as FHIRClient Resource but did "
                    "not supply valid Resource subclass to construct with"
                )
                traceback.print_stack()

        # Filter by resource type, if passed
        if resource_types:
            resources = [r for r in resources if r["resourceType"] in resource_types]

        # If a filter is passed, run the list of resources through
        if filter:
            resources = [r for r in resources if filter(r)]

        return resources

    @staticmethod
    def find_resource(
        resource: Union[Resource, BundleEntry, dict, list],
        resource_type: str = None,
        filter: Callable[[dict], bool] = None,
    ) -> Optional[dict]:
        """
        Accepts a FHIR object container (Bundle, Resource, dict, FHIRResource)
        or a list of the mentioned types and returns a FHIR resource
        matching the passed resource types or filter, if passed. Resources
        are filtered by resource type first before they are run through the
        optional filter lambda. Returned FHIR resource is a "as JSON" Python
        dict.

        :param resource: A resource that contains FHIR resources to be filtered
        and returned
        :type resource: Union[Resource, BundleEntry, dict, list]
        :param resource_type: A FHIR resource type to filter on
        :type resource_type: str
        :param filter: A lambda method to provide a customized filter on the
        found resources.
        :type filter: Callable[[dict], bool]
        :raises ValueError: If there are more than one resources found in the
        resource container that match the filters
        :return: A FHIR resource as a JSON Python dict, if found
        :rtype: Optional[dict]
        """
        resources = FHIR.find_resources(
            resource=resource,
            resource_types=[resource_type],
            filter=filter,
        )
        if len(resources) > 1:
            raise ValueError(f"Found '{len(resources)}' resources matching the query")

        return next(iter(resources), None)

    @staticmethod
    def get_resource(
        resource: Union[Resource, BundleEntry, dict, list],
        resource_type: str = None,
        filter: Callable[[dict], bool] = None,
    ) -> dict:
        """
        Accepts a FHIR object container (Bundle, Resource, dict, FHIRResource)
        or a list of the mentioned types and returns a FHIR resource
        matching the passed resource types or filter, if passed. Resources
        are filtered by resource type first before they are run through the
        optional filter lambda. Returned FHIR resource is a "as JSON" Python
        dict. If no matching resource is found, or more than one resource
        if found, an exception is raised.

        :param resource: A resource that contains FHIR resources to be filtered
        and returned
        :type resource: Union[Resource, BundleEntry, dict, list]
        :param resource_type: A FHIR resource type to filter on
        :type resource_type: str
        :param filter: A lambda method to provide a customized filter on the
        found resources.
        :type filter: Callable[[dict], bool]
        :raises ValueError: If no resource is found matching the passed
        resource type and filter
        :raises ValueError: If there are more than one resources found that
        match the resource type and filter
        :return: A FHIR resource as a JSON Python dict, if found
        :rtype: dict
        """
        resource = FHIR.find_resource(
            resource=resource,
            resource_type=resource_type,
            filter=filter,
        )
        if not resource:
            raise ValueError("Could not find resource matching the query")

        return resource

    @staticmethod
    def _find_resources(obj, resource_type=None):
        """
        Accepts an arbitrary FHIR object (Bundle, Resource, dict, FHIRResource)
        and returns either the FHIRResources or the immediate resource dicts
        matching the resource type
        :param obj: A bundle or list or resource as a dict or FHIRResource
        :param resource_type: If multiple resources exist, only return these types
        :return: list
        """
        # Check for valid object
        if not obj:
            logger.warning('FHIR: Attempt to extract resource from nothing: "{}"'.format(obj))
            return []

        # Check type
        if isinstance(obj, Resource):

            # Check if in a search bundle
            if type(obj) is Bundle:

                # Get entries
                return FHIR._find_resources(obj.entry, resource_type=resource_type)

            else:

                # Object is resource, return it
                return [obj.as_json()] if not resource_type or obj.resource_type == resource_type else []

        # Check if is a search bundle entry
        if type(obj) is BundleEntry:

            # Return its resource
            return FHIR._find_resources(obj.resource, resource_type=resource_type)

        if type(obj) is list:

            # Get all matching resources
            resources = []
            for r in obj:
                resources.extend(FHIR._find_resources(r, resource_type=resource_type))

            return resources

        if type(obj) is dict:

            # Check for bundle
            if obj.get("resourceType") == "Bundle" and obj.get("entry"):

                # Call this with bundle entries
                return FHIR._find_resources(obj["entry"], resource_type=resource_type)

            # Check for bundle entry
            elif obj.get("resource") and obj.get("fullUrl"):

                # Call this with resource
                return FHIR._find_resources(obj["resource"], resource_type=resource_type)

            elif obj.get("resourceType"):

                # Object is a resource, return it
                return [obj] if not resource_type or obj["resourceType"] == resource_type else []

            elif obj.get("resource") and obj.get("response"):

                # Object is a resource, return it
                return (
                    [obj["resource"]] if not resource_type or obj["resource"]["resourceType"] == resource_type else []
                )

            else:
                logger.warning(
                    "FHIR: Requested resource as FHIRClient Resource but did "
                    " not supply valid Resource subclass to construct with"
                )
                traceback.print_stack()

        return []

    @staticmethod
    def _find_resource(obj, resource_type=None):
        """
        Accepts an arbitrary FHIR object (Bundle, Resource, dict, FHIRResource)
        and returns either the first resource found of said type
        :param obj: A bundle or list or resource as a dict or FHIRResource
        :param resource_type: The resource type we are looking for
        :return: object
        """
        return next(iter(FHIR._find_resources(obj, resource_type)), None)

    @staticmethod
    def _get_or(item, keys, default=""):
        """
        Fetch a property from a json object. Keys is a list of keys and indices
        to use to fetch the property. Returns the passed default string if the
        path through the json does not exist.
        :param item: The json to parse properties from
        :type item: json object
        :param keys: The list of keys and indices for the property
        :type keys: A list of string or int
        :param default: The default string to use if a property could not be found
        :type default: String
        :return: The requested property or the default value if missing
        :rtype: String
        """
        try:
            # Try it out.
            for key in keys:
                item = item[key]

            return item
        except (KeyError, IndexError):
            return default

    @staticmethod
    def _get_referenced_id(resource: dict, resource_type: str, key=None):
        """
        Checks a resource JSON and returns any ID reference for the given resource
        type. If 'key' is passed, that will be forced, if anything is present or not.
        :param resource: The resource JSON to check
        :type resource: dict
        :param resource_type: The type of the referenced resource
        :type resource_type: str
        :param key: The resource key to check for the reference
        :type key: str
        :return: The requested referenced resources ID or None
        :rtype: str
        """
        try:
            # Try it out.
            if key and resource.get(key, {}).get("reference"):
                return resource[key]["reference"].replace(f"{resource_type}/", "")

            else:
                # Find it
                for key, value in resource.items():
                    if type(value) is dict and value.get("reference") and resource_type in value.get("reference"):
                        return value["reference"].replace(f"{resource_type}/", "")

        except (KeyError, IndexError) as e:
            logger.exception(
                "FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "resource_type": resource_type,
                    "key": key,
                },
            )

        else:
            logger.warning(f'FHIR Error: No reference found for "{resource_type}"')

        return None

    @staticmethod
    def _get_list(bundle: Bundle, resource_type: str) -> Optional[FHIRList]:
        """
        Finds and returns the list resource for the passed resource type
        :param bundle: The FHIR resource bundle
        :type bundle: Bundle
        :param resource_type: The resource type of the list's contained resources
        :type resource_type: str
        :return: The List resource if exists
        :rtype: List, defaults to None
        """

        # Check the bundle type
        if type(bundle) is dict:
            bundle = Bundle(bundle)

        # Quit early for an empty bundle
        if not bundle.entry:
            return None

        for list in [entry.resource for entry in bundle.entry if entry.resource.resource_type == "List"]:

            # Compare the type
            for item in [entry.item for entry in list.entry]:

                # Check for a reference
                if item.reference and resource_type == item.reference.split("/")[0]:

                    return list

        return None

    @staticmethod
    def is_ppm_research_subject(research_subject: dict) -> bool:
        """
        Accepts a FHIR ResearchSubject resource and returns whether it's
        related to a PPM study or not

        :param research_subject: The ResearchSubject object
        :type research_subject: dict
        :returns: Whether or not this ResearchSubject is for a PPM study
        :rtype: bool
        """
        return next(
            (
                i
                for i in research_subject.get("identifier", [])
                if i["system"] == FHIR.research_subject_study_identifier_system
            ),
            False,
        ) and next((i for i in research_subject.get("identifier", []) if i["value"] in PPM.Study.identifiers()), False)

    @staticmethod
    def get_study_from_research_subject(research_subject: dict | ResearchSubject) -> Optional[str]:
        """
        Accepts a FHIR resource representation (ResearchSubject, dict or bundle entry)
        and parses out the identifier which contains the code of the study this
        belongs too.

        :param research_subject: The ResearchSubject resource
        :type research_subject: object
        :return: The study or None
        :rtype: str
        """

        # Check type and convert the JSON resource
        if type(research_subject) is ResearchSubject:
            research_subject = research_subject.as_json()
        elif type(research_subject) is dict and research_subject.get("resource"):
            research_subject = research_subject.get("resource")
        elif type(research_subject) is not dict or research_subject.get("resourceType") != "ResearchSubject":
            raise ValueError("Passed ResearchSubject is not a valid resource: {}".format(research_subject))

        # Parse the identifier
        identifier = next(
            (
                i["value"]
                for i in research_subject.get("identifier", [])
                if i["system"] == FHIR.research_subject_study_identifier_system
            ),
            None,
        )
        if identifier:

            # Split off the 'ppm-' prefix if needed
            if PPM.Study.is_ppm(identifier):
                return PPM.Study.get(identifier).value

            else:
                return identifier

        return None

    @staticmethod
    def _format_date(date_string: str, date_format: str) -> str:
        """
        Accepts a date string and converts the timezone to US/Eastern
        and then returns the date as formatted string per the `date_format`
        argument.

        :param date_string: The original date string
        :type date_string: str
        :param date_format: The format to return date as
        :type date_format: str
        :returns: A date formatted as string in US/Eastern timezone
        :rtype: str
        """
        try:
            # Parse it
            date = parse(date_string)

            # Set UTC as timezone
            from_zone = tz.gettz("UTC")
            to_zone = tz.gettz("America/New_York")
            utc = date.replace(tzinfo=from_zone)

            # If UTC time was 00:00:00, assume a time was missing and
            # return the date as is so
            # the ET conversion does not change the date.
            if utc.hour == 0 and utc.minute == 0 and utc.second == 0:
                return utc.strftime(date_format)

            # Convert time zone to assumed ET
            et = utc.astimezone(to_zone)

            # Format it and return it
            return et.strftime(date_format)

        except ValueError as e:
            logger.exception(
                "FHIR date parsing error: {}".format(e),
                exc_info=True,
                extra={"date_string": date_string, "date_format": date_format},
            )

            return "--/--/----"

    @staticmethod
    def find_patient_identifier(patient: Union[Patient, dict, str], strict: bool = False, lookup: bool = False) -> str:
        """
        Finds and returns the FHIR ID of the Patient resource given the
        passed patient object or identifier. This is meant to allow methods
        to accept various objects for a patient query but to get the actual
        FHIR ID when that is needed. If 'strict' is True, this method will
        throw an exception of the FHIR ID cannot be determined such as when
        an email is passed for the 'patient' argument. If 'strict' is True
        and 'lookup' is True then the FHIR ID will be determined via a query
        to FHIR, if necessary.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param strict: Only allow returning of the Patient's FHIR ID
        :type strict: bool, defaults to False
        :param lookup: Allow this method to do a lookup for FHIR ID if not
        immediately available
        :type lookup: bool, defaults to False
        :raises ValueError: If an email address is passed as 'patient'
        :raises ValueError: If the FHIR ID of the Patient cannot be determined
        :return: The FHIR ID or email of the Patient resource
        :rtype: str
        """
        # Check types
        if type(patient) is str and re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\d]{4,}$", patient
        ):
            return patient

        # Check for an email address
        elif type(patient) is str and re.match(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", patient):
            if strict and lookup:
                # Return Patient ID from query
                return FHIR.query_patient_id(email=patient)
            elif strict:
                raise ValueError("Email cannot be used to determine FHIR ID of Patient without lookup")

            # Return it
            return patient

        # Check for a resource
        elif type(patient) is dict and patient.get("resourceType") == "Patient":
            return patient["id"]

        # Check for a bundle entry
        elif type(patient) is dict and patient.get("resource", {}).get("resourceType") == "Patient":
            return patient["resource"]["id"]

        # Check for a Patient object
        elif type(patient) is Patient:
            return patient.id

        # Default to raise an exception for unhandled argument
        raise ValueError(f"Unhandled instance for patient: {type(patient)}: {patient}")

    @staticmethod
    def _patient_query(patient: Union[Patient, dict, str]):
        """
        Accepts an identifier and builds the query for resources related to that
        Patient. Identifier can be a FHIR ID, an email address, or a Patient object.
        Optionally specify the parameter key to be used, defaults to 'patient'.

        :param patient: The Patient object to build query from
        :type patient: Patient | dict | str
        :return: A query as a dictionary for the Patient
        :rtype: dict
        """
        # Check types
        if type(patient) is str and re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\d]+$", patient
        ):

            # Likely a FHIR ID
            return {"_id": patient}

        # Check for an email address
        elif type(patient) is str and re.match(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", patient):

            # An email address
            return {"identifier": "{}|{}".format(FHIR.patient_email_identifier_system, patient)}

        # Check for a resource
        elif type(patient) is dict and patient.get("resourceType") == "Patient":

            return {"_id": patient["id"]}

        # Check for a bundle entry
        elif type(patient) is dict and patient.get("resource", {}).get("resourceType") == "Patient":

            return {"_id": patient["resource"]["id"]}

        # Check for a Patient object
        elif type(patient) is Patient:

            return {"_id": patient.id}

        else:
            raise ValueError("Unhandled instance of a Patient identifier: {}".format(patient))

    @staticmethod
    def _patient_resource_query(patient: Union[Patient, dict, str], key: str = "patient") -> dict:
        """
        Accepts an identifier and builds the query for resources related to that
         Patient. Identifier can be a FHIR ID, an email address, or a Patient object.
         Optionally specify the parameter key to be used, defaults to 'patient'.

        :param patient: The Patient object to build query from
        :type patient: Patient | dict | str
        :return: A query as a dictionary for the Patient-related resource
        :rtype: dict
        """
        # Check types
        if type(patient) is str and re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[\d]+$", patient
        ):

            # Likely a FHIR ID
            return {key: patient}

        # Check for an email address
        elif type(patient) is str and re.match(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", patient):

            # An email address
            return {"{}:Patient.identifier".format(key): "{}|{}".format(FHIR.patient_email_identifier_system, patient)}

        # Check for a resource
        elif type(patient) is dict and patient.get("resourceType") == "Patient":

            return {key: patient["id"]}

        # Check for a bundle entry
        elif type(patient) is dict and patient.get("resource", {}).get("resourceType") == "Patient":

            return {key: patient["resource"]["id"]}

        # Check for a Patient object
        elif type(patient) is Patient:

            return {key: patient.id}

        else:
            raise ValueError("Unhandled instance of a Patient identifier: {}".format(patient))

    @staticmethod
    def get_created_resource_id(response: requests.Response, resource_type: str) -> Optional[str]:
        """
        Accepts a response from a FHIR operation to create a resource and returns
        the ID and URL of the newly created resource in FHIR
        :param response: The raw HTTP response object from FHIR
        :type response: requests.Response
        :param resource_type: The resource type of the created resource
        :type resource_type: str
        :returns: The ID of the created resource, defaults to None
        :rtype: str, optional
        """
        # Check status
        if not response.ok:
            logger.error(
                "FHIR Error: Cannot get resource details from a failed response: "
                f"{response.status_code} : {response.content.decode()}"
            )
            return None

        url = None
        try:
            # Get the URL from headers
            url = furl(response.headers.get("Location"))
            logger.debug(f"PPM/FHIR: Extracting created resource ID from: {url}")

            # Get ID of resource (UUID in FHIR R4)
            pattern = r"^(?:.*\/)?([A-Za-z]+)\/([^/]+)(?:\/_history\/[a-zA-Z0-9]+)?$"
            resource_id = re.search(pattern, url.url)[2]

            # Return
            logger.debug(f"PPM/FHIR: Created resource '{resource_type}/{resource_id}'")
            return resource_id

        except Exception as e:
            logger.exception(
                f"FHIR Error: {e}",
                exc_info=True,
                extra={
                    "response": response.content.decode(),
                    "headers": response.headers,
                    "status": response.status_code,
                    "url": url,
                },
            )

        # Iterate results
        resource_ids = {}
        for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
            logging.debug(f"FHIR result: {result}")

            # Get the location
            location = result.get("location")
            if not location:
                logger.warning(f"PPM/FHIR: Could not parse result: {result}")
                continue

            # Get the resource type and ID
            pattern = r"^(?:.*\/)?([A-Za-z]+)\/([^/]+)(?:\/_history\/[a-zA-Z0-9]+)?$"
            resource_details = re.search(pattern, location, re.IGNORECASE)

            # Add it to the dict
            resource_ids.setdefault(resource_details.group(1), []).append(resource_details.group(2))

        # Return the first group
        if resource_ids:
            return next(iter(resource_ids[resource_type]))

        # Could not figure it out
        logger.error(f"FHIR ERROR: Could not determine resource ID from response: {response.content.decode()}")
        return None

    def get_created_resource_ids(response: requests.Response) -> Optional[dict[str, list[str]]]:

        # Check status
        if not response.ok:
            logger.error(
                "FHIR Error: Cannot get resource details from a failed response: "
                f"{response.status_code} : {response.content.decode()}"
            )
            return None

        # Iterate results
        resource_ids = {}
        for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
            logging.debug(f"FHIR result: {result}")

            # Get the location
            location = result.get("location")
            if not location:
                logger.warning(f"PPM/FHIR: Could not parse result: {result}")
                continue

            # Get the resource type and ID
            pattern = r"^(?:.*\/)?([A-Za-z]+)\/([^/]+)(?:\/_history\/[a-zA-Z0-9]+)?$"
            resource_details = re.search(pattern, location, re.IGNORECASE)

            # Add it to the dict
            resource_ids.setdefault(resource_details.group(1), []).append(resource_details.group(2))

        return resource_ids

    #
    # SAVE
    #

    @staticmethod
    def save_questionnaire_response(
        patient_id: str, questionnaire_id: str, questionnaire_response: dict, replace: bool = False
    ) -> Optional[dict]:
        """
        Persist the QuestionnaireResponse to FHIR. If replace is set to true,
        an existing QuestionnaireResponse for this Questionnaire and Patient
        is deleted.

        :param patient_id: The Patient ID for the QuestionnaireResponse
        :type patient_id: str
        :param questionnaire_id: The ID of the Questionnaire this is related to
        :type questionnaire_id: str
        :param questionnaire_response: The QuestionnaireResponse resource
        :type questionnaire_response: dict
        :param replace: Whether to replace existing response or not, defaults to True
        :type replace: bool, defaults to False
        :return: The response object for the operation
        :rtype: dict, defaults to None
        """
        logger.debug(
            "Create QuestionnaireResponse: {}".format(questionnaire_response["questionnaire"].rsplit("/", 1)[-1])
        )

        # Validate it.
        bundle = Bundle()
        bundle.entry = []
        bundle.type = "transaction"

        # If replace, request prior response be deleted
        if replace:

            # Check for it
            existing_questionnaire_responses = FHIR.query_questionnaire_responses(patient_id, questionnaire_id)
            for q in existing_questionnaire_responses.entry:

                delete_questionnaire_response_entry = BundleEntry()
                delete_questionnaire_response_request = BundleEntryRequest(
                    {
                        "url": f"QuestionnaireResponse/{q.resource.id}",
                        "method": "DELETE",
                    }
                )

                # Set it
                delete_questionnaire_response_entry.request = delete_questionnaire_response_request

                # Add it
                bundle.entry.append(delete_questionnaire_response_request)

        # Create the organization
        questionnaire_response = QuestionnaireResponse(questionnaire_response)
        questionnaire_response_request = BundleEntryRequest(
            {
                "url": "QuestionnaireResponse",
                "method": "POST",
            }
        )

        questionnaire_response_entry = BundleEntry({"resource": questionnaire_response.as_json()})

        questionnaire_response_entry.request = questionnaire_response_request

        # Add it
        bundle.entry.append(questionnaire_response_entry)

        logger.debug(f"PPM/{patient_id}: Saving QuestionnaireResponse for " f"Questionnaire/{questionnaire_id}")

        try:
            # Create the organization
            response = FHIR.post(PPM.fhir_url(), json=bundle.as_json())
            response.raise_for_status()

            # Log the results of each request
            for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
                logging.debug(f"FHIR result: {result}")

            return response.json()

        except Exception as e:
            logger.exception(
                "Save QuestionnaireResponse error: {}".format(e),
                exc_info=True,
                extra={
                    "ppm_id": patient_id,
                    "questionnaire": questionnaire_id,
                },
            )

        return None

    #
    # CREATE
    #

    @staticmethod
    def create_ppm_research_study(study: str, title: str, start: datetime = None, end: datetime = None) -> bool:
        """
        Creates the research study resource in FHIR for the given PPM study
        details.

        :param study: The PPM study code
        :type study: str
        :param title: The title of the PPM study
        :type title: str
        :param start: The start date of the study, defaults to None
        :type start: datetime, optional
        :param end: The end date of the study, defaults to None
        :type end: datetime, optional
        :raises FHIRValidationError: If the resource fails FHIR validation
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Create the resource
        resource = FHIR.Resources.research_study(title, ppm_study=study, start=start, end=end)

        # Make the PUT request
        success = FHIR.fhir_put(resource=resource, path=["ResearchStudy", resource["id"]])

        if success:
            logger.debug(f"PPM/FHIR: Created/updated ResearchStudy/{resource['id']}")

        return success

    @staticmethod
    def create_ppm_device(
        patient_id: str,
        study: str,
        code: str,
        display: str,
        title: str,
        identifier: str,
        shipped: Optional[str] = None,
        returned: Optional[str] = None,
        note: Optional[str] = None,
        tracking: Optional[str] = None,
    ) -> bool:
        """
        Creates a Device resource utilized by PPM to track the various physical
        items that need to be delivered to participants for data collection
        and other study-related processes.

        :param patient_id: The ID of the Patient this device is related to
        :type patient_id: str
        :param study: The ID of the PPM study this device is related to
        :type study: str
        :param code: The code to use for the device
        :type code: str
        :param display: The display item of the code
        :type display: str
        :param title: The title of the device
        :type title: str
        :param identifier: The unique identifier for the device
        :type identifier: str
        :param shipped: When the device was shipped, defaults to None
        :type shipped: Optional, optional
        :param returned: When the device was returned, defaults to None
        :type returned: Optional, optional
        :param note: An optional note for the device, defaults to None
        :type note: Optional, optional
        :param tracking: An optional tracking number, defaults to None
        :type tracking: Optional, optional
        :raises FHIRValidationError: If the resource fails FHIR validation
        :return: Whether or not the Device resource was created
        :rtype: bool
        """
        device_data = FHIR.Resources.ppm_device(
            patient_ref="Patient/{}".format(patient_id),
            study=study,
            code=code,
            display=display,
            title=title,
            identifier=identifier,
            shipped=shipped,
            returned=returned,
            note=note,
            tracking=tracking,
        )

        device_request = BundleEntryRequest(
            {
                "url": "Device",
                "method": "POST",
            }
        )
        device_entry = BundleEntry(
            {
                "resource": device_data,
            }
        )
        device_entry.request = device_request

        # Validate it.
        bundle = Bundle()
        bundle.entry = [device_entry]
        bundle.type = "transaction"

        # Create the Device on the FHIR server.
        logger.debug("Creating Device via Transaction")
        response = FHIR.post(PPM.fhir_url(), json=bundle.as_json())

        # Parse out created identifiers
        for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
            logging.debug(f"FHIR result: {result}")

        return response.ok

    @staticmethod
    def query_patient_research_subjects(
        patient: Union[Patient, dict, str], ppm_study: str
    ) -> tuple[Optional[dict], Optional[dict]]:
        """
        Find and return a Patient and ResearchStudy set for the given
        parameters.

        :param patient: The identifier of the patient to query for
        :type patient: Union[Patient, dict, str]
        :param ppm_study: The identifier of the PPM study
        :type ppm_study: str
        :returns: The Patient and ResearchSubjects, if found
        :rtype: (dict, dict)
        """
        # Setup query for Patient
        query = FHIR._patient_query(patient)

        # Include all ResearchSubject resources
        query["_revinclude"] = [
            "ResearchSubject:individual",
        ]

        # Get the resources
        resources = FHIR._query_resources("Patient", query=query)

        # Extract resources
        patient = FHIR._find_resource(resources, "Patient")
        research_subjects = FHIR._find_resources(resources, "ResearchSubject")

        # Match PPM research subject
        research_subject = next(
            (r for r in research_subjects if r.get("study", {}).get("reference") == f"ResearchStudy/{ppm_study}"), None
        )

        return patient, research_subject

    @staticmethod
    def study_participant_identifier_system(ppm_study: str) -> str:
        """
        Returns the system to use for participant identifiers for the passed
        study.

        :param ppm_study: The identifier of the study
        :type ppm_study: str
        :return: The study participant identifier
        :rtype: str
        """
        system = furl(FHIR.study_participant_identifier_system_base)

        # Get path components
        path = list(system.path.segments)

        # We don't want the "ppm-" prefix
        study = PPM.Study.get(ppm_study).value

        # Insert study identifier after "study"
        path.insert(path.index("study") + 1, study)

        # Set new path and return
        system.set(path=path)

        return system.url

    @staticmethod
    def get_last_participant_id(ppm_study: str = None) -> str:
        """
        Gets the last Patient created and fetches their PPM ID. If a study is
        passed, the last Patient for that study is returned.
        """
        # Build the query and fetch the patient
        query = {"_count": 1, "_sort": "-_lastUpdated"}
        patient = next(iter(FHIR.fhir_get(path=["Patient"], query=query)["entry"]))["resource"]

        # Set regex to match study participant identifier system
        pattern = r"https://peoplepoweredmedicine.org/study/[a-zA-z0-9-_]+/participant"

        # Get study ID
        ppm_id = next(i["value"] for i in patient["identifier"] if re.match(pattern, i["system"]))

        return ppm_id

    @staticmethod
    def create_patient(
        ppm_study: str,
        email: str,
        first_name: str,
        last_name: str,
        addresses: list[str],
        city: str,
        state: str,
        zip: str,
        phone: str = None,
        contact_email: str = None,
        how_heard_about_ppm: str = None,
        ppm_id: str = None,
    ) -> Optional[tuple[str, str, str]]:
        """
        Creates the core resources necessary for a participant in PPM. Resources
        include a Patient, a Flag and a ResearchSubject. The flag tracks
        enrollment state for the specific study and the research subject
        resource includes a participant in a specific PPM study.

        :param ppm_study: The identifier of the study for which the enrollment was for
        :type ppm_study: str
        :param email: The email of the participant
        :type email: str
        :param first_name: The first name of the participant
        :type first_name: str
        :param last_name: The last name of the participant
        :type last_name: str
        :param addresses: The list of street address strings for the
        participant
        :type addresses: list[str]
        :param city: The participants address city
        :type city: str
        :param state: The participants address state
        :type state: str
        :param zip: The participants address zip
        :type zip: str
        :param phone: The participants phone number, defaults to None
        :type phone: str, optional
        :param contact_email: The participants alternative contact email,
        defaults to None
        :type contact_email: str, optional
        :param how_heard_about_ppm: How the participant heard about PPM,
        defaults to None
        :param ppm_id: Used to specify a specific ID to use for the Patient
        resource
        :type ppm_id: str
        :type how_heard_about_ppm: str, optional
        :raises FHIRValidationError: If the resource fails FHIR validation
        :raises Exception: if resource creation request fails.
        :return: A tuple of the created resource IDs
        :rtype: Optional[tuple[str, str, str]], defaults to None
        """
        try:
            # Set logging prefix
            prefix = f"PPM/FHIR/{ppm_study}"

            # Get the study's FHIR ID
            ppm_study_id = PPM.Study.fhir_id(ppm_study)

            # Check for existing patient and research subject
            # TODO: This seems unecessary, investigate
            patient, research_subject = FHIR.query_patient_research_subjects(email, ppm_study_id)

            # Return if ResearchSubject already exists
            if research_subject:
                logger.warning(f"{prefix}: ResearchSubject already exists for '{email}'")
                return None

            # Flag if Patient exists or not
            patient_exists = patient is not None

            # Build transaction
            bundle = Bundle()
            bundle.entry = []
            bundle.type = "transaction"

            # Create a list to track resources to create
            resources = []

            # Get or set the Patient identifier
            patient_id = patient.get("id") if patient else ppm_id if ppm_id else uuid.uuid1().urn

            # Participant identifier should be unique between studies
            last_participant_id = FHIR.get_last_participant_id()

            # Increment
            participant_id = str(int(last_participant_id) + 1)

            # Check for a patient
            if not patient:

                # Build out patient JSON
                patient_data = FHIR.Resources.patient(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    addresses=addresses,
                    city=city,
                    state=state,
                    zip=zip,
                    phone=phone,
                    contact_email=contact_email,
                    how_heard_about_ppm=how_heard_about_ppm,
                )

                # Add the UUID identifier
                patient_data.setdefault("identifier", []).append(
                    {"system": FHIR.patient_identifier_system, "value": patient_id.replace("urn:uuid:", "")}
                )

                # Add the participant identifier
                patient_data.setdefault("identifier", []).append(
                    {"system": FHIR.study_participant_identifier_system(ppm_study), "value": participant_id}
                )

                # Set the temporary ID
                patient_data["id"] = patient_id

                # Add it to the bundle
                resources.append(patient_data)
                logger.info(f"{prefix}: Will create Patient for '{email}'")

            else:
                # Get or set the Patient identifier
                patient_id = patient.get("id")
                logger.info(f"{prefix}/{patient_id}: Patient for '{email}' already exists")

                # Set logging prefix for existing patient
                prefix = f"PPM/FHIR/{ppm_study}/{patient_id}"

            # Build enrollment flag.
            flag = FHIR.Resources.enrollment_flag(
                patient_ref=patient_id,
                study=ppm_study_id,
                status=PPM.Enrollment.Registered.value,
            )

            # Add the participant identifier
            flag.setdefault("identifier", []).append(
                {"system": FHIR.study_participant_identifier_system_base, "value": participant_id}
            )

            # Add it to the bundle
            resources.append(flag)

            # Build research subject
            research_subject = FHIR.Resources.research_subject(
                patient_ref=patient_id,
                research_study_ref=f"ResearchStudy/{PPM.Study.fhir_id(ppm_study_id)}",
                status="candidate",
            )

            # Add the participant identifier
            research_subject.setdefault("identifier", []).append(
                {"system": FHIR.study_participant_identifier_system_base, "value": participant_id}
            )

            # Add it to the bundle
            resources.append(research_subject)

            # Create the resources on the FHIR server.
            logger.debug(f"{prefix}: Creating {', '.join([r['resourceType'] for r in resources])}")
            resource_ids = FHIR.fhir_create_and_get_ids(resources, transaction=True)

            # Get specific resource IDs
            research_subject_id = next(iter(resource_ids.get("ResearchSubject", [])))
            flag_id = next(iter(resource_ids.get("Flag", [])))

            # Check if Patient created
            if not patient_exists:
                patient_id = next(iter(resource_ids.get("Patient", [])))

            # Log create resources
            logger.debug(f"{prefix}: Created {resource_ids}")

            return patient_id, flag_id, research_subject_id

        except Exception as e:
            logger.exception(e)
            raise

    @staticmethod
    def create_communication(patient_id, content, identifier):
        """
        Create a record of a communication to a participant

        # TODO: Check whether this method is utilized or not

        :param patient_id:
        :param content: The content of the email
        :param identifier: The identifier of the communication
        :return:
        """
        warnings.warn("PPM/FHIR: The method `create_communication` is deprecated", DeprecationWarning, stacklevel=2)
        logger.debug("Patient: {}".format(patient_id))

        # Use the FHIR client lib to validate our resource.
        communication = Communication(
            FHIR.Resources.communication(
                patient_ref="Patient/{}".format(patient_id),
                identifier=identifier,
                content=content,
                sent=datetime.now(timezone.utc).isoformat(),
            )
        )

        # Build the FHIR Communication destination URL.
        url = furl(PPM.fhir_url())
        url.path.segments.append("Communication")

        logger.debug("Creating communication at: {}".format(url.url))

        response = FHIR.post(url.url, json=communication.as_json())
        logger.debug("Response: {}".format(response.status_code))

        return response

    @staticmethod
    def create_research_studies(patient_id: str, research_study_titles: list[str]) -> bool:
        """
        Creates a set of ResearchStudy objects given the list of names to use
        for them and relates them to the Patient via ResearchSubject resources.

        :param patient_id: The identifier of the Patient
        :type patient_id: str
        :param research_study_titles: The list of study titles
        :type research_study_titles: [str]
        :return: Whether the resources were created or not
        :rtype: bool
        """
        logger.debug("Create ResearchStudy objects: {}".format(research_study_titles))

        # Collect entries for bundle
        entries = []

        # Iterate study titles
        for research_study_title in research_study_titles:

            # Create temp identifier for the study
            research_study_id = uuid.uuid1().urn

            # Create the organization
            research_study = ResearchStudy()
            research_study.title = research_study_title
            research_study.status = "completed"

            research_study_request = BundleEntryRequest(
                {
                    "url": "ResearchStudy",
                    "method": "POST",
                }
            )

            research_study_entry = BundleEntry({"resource": research_study.as_json(), "fullUrl": research_study_id})

            research_study_entry.request = research_study_request

            research_study_reference = FHIRReference()
            research_study_reference.reference = research_study_id

            patient_reference = FHIRReference()
            patient_reference.reference = "Patient/{}".format(patient_id)

            # Create the subject
            research_subject = ResearchSubject()
            research_subject.study = research_study_reference
            research_subject.individual = patient_reference
            research_subject.status = "off-study"

            # Add Research Subject to bundle.
            research_subject_request = BundleEntryRequest()
            research_subject_request.method = "POST"
            research_subject_request.url = "ResearchSubject"

            # Create the Research Subject entry
            research_subject_entry = BundleEntry({"resource": research_subject.as_json()})
            research_subject_entry.request = research_subject_request

            # Add them to entries
            entries.extend([research_study_entry, research_subject_entry])

        # Validate it.
        bundle = Bundle()
        bundle.entry = entries
        bundle.type = "transaction"

        try:
            # Create the organization
            response = FHIR.post(PPM.fhir_url(), json=bundle.as_json())
            response.raise_for_status()

            # Parse out created identifiers
            for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
                logging.debug(f"FHIR result: {result}")

            return response.ok

        except Exception as e:
            logger.exception(
                "Create ResearchStudy error: {}".format(e),
                exc_info=True,
                extra={
                    "ppm_id": patient_id,
                    "research_study_title": research_study_title,
                },
            )

        return False

    @staticmethod
    def create_point_of_care_list(patient_id: str, point_of_care_list: list[str]) -> bool:
        """
        Creates a List resource containing a set of Organization resources
        named after the points of care named in the provided list.

        :param patient_id: The Patient to link the List to
        :type patient_id: str
        :param point_of_care_list: The list of point of care names
        :type point_of_care_list: list[str]
        :return: Whether the resources were created or not
        :rtype: bool
        """

        # This is a FHIR resources that allows references between resources.
        # Create one for referencing patients.
        patient_reference = FHIRReference()
        patient_reference.reference = "Patient/" + patient_id

        # The list will hold Organization resources representing where patients
        # have received care.
        data_list = FHIRList()
        data_list_identifier = Identifier()
        data_list_identifier.system = FHIR.points_of_care_list_identifier_system
        data_list_identifier.value = patient_id
        data_list.identifier = [data_list_identifier]
        data_list.subject = patient_reference
        data_list.status = "current"
        data_list.mode = "working"

        # We use the SNOMED code for location to define the context of items added
        # to the list.
        coding = Coding()
        coding.system = FHIR.SNOMED_VERSION_URI
        coding.code = FHIR.SNOMED_LOCATION_CODE

        codeable = CodeableConcept()
        codeable.coding = [coding]

        # Add it
        data_list.code = codeable

        # Start building the bundle. Bundles are used to submit multiple related
        # resources.
        bundle_entries = []

        # Add Organization objects to bundle.
        list_entries = []
        for point_of_care in point_of_care_list:

            # Create the organization
            organization = Organization()
            organization.name = point_of_care
            organization_identifier = Identifier()
            organization_identifier.system = FHIR.organization_identifier_system
            organization_identifier.value = point_of_care
            organization.identifier = [organization_identifier]
            organization_id = uuid.uuid1().urn

            bundle_item_org_request = BundleEntryRequest()
            bundle_item_org_request.method = "POST"
            bundle_item_org_request.url = "Organization"

            bundle_item_org = BundleEntry()
            bundle_item_org.resource = organization
            bundle_item_org.fullUrl = organization_id
            bundle_item_org.request = bundle_item_org_request

            bundle_entries.append(bundle_item_org)

            # Set the reference
            reference = FHIRReference()
            reference.reference = organization_id

            # Add it
            list_entry = ListEntry()
            list_entry.item = reference
            list_entries.append(list_entry)

        # Set it on the list
        data_list.entry = list_entries

        bundle_item_list_request = BundleEntryRequest()
        bundle_item_list_request.url = "List"
        bundle_item_list_request.method = "POST"
        bundle_item_list_request.ifNoneExist = str(
            Query(
                {
                    "identifier": f"{FHIR.points_of_care_list_identifier_system}|{patient_id}",
                }
            )
        )

        bundle_item_list = BundleEntry()
        bundle_item_list.resource = data_list
        bundle_item_list.request = bundle_item_list_request

        bundle_entries.append(bundle_item_list)

        # Create and send the full bundle.
        full_bundle = Bundle()
        full_bundle.entry = bundle_entries
        full_bundle.type = "transaction"

        response = FHIR.post(url=PPM.fhir_url(), json=full_bundle.as_json())

        # Parse out created identifiers
        for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
            logging.debug(f"FHIR result: {result}")

        return response.ok

    @staticmethod
    def create_consent_document_reference(
        study: str,
        ppm_id: str,
        filename: str,
        url: str,
        hash: str,
        size: int,
        composition: dict,
        identifiers: Optional[list[dict]] = None,
    ) -> bool:
        """
        Accepts details and rendering of a signed PPM consent and saves that data as a
        DocumentReference to the participant's FHIR record as well as includes a
        reference to the DocumentReference in the
        participant's consent Composition resource.
        :param study: The PPM study for which this consent was signed
        :type study: str
        :param ppm_id: The Patient object who owns the consent PDF
        :type ppm_id: str
        :param filename: The filename of the file
        :type filename: str
        :param url: The URL of the file
        :type url: str
        :param hash: The md5 hash of the file
        :type hash: str
        :param size: The size of the file
        :type size: int
        :param composition: The consent Composition object
        :type composition: dict
        :param identifiers: An optional list if identifier objects to attach to
        the DocumentReference
        :type identifiers: list
        :return: The DocumentReference URL
        """
        # Retain the response content for debugging
        content = None
        try:
            # Build the resource
            resource = {
                "resourceType": "DocumentReference",
                "subject": {"reference": "Patient/" + ppm_id},
                "type": {
                    "coding": [
                        {
                            "system": FHIR.ppm_consent_type_system,
                            "code": FHIR.ppm_consent_type_value,
                            "display": FHIR.ppm_consent_type_display,
                        }
                    ]
                },
                "date": datetime.now(timezone.utc).isoformat(),
                "status": "current",
                "content": [
                    {
                        "attachment": {
                            "contentType": "application/pdf",
                            "language": "en-US",
                            "url": url,
                            "creation": datetime.now(timezone.utc).isoformat(),
                            "title": filename,
                            "hash": hash,
                            "size": size,
                        }
                    }
                ],
                "context": {"related": [{"reference": f"ResearchStudy/{PPM.Study.fhir_id(study)}"}]},
            }

            # If passed, add identifiers
            if identifiers:
                resource.setdefault("identifier", []).extend(identifiers)

            # Start a bundle request
            bundle = Bundle()
            bundle.entry = []
            bundle.type = "transaction"

            # Create the document reference
            document_reference = DocumentReference(resource)

            # Create placeholder ID
            document_reference_id = uuid.uuid1().urn

            # Add Organization objects to bundle.
            document_reference_request = BundleEntryRequest()
            document_reference_request.method = "POST"
            document_reference_request.url = "DocumentReference"

            # Create the organization entry
            organization_entry = BundleEntry({"resource": document_reference.as_json()})
            organization_entry.request = document_reference_request
            organization_entry.fullUrl = document_reference_id

            # Add it
            bundle.entry.append(organization_entry)

            # Update the composition
            composition["section"].append({"entry": [{"reference": document_reference_id}]})

            # Ensure it's related to a study
            for entry in [
                section["entry"][0]
                for section in composition["section"]
                if "entry" in section and len(section["entry"])
            ]:
                if entry.get("reference") and PPM.Study.is_ppm(entry["reference"].replace("ResearchStudy/", "")):
                    break
            else:
                # Add it
                logger.debug(f"PPM/{study}/{ppm_id}: Adding study reference to composition")
                composition["section"].append({"entry": [{"reference": f"ResearchStudy/{PPM.Study.fhir_id(study)}"}]})

            # Add List objects to bundle.
            composition_request = BundleEntryRequest()
            composition_request.method = "PUT"
            composition_request.url = "Composition/{}".format(composition["id"])

            # Create the organization entry
            composition_entry = BundleEntry({"resource": composition})
            composition_entry.request = composition_request

            # Add it
            bundle.entry.append(composition_entry)

            # Post the transaction
            response = FHIR.post(PPM.fhir_url(), json=bundle.as_json())
            response.raise_for_status()

            # Parse out created identifiers
            for result in [entry["response"] for entry in response.json().get("entry", []) if "response" in entry]:
                logging.debug(f"FHIR result: {result}")

            # Check response
            return response.ok

        except (requests.HTTPError, TypeError, ValueError):
            logger.error(
                "Create consent DocumentReference failed",
                exc_info=True,
                extra={"study": study, "ppm_id": ppm_id, "response": content},
            )

        return False

    #
    # READ
    #

    @staticmethod
    def _query_bundle(resource_type: str, query: dict[str, Any] = None) -> Bundle:
        """
        This method will fetch all resources for a given type, including paged
        results. It will then return a Bundle resources containing the
        actual results of the search.

        # TODO: Set this method to use `FHIR.fhir_search` to move query to body of request instead of URL

        :param resource_type: FHIR resource type
        :type resource_type: str
        :param query: A dict of key value pairs for searching resources
        :type query: dict
        :return: A Bundle resource containing the results of the search
        :rtype: Bundle
        """
        # Build the URL.
        url_builder = furl(PPM.fhir_url())
        url_builder.path.add(resource_type)

        # Add query if passed and set a return count to a high number,
        # despite the server
        # probably ignoring it.
        url_builder.query.params.add("_count", 999)
        if query is not None:
            for key, value in query.items():
                if type(value) is list:
                    for _value in value:
                        url_builder.query.params.add(key, _value)
                else:
                    url_builder.query.params.add(key, value)

        # Prepare the final URL
        url = url_builder.url

        # Collect them.
        total_bundle = None

        # The url will be set to none on the second iteration if all resources
        # were returned, or it will be set to the next page of resources if more exist.
        while url is not None:

            # Make the request.
            response = FHIR.get(url)
            response.raise_for_status()

            # Parse the JSON.
            bundle = response.json()
            if total_bundle is None:
                total_bundle = bundle
            elif bundle.get("total", 0) > 0:
                total_bundle["entry"].extend(bundle.get("entry"))

            # Check for a page.
            url = None

            for link in bundle.get("link", []):
                if link["relation"] == "next":
                    url = link["url"]

                    # Swap domain if necessary
                    if furl(url).host != furl(PPM.fhir_url()).host:

                        # Set it
                        url = furl(url).set(host=furl(PPM.fhir_url()).host).url

        return Bundle(total_bundle)

    @staticmethod
    def _query_resources(resource_type: str, query: Optional[dict] = None) -> list[Optional[dict]]:
        """
        This method will fetch all resources for a given type, including paged
        results. It will then return a list of the actual resource objects.
        If not resources are returned, any empty list is returned.

        :param resource_type: FHIR resource type
        :type resource_type: str
        :param query: A dict of key value pairs for searching resources
        :type query: dict
        :return: A list of FHIR resource dicts
        :rtype: [dict], defaults to []
        """
        logger.debug("Query resource: {}".format(resource_type))

        # Query for the bundle
        bundle = FHIR._query_bundle(resource_type, query).as_json()

        # Extract resources, if any
        return [entry["resource"] for entry in bundle.get("entry", []) if entry.get("resource")]

    @staticmethod
    def query_participants(
        studies: Optional[list[str]] = None,
        enrollments: Optional[list[str]] = None,
        active: Optional[bool] = None,
        testing: bool = False,
    ) -> list[dict]:
        """
        Queries the current set of participants. This allows filtering on study,
        enrollment, status, etc. A list of matching participants are returned
        as flattened participant resource dicts.

        Example:

        {
            "email": str,
            "fhir_id": str,
            "ppm_id": str,
            "enrollment": str,
            "status": str,
            "study": str,
            "project": str,
            "date_registered": str,
            "datetime_registered": str,
            "date_enrollment_updated": str,
            "datetime_enrollment_updated": str,
        }

        :param studies: A list of PPM studies to filter on
        :type studies: List[str]
        :param enrollments: A list of PPM enrollments to filter on
        :type enrollments: List[str]
        :param active: Select on whether the Patient.active flag is set or not
        :type active: bool, defaults to None
        :param testing: Whether to include testing participants or not
        :type testing: defaults to False
        :return: A list of dicts per participant fetched
        :rtype: List[dict]
        """
        logger.debug(
            "Querying participants - Enrollments: {} - "
            "Studies: {} - Active: {} - Testing: {}".format(enrollments, studies, active, testing)
        )

        # Ensure we are using values
        if studies:
            studies = [PPM.Study.get(study).value for study in studies]
        if enrollments:
            enrollments = [PPM.Enrollment.get(enrollment).value for enrollment in enrollments]

        # Build the query for ResearchSubjects first
        query = {
            "_include": ["ResearchSubject:individual:Patient"],
        }

        # Add studies filter, if passed
        if studies:
            query["study"] = (",".join([f"ResearchStudy/{PPM.Study.fhir_id(s)}" for s in studies]),)

        # Get ResearchSubjects first
        bundle = FHIR._query_bundle("ResearchSubject", query)

        # Check for empty query set
        if not bundle.entry:
            return []

        # Build the query for Flags second
        flag_query = {}

        # Check if filtering on studies
        if studies:
            flag_query["identifier"] = ",".join(
                [f"{FHIR.enrollment_flag_study_identifier_system}|{PPM.Study.fhir_id(s)}" for s in studies]
            )

        # Get Flags
        flag_bundle = FHIR._query_bundle("Flag", flag_query)

        # Build a dictionary keyed by FHIR IDs containing enrollment status
        patient_enrollments = {
            entry.resource.subject.reference.split("/")[1]: {
                "status": entry.resource.code.coding[0].code,
                "date_accepted": entry.resource.period.start.origval if entry.resource.period else "",
                "date_updated": entry.resource.meta.lastUpdated.origval,
            }
            for entry in flag_bundle.entry
        }

        # Build a dictionary keyed by FHIR IDs containing flattened study objects
        patient_studies = {
            entry.resource.individual.reference.split("/")[1]: {
                "study": FHIR.get_study_from_research_subject(entry.resource),
                "date_registered": entry.resource.period.start.origval,
            }
            for entry in bundle.entry
            if entry.resource.resource_type == "ResearchSubject"
        }

        # Process patients
        patients = []
        for patient in [entry.resource for entry in bundle.entry if entry.resource.resource_type == "Patient"]:
            try:
                # Check if filtering by 'active'
                if active is not None and patient.active != active:
                    continue

                # Fetch their email
                email = next(
                    identifier.value
                    for identifier in patient.identifier
                    if identifier.system == FHIR.patient_email_identifier_system
                )

                # Check if tester
                if not testing and PPM.is_tester(email):
                    continue

                # Get values and compare to filters
                patient_enrollment = patient_enrollments.get(patient.id)
                patient_study = patient_studies.get(patient.id)

                if enrollments and patient_enrollment["status"].lower() not in enrollments:
                    continue

                if studies and patient_study.get("study").lower() not in studies:
                    continue

                # Pull out dates, both formatted and raw
                date_registered = FHIR._format_date(patient_study.get("date_registered"), "%m/%d/%Y")
                datetime_registered = patient_study.get("date_registered")
                date_enrollment_updated = FHIR._format_date(patient_enrollment.get("date_updated"), "%m/%d/%Y")
                datetime_enrollment_updated = patient_enrollment.get("date_updated")

                # Build the dict
                patient_dict = {
                    "email": email,
                    "fhir_id": patient.id,
                    "ppm_id": patient.id,
                    "enrollment": patient_enrollment["status"],
                    "status": patient_enrollment["status"],
                    "study": patient_study.get("study"),
                    "project": patient_study.get("study"),
                    "date_registered": date_registered,
                    "datetime_registered": datetime_registered,
                    "date_enrollment_updated": date_enrollment_updated,
                    "datetime_enrollment_updated": datetime_enrollment_updated,
                }

                # Check acceptance
                if patient_enrollment.get("date_accepted"):
                    patient_dict["date_accepted"] = FHIR._format_date(patient_enrollment["date_accepted"], "%m/%d/%Y")
                    patient_dict["datetime_accepted"] = patient_enrollment["date_accepted"]

                # Wrap the patient resource in a fake bundle and flatten them
                flattened_patient = FHIR.flatten_patient(patient)
                if flattened_patient:
                    patient_dict.update(flattened_patient)

                # Add it
                patients.append(patient_dict)

            except Exception as e:
                logger.exception("Resources malformed for Patient/{}: {}".format(patient.id, e))

        return patients

    @staticmethod
    def query_patients(
        study: str = None,
        enrollment: str = None,
        active: bool = None,
        testing: bool = False,
        include_deceased: bool = True,
    ) -> list[dict]:
        """
        Queries the current set of participants. This allows filtering on study,
        enrollment, status, etc. A list of matching participants are returned
        as flattened participant resource dicts.

        Example:

        {
            "email": str,
            "fhir_id": str,
            "ppm_id": str,
            "enrollment": str,
            "status": str,
            "study": str,
            "project": str,
            "date_registered": str,
            "datetime_registered": str,
            "date_enrollment_updated": str,
            "datetime_enrollment_updated": str,
        }

        :param studies: A comma-separated string of PPM studies to filter on
        :type studies: str
        :param enrollments: A comma-separated string of PPM enrollments to filter on
        :type enrollments: str
        :param active: Select on whether the Patient.active flag is set or not
        :type active: bool, defaults to None
        :param testing: Whether to include testing participants or not
        :type testing: defaults to False
        :return: A list of dicts per participant fetched
        :rtype: List[dict]
        """
        logger.debug(
            "Getting patients - enrollment: {}, study: {}, "
            "active: {}, testing: {}".format(enrollment, study, active, testing)
        )

        # Check for multiples
        enrollments = enrollment.split(",") if enrollment else None
        studies = study.split(",") if study else None

        # Call the query_participants method
        return FHIR.query_participants(studies, enrollments, active, testing)

    @staticmethod
    def get_participant(
        patient: Union[Patient, dict, str],
        study: str = None,
        questionnaires: list[dict] = None,
        flatten_return: bool = False,
    ) -> dict:
        """
        This method fetches a participant's entire FHIR record and returns it.
        If specified, the record will be flattened into a dictionary. Otherwise,
        a list of all resources belonging to the participant are returned.
        Optional values include questionnaire IDs
        to be flattened. If these are not specified, hard-coded values from the
        PPM module will be used, althought this is deprecated behavior.

        :param patient: The participant identifier, PPM ID or email
        :type patient: Union[Patient, dict, str]
        :param study: The study to fetch resources for
        :type study: str, defaults to None
        :param questionnaires: The list of survey/questionnaires for this study
        :type questionnaires: list, defaults to None
        :param flatten_return: Whether to flatten the resources or not
        :type flatten_return: bool, defaults to False
        :returns: A dictionary comprising the user's record
        :rtype: dict
        """
        # Build the FHIR Consent URL.
        url = furl(PPM.fhir_url())
        url.path.segments.append("Patient")
        url.query.params.add("_include", FHIR.PARTICIPANT_PATIENT_INCLUDES)
        url.query.params.add("_include:iterate", FHIR.PARTICIPANT_PATIENT_INCLUDE_ITERATES)
        url.query.params.add("_revinclude", FHIR.PARTICIPANT_PATIENT_REVINCLUDES)
        url.query.params.add("_revinclude:iterate", FHIR.PARTICIPANT_PATIENT_REVINCLUDE_ITERATES)

        # Add patient query
        for key, value in FHIR._patient_query(patient).items():
            url.query.params.add(key, value)

        # Make the call
        content = response = None
        try:
            # Make the FHIR request.
            response = FHIR.get(url.url)
            content = response.content

            # Check for entries
            bundle = response.json()

            if not bundle.get("entry") or not FHIR._find_resources(bundle, "Patient"):
                logger.debug(f"PPM/FHIR: Empty and/or no Patient for {patient}")
                return {}

            # Make the request
            secondary_bundle = FHIR._get_participant_missing_resources(bundle)
            if secondary_bundle and secondary_bundle.get("entry"):
                logger.debug(f"PPM/FHIR: Fetched {len(secondary_bundle['entry'])} missing resources")

                # Add secondary resources to primary bundle
                bundle["entry"].extend(secondary_bundle["entry"])

                # Update bundle count
                bundle["total"] = len(bundle["entry"])

            if flatten_return:
                return FHIR.flatten_participant(
                    bundle=bundle,
                    study=study,
                    questionnaires=questionnaires,
                )
            else:
                return bundle

        except Exception as e:
            logger.exception(
                "FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": patient,
                    "study": study,
                    "questionnaires": questionnaires,
                    "flatten_return": flatten_return,
                    "response": response,
                    "content": content,
                },
            )

        return None

    @staticmethod
    def _get_participant_missing_resources(bundle: dict) -> Optional[dict]:
        """
        Checks the current bundle of all participant resources and checks
        for any missing linked resources that are needed for parsing
        the participants' record. This usually includes secondary references
        like Questionnaire or ResearchStudy resources that are not directly
        linked to a Patient. While current queries are designed to include
        this resources initially, spotty support by FHIR instance backends
        will sometimes require this second query to complete the bundle.
        An example being GCP's Healthcare API FHIR does not support
        `_revinclude:iterate` for including a Questionnaire linked by a
        QuestionnaireResponse. Presumably due to the weird canonical URL
        reference type enforeced in FHIR R4 between those two resources.
        If no resources are missing, `None` is returned.

        :param bundle: The current bundle of fetched resources for the
        participant.
        :type bundle: dict
        :return: A second bundle containing missing resources, defaults to None
        :rtype: Optional[dict]
        """
        # Prepare a bundle to get all other resources that aren't directly
        # linked to Patient (e.g. Questionnaire, ResearchStudy)
        secondary_resources = {
            "Questionnaire": {
                "resource": "QuestionnaireResponse",
                "get_ids": lambda r: [r["questionnaire"].rsplit("/", 1)[-1]],
            },
            "ResearchStudy": {
                "resource": "ResearchSubject",
                "get_ids": lambda r: [r["study"]["reference"].rsplit("/", 1)[-1]],
            },
            "Organization": {
                "resource": "List",
                "get_ids": lambda r: [e["item"]["reference"].rsplit("/", 1)[-1] for e in r["entry"]],
            },
        }

        # Build a batch bundle
        secondary_bundle = {
            "resourceType": "Bundle",
            "type": "batch",
            "entry": [],
        }

        # Iterate secondary resources
        for resource_type, link in secondary_resources.items():

            # Get referenced IDs from resources in current bundle
            references = [
                f"{resource_type}/{resource_id}"
                for e in bundle["entry"]
                if e.get("resource", {}).get("resourceType") == link["resource"]
                for resource_id in link["get_ids"](e["resource"])
            ]

            # Iterate references to missing resources
            for reference in references:

                # Split the reference
                resource_type, resource_id = tuple(reference.split("/", 1))

                # Check current bundle
                if not FHIR.find_resource(bundle, resource_type=resource_type, filter=lambda r: r["id"] == resource_id):

                    # Make entry for bundle
                    secondary_bundle["entry"].append(
                        {
                            "request": {
                                "method": "GET",
                                "url": reference,
                            }
                        }
                    )

        # Make the request if we have entries
        if secondary_bundle["entry"]:
            secondary_bundle = FHIR.fhir_transaction(secondary_bundle)

            # Ensure we have a return value
            if not secondary_bundle or not secondary_bundle.get("entry"):
                logger.warning(f"PPM/FHIR: Could not find missing resources: {references}")
            else:
                return secondary_bundle
        else:
            logger.debug("PPM/FHIR: No missing resources")

        return None

    @staticmethod
    def get_patient(patient: str, flatten_return: bool = False) -> Optional[dict]:
        """
        This method queries a participant's FHIR Patient record and returns it
        if available. If specified, the record will be flattened into a
        dictionary. Otherwise, a list of relevant resources will be returned.

        :param patient: The participant identifier, PPM ID or email
        :type patient: str
        :param flatten_return: Whether to flatten the resources or not
        :type flatten_return: bool, defaults to False
        :returns: A dictionary comprising the user's Patient record
        :rtype: dict, optional
        """
        # Build the FHIR Consent URL.
        url = furl(PPM.fhir_url())
        url.path.segments.append("Patient")

        # Add query for patient
        for key, value in FHIR._patient_query(patient).items():
            url.query.params.add(key, value)

        # Make the call
        response = content = None
        try:
            # Make the FHIR request.
            response = FHIR.get(url.url)
            content = response.content

            if flatten_return:
                return FHIR.flatten_patient(response.json())
            else:
                return next(
                    (entry["resource"] for entry in response.json().get("entry", [])),
                    None,
                )

        except Exception as e:
            logger.exception(
                f"PPM/FHIR Error: {e}",
                exc_info=True,
                extra={
                    "patient": patient,
                    "url": url,
                    "response": response,
                    "content": content,
                },
            )

        return None

    @staticmethod
    def query_enrollment_flags(
        patient: Union[Patient, dict, str] = None, study: str = None, flatten_return: bool = False
    ) -> list[dict]:
        """
        This method finds and returns the Flag resources used to track
        participant's progress through PPM studies. Can optionally filter on
        Patient or study. Flag resources are returned in a list or can be
        flattened.

        :param patient: The Patient object/identifier to query on, defaults to None
        :type patient: Optional[Union[Patient, dict, str]]
        :param study: The study for which the Flag tracks enrollment, defaults to None
        :type study: Optional[str]
        :param flatten_return: Whether to flatten the resources or not
        :type flatten_return: bool, defaults to False
        :returns: The found Flag resources, or flattened versions if specified
        :rtype: list[dict]
        """
        try:
            # Build the query
            query = {}
            if patient:
                query.update(FHIR._patient_resource_query(patient, "subject"))

            # Add study filter
            if study:
                query["identifier"] = f"{FHIR.enrollment_flag_study_identifier_system}|{PPM.Study.fhir_id(study)}"

            flags = FHIR._query_resources("Flag", query=query)
            if flags and flatten_return:
                return [FHIR.flatten_enrollment_flag(f) for f in flags]

            return flags

        except Exception as e:
            logger.exception(
                f"PPM/FHIR Error: {e}",
                exc_info=True,
                extra={
                    "patient": patient,
                    "study": study,
                },
            )

    @staticmethod
    def get_enrollment_flag(
        patient: Union[Patient, dict, str], study: str, flatten_return: bool = False
    ) -> Optional[dict]:
        """
        This method finds and returns the Flag resource used to track the
        passed Patient's progress through the given PPM study.
        If specified, the record will be flattened into a dictionary.
        Otherwise, the Flag resource will be returned.

        :param patient: The Patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param study: The study for which the Flag tracks enrollment
        :type study: str
        :param flatten_return: Whether to flatten the resources or not
        :type flatten_return: bool, defaults to False
        :returns: The Flag resource if found, or a flattened version of it specified
        :rtype: Optional[dict]
        """
        try:
            # Call the query method with filters
            return next(
                iter(
                    FHIR.query_enrollment_flags(
                        patient=patient,
                        study=study,
                        flatten_return=flatten_return,
                    )
                ),
                None,
            )

        except Exception as e:
            logger.exception(
                f"PPM/FHIR Error: {e}",
                exc_info=True,
                extra={
                    "patient": patient,
                    "study": study,
                },
            )

    @staticmethod
    def query_patient_id(email: str) -> Optional[str]:
        """
        Queries FHIR for a Patient matching the given email and returns
        their Patient ID if found.

        :param email: The email of the Patient to query for
        :type email: str
        :return: The Patient ID if found, otherwise None
        :rtype: Optional[str]
        """
        try:
            # Get and return the patient's ID
            return FHIR.get_patient(email)["id"]

        except Exception:
            logger.info(
                f"PPM/FHIR: No Patient exists for email '{email}'",
            )

        return None

    @staticmethod
    def get_ppm_id(email: str) -> Optional[str]:
        """
        Queries FHIR for a Patient with an identifier matching the passed
        email address and returns that resource's ID, if it exists.

        :param email: The email of the Patient to query on
        :type email: str
        :return: The FHIR ID of the Patient if it exists
        :rtype: Optional[str]
        """
        warnings.warn("This method is deprecated, use `query_patient_id` instead", DeprecationWarning, stacklevel=2)
        return FHIR.query_patient_id(email)

    @staticmethod
    def get_consent_composition(
        patient: Union[Patient, dict, str], study: str, flatten_return: bool = False
    ) -> Optional[dict]:
        """
        Gets and returns the Composition storing the user's signed consent
        resources. If flattened, all related resources are included when
        flattened, whereas only the Composition resource is returned if the
        caller elects not to flatten the return.

        :param patient: The Patient identifier or object who owns the consent
        :type patient: Union[Patient, dict, str]
        :param study: The study for which the consent was signed
        :type study: str
        :param flatten_return: Whether to return FHIR JSON or a flattened dict
        :type flatten_return: bool
        :return: The Composition object or a dict containing details of all
        related resources
        :rtype: dict, defaults to None
        """
        # Build the query
        query = {
            "type": f"{FHIR.ppm_consent_type_system}|{FHIR.ppm_consent_type_value}",
            "entry": f"ResearchStudy/{PPM.Study.fhir_id(study)}",
            "_include": "*",
        }

        # Build the query
        query.update(FHIR._patient_resource_query(patient, "subject"))

        # Get resources
        bundle = FHIR._query_bundle("Composition", query=query)
        if bundle:

            # Check for multiple Compositions matching the query
            # TODO: This is likely not required any longer
            compositions = FHIR._find_resources(bundle, "Composition")
            if len(compositions) > 1:
                logger.error(
                    f"FHIR Error: Multiple consent Compositions returned for {study}/{patient}",
                    extra={
                        "compositions": [f"Composition/{c['id']}" for c in compositions],
                    },
                )

            # Handle the format of return
            if flatten_return:

                # Flatten bundle
                return FHIR.flatten_consent_composition(bundle)
            else:

                # Return just the Composition resource
                return next(iter(compositions), None)

        return None

    @staticmethod
    def get_consent_document_reference(
        patient: Union[Patient, dict, str], study: str, flatten_return: bool = False
    ) -> Optional[dict]:
        """
        Gets and returns the DocumentReference storing the user's signed consent PDF

        :param patient: The Patient object or identifier who owns the consent PDF
        :type patient: Union[Patient, dict, str]
        :param study: The study for which the consent was signed
        :type study: str
        :param flatten_return: Whether to return FHIR JSON or a flattened dict
        :type flatten_return: bool
        :return: The DocumentReference object if it exists
        :rtype: dict, defaults to None
        """
        # Build the query
        query = {
            "type": f"{FHIR.ppm_consent_type_system}|{FHIR.ppm_consent_type_value}",
            "related": f"ResearchStudy/{PPM.Study.fhir_id(study)}",
        }

        # Add query for patient
        query.update(FHIR._patient_resource_query(patient))

        # Get resources
        resources = FHIR._query_resources("DocumentReference", query=query)
        if resources:

            # Check for multiple
            if len(resources) > 1:
                logger.error(
                    f"FHIR Error: Multiple consent DocumentReferences returned for {study}/{patient}",
                    extra={
                        "document_references": [f"DocumentReference/{r['id']}" for r in resources],
                    },
                )

                # TODO: Multiple Resource Handling
                # In instances where we catch too many resources, we should
                # at least come up with a determinate manner in which we select
                # the one to use (e.g. creation date)

            # Handle the format of return
            if flatten_return:
                return FHIR.flatten_document_reference(resources[0])
            else:
                return resources[0]

        return None

    @staticmethod
    def get_ppm_device(id: str, flatten_return: bool = False) -> Optional[dict]:
        """
        Queries FHIR for PPM devices and returns the device, if any, matching
        the passed ID. Note: This is the numeric FHIR ID of the resource.

        :param id: The item's FHIR ID
        :type id: str
        :param flatten_return: Whether to flatten the resource or not
        :type flatten_return: bool
        :return: The matching device resource, if any
        :rtype: dict, defaults to None
        """
        # Get the devices
        device = next(iter(FHIR._query_resources("Device", query={"_id": id})), None)

        # Check if the resource should be flattened
        if device and flatten_return:
            return FHIR.flatten_ppm_device(device)

        return device

    @staticmethod
    def query_ppm_devices(
        patient: Union[Patient, dict, str] = None,
        item: str = None,
        identifier: str = None,
        flatten_return: bool = False,
    ) -> list[dict]:
        """
        Queries the participants FHIR record for any PPM-related Device
        resources. These are used to track kits, etc. that
        are sent to participants for collecting samples and other
        information/data.

        :param patient: The patient identifier/ID/object
        :type patient: object
        :param item: The PPM item type
        :type item: str
        :param identifier: The device identifier
        :type identifier: str
        :param flatten_return: Whether to flatten the resource or not
        :type flatten_return: bool
        :return: A list of resources
        :rtype: list
        """

        # Check item type
        if item:
            query = {
                "type": "{}|{}".format(FHIR.device_coding_system, item),
            }
        else:

            query = {
                "type": "{}|".format(FHIR.device_coding_system),
            }

        # Check for an identifier
        if identifier:
            query["identifier"] = "{}|{}".format(FHIR.device_identifier_system, identifier)

        # Update for the patient query
        if patient:
            query.update(FHIR._patient_resource_query(patient))

        # Get the devices
        devices = FHIR._query_resources("Device", query=query)

        if flatten_return:
            return [FHIR.flatten_ppm_device(resource) for resource in devices]
        else:
            return devices

    @staticmethod
    def query_ppm_research_subjects(
        patient: Union[Patient, dict, str] = None, flatten_return: bool = False
    ) -> list[dict]:
        """
        Queries the participants FHIR record for any PPM-specific
        ResearchSubject resources. Returns either a list of ResearchSubject
        resources or a list of flattened resource dicts.

        :param patient: The patient identifier/ID/object
        :type patient: Union[Patient, dict, str]
        :param flatten_return: Whether to flatten the resource or not
        :type flatten_return: bool
        :return: A list of resources
        :rtype: list
        """
        # Get flags for current user
        query = {
            "identifier": "{}|".format(FHIR.research_subject_study_identifier_system),
        }

        # Update for the patient query
        if patient:
            query.update(FHIR._patient_resource_query(patient, key="individual"))

        # Get the resources
        resources = FHIR._query_resources("ResearchSubject", query=query)

        if flatten_return:
            return [FHIR.flatten_research_subject(resource) for resource in resources]
        else:
            return resources

    @staticmethod
    def query_research_subjects(patient: Union[Patient, dict, str] = None, flatten_return: bool = False) -> list[dict]:
        """
        Queries the participants FHIR record for any non-PPM study
        ResearchSubject resources. Returns either a list of ResearchSubject
        resources or a list of flattened resource dicts.

        :param patient: The patient identifier/ID/object
        :type patient: Union[Patient, dict, str]
        :param flatten_return: Whether to flatten the resource or not
        :type flatten_return: bool
        :return: A list of resources
        :rtype: list
        """
        # Build query
        query = {}
        if patient:
            query = FHIR._patient_resource_query(patient)

        # Get the resources
        resources = FHIR._query_resources("ResearchSubject", query=query)

        # Filter out PPM subjects
        research_subjects = [
            entry
            for entry in resources
            if not PPM.Study.is_ppm(entry.get("study", {}).get("reference", "").replace("ResearchStudy/", ""))
        ]

        if flatten_return:
            return [FHIR.flatten_research_subject(resource) for resource in research_subjects]
        else:
            return research_subjects

    @staticmethod
    def query_qualtrics_questionnaire(survey_id: str) -> Bundle:
        """
        Queries FHIR for a Questionnaire created from the passed Qualtrics
        survey.

        :param survey_id: The Qualtrics survey ID
        :type survey_id: str
        :return: The FHIR Bundle containing the results of the query
        :rtype: Bundle
        """
        # Build the query
        query = {
            "identifier": "{}|{}".format(FHIR.qualtrics_survey_identifier_system, survey_id),
        }

        # Query resources
        bundle = FHIR._query_bundle("Questionnaire", query=query)

        return bundle

    @staticmethod
    def query_questionnaire_responses(
        patient: Union[Patient, dict, str] = None, questionnaire_id: str = None
    ) -> Bundle:
        """
        Finds and returns any QuestionnaireResponse resources for the given
        Patient and Questionnaire combination.

        :param patient: The Patient object/identifier for the
        QuestionnaireResponse, defaults to None
        :type patient: Union[Patient, dict, str], optional
        :param questionnaire_id: The ID of the Questionnaire the QuestionnaireResponse was for, defaults to None
        :type questionnaire_id: str, optional
        :return: A FHIR Bundle resource
        :rtype: Bundle
        """

        # Build the query
        query = {
            "questionnaire": "Questionnaire/{}".format(questionnaire_id),
            "_include": "*",
        }

        # Check patient
        if patient:
            query.update(FHIR._patient_resource_query(patient, "source"))

        # Query resources
        bundle = FHIR._query_bundle("QuestionnaireResponse", query=query)

        return bundle

    @staticmethod
    def query_qualtrics_questionnaire_responses(
        patient: Union[Patient, dict, str] = None, survey_id: str = None
    ) -> Bundle:
        """
        Queries FHIR for QuestionnaireResponses created for the passed Qualtrics
        survey by the passed patient.

        :param patient: The patient reference
        :type patient: Union[Patient, dict, str]
        :param survey_id: The Qualtrics survey ID
        :type survey_id: str
        :return: The FHIR Bundle containing the results of the query
        :rtype: Bundle
        """
        # Build the query
        query = {
            "questionnaire.identifier": "{}|".format(FHIR.qualtrics_survey_identifier_system),
            "_include": "*",
        }

        # Check for specific survey
        if survey_id:
            query["questionnaire.identifier"] = "{}{}".format(query["questionnaire.identifier"], survey_id)

        # Check patient
        if patient:
            query.update(FHIR._patient_resource_query(patient, "source"))

        # Query resources
        bundle = FHIR._query_bundle("QuestionnaireResponse", query=query)

        return bundle

    @staticmethod
    def get_qualtrics_questionnaire(survey_id: str) -> Optional[dict]:
        """
        Queries FHIR for a Questionnaire created from the passed Qualtrics
        survey.

        :param survey_id: The Qualtrics survey ID
        :type survey_id: str
        :return: The FHIR Questionnaire object
        :rtype: dict or None
        """
        # Query resources
        bundle = FHIR.query_qualtrics_questionnaire(survey_id=survey_id)

        if bundle and bundle.entry:
            return next(
                (r.resource.as_json() for r in bundle.entry if r.resource.resource_type == "Questionnaire"),
                None,
            )

        return None

    @staticmethod
    def get_questionnaire_response(
        patient: Union[Patient, dict, str], questionnaire_id: str, flatten_return: bool = False
    ) -> Optional[dict]:
        """
        Returns the QuestionnaireResponse for the given patient and
        questionnaire. If specified to do so, the response object will be
        flattened to an easier to parse dictionary object. Returns None if
        not QuestionnaireResponse is found.add()

        :param patient: The PPM participant to find the response for
        :type patient: Union[Patient, dict, str]
        :param questionnaire_id: The ID of the Questionnaire the response was for
        :type questionnaire_id: str
        :param flatten_return: Whether to flatten the resource or not, defaults to False
        :type flatten_return: bool, optional
        :return: The QuestionnaireResponse object
        :rtype: dict, or None
        """
        # Build canonical URL for Questionnaire
        questionnaire_url = furl(PPM.fhir_url()) / "Questionnaire" / questionnaire_id

        # Build the query
        query = {
            "questionnaire": questionnaire_url.url,
            "_include": "*",
        }

        # Check patient
        query.update(FHIR._patient_resource_query(patient=patient, key="source"))

        # Query resources
        bundle = FHIR._query_bundle("QuestionnaireResponse", query=query)

        # Ensure we've got resources
        if bundle.entry:

            if flatten_return:

                # We need the whole bundle to flatten it
                return FHIR.flatten_questionnaire_response(bundle, questionnaire_id)
            else:

                # Fetch the questionnaire response from the bundle
                questionnaire_response = next(
                    (r.resource.as_json() for r in bundle.entry if r.resource.resource_type == "QuestionnaireResponse"),
                    None,
                )
                return questionnaire_response
        else:
            logger.warning(f"PPM/FHIR: No QuestionnaireResponse for query: {query}")

    @staticmethod
    def get_qualtrics_questionnaire_response(
        patient: Union[Patient, dict, str], survey_id: str, flatten_return: bool = False
    ) -> Optional[dict]:
        """
        Queries FHIR for a QuestionnaireResponse for the passed patient and
        Qualtrics survey. If specified, FHIR resource is flattened for output.

        :param patient: The patient reference
        :type patient: Union[Patient, dict, str]
        :param survey_id: The Qualtrics survey ID
        :type survey_id: str
        :param flatten_return: Whether to flatten the resource or not, defaults to False
        :type flatten_return: bool, optional
        :return: The FHIR Questionnaire object
        :rtype: dict or None
        """
        # Query resources
        bundle = FHIR.query_qualtrics_questionnaire_responses(patient=patient, survey_id=survey_id)

        # Pull out Questionnaire ID
        questionnaire = next(e.resource for e in bundle.entry if e.resource.resource_type == "Questionnaire")

        if flatten_return:

            # We need the whole bundle to flatten it
            return FHIR.flatten_questionnaire_response(bundle, questionnaire["id"])
        else:

            # Fetch the questionnaire response from the bundle
            questionnaire_response = next(
                (r.resource for r in bundle.entry if r.resource.resource_type == "QuestionnaireResponse"),
                None,
            )
            return questionnaire_response.as_json()

    @staticmethod
    def query_document_references(
        patient: Union[Patient, dict, str] = None, query: dict = None, flatten_return: bool = False
    ) -> list[dict]:
        """
        Queries the current user's FHIR record for any DocumentReferences
        related to this type

        :param patient: The patient object/identifier to query resources on
        :type pation: Any
        :param query: They query parameters to use for the request
        :type query: dict
        :param flatten_return: Whether to flatten the resource or not, defaults to False
        :type flatten_return: bool, optional
        :return: A list of DocumentReference resources
        :rtype: list
        """
        # Build the query
        if query is None:
            query = {}

        if patient:
            query.update(FHIR._patient_resource_query(patient))

        # Get resources
        resources = FHIR._query_resources("DocumentReference", query=query)

        if flatten_return:
            return [FHIR.flatten_document_reference(resource) for resource in resources]
        else:
            return resources

    @staticmethod
    def query_data_document_references(
        patient: Union[Patient, dict, str] = None,
        provider: str = None,
        status: str = None,
        flatten_return: bool = False,
    ) -> list[dict]:
        """
        Queries the current user's FHIR record for any DocumentReferences
        related to this type

        :param patient: The patient object/identifier to query resources on
        :type pation: Any
        :param provider: The provider to find DocumentReferences for (see P2MD)
        :type provider: str
        :param status: The status of the DocumentReference to query on
        :type status: str
        :param flatten_return: Whether to flatten the resource(s) or not, defaults to False
        :type flatten_return: bool, optional
        :return: A list of DocumentReference resources
        :rtype: list
        """
        # Build the query
        query = {}

        if patient:
            query.update(FHIR._patient_resource_query(patient))

        # Set the provider, if passed
        if provider:
            query["type"] = f"{FHIR.data_document_reference_identifier_system}|{provider}"
        else:
            query["type"] = f"{FHIR.data_document_reference_identifier_system}|"

        # Set preference on status
        if status:
            query["status"] = status

        # Get resources
        resources = FHIR._query_resources("DocumentReference", query=query)

        if flatten_return:
            return [FHIR.flatten_document_reference(resource) for resource in resources]
        else:
            return resources

    @staticmethod
    def query_ppm_participants_details(ppm_ids: list[str]) -> list[tuple[dict, list]]:
        """
        Fetches and returns basic details on the Patients and any PPM studies
        they're participating in.

        :param ppm_ids: A list of participant identifiers
        :type ppm_ids: list
        :return: A list of tuples of Patient object and a list of study codes
        :rtype: [(dict, list)]
        """
        # Get flags for current user
        query = {
            "identifier": "{}|".format(FHIR.research_subject_study_identifier_system),
            "_include": "ResearchSubject:individual",
            "individual": ppm_ids,
        }

        # Get the resources
        bundle = FHIR._query_bundle("ResearchSubject", query=query)
        if not bundle.entry:
            return []

        # Build list
        participants = []

        # Build response
        for patient in [p.resource for p in bundle.entry if p.resource.resource_type == "Patient"]:

            # Get matching research subject
            research_subjects = [
                r.resource
                for r in bundle.entry
                if r.resource.resource_type == "ResearchSubject"
                and r.resource.individual.reference == f"Patient/{patient.id}"
            ]

            # Get study IDs
            research_study_ids = [r.study.reference.split("/")[1] for r in research_subjects]

            # Add details
            participants.append((FHIR.flatten_patient(patient), research_study_ids))

        # Return list
        return participants

    @staticmethod
    def query_ppm_participant_details(patient_id: Any) -> tuple[Optional[dict], Optional[list[str]]]:
        """
        Fetches and returns basic details on the Patient and any PPM studies
        they're participating in.

        :param patient_id: Patient identifier
        :type patient_id: str
        :return: A tuple of Patient object and a list of study codes, defaults
        to (None, None)
        :rtype: tuple[Optional[dict], Optional[list[str]]]
        """
        # Call the group method and return the only entry
        participants = FHIR.query_ppm_participants_details([patient_id])
        return next(iter(participants), (None, None))

    @staticmethod
    def query_ppm_research_study_codes(patient: Union[Patient, dict, str]) -> list[str]:
        """
        Fetches all PPM-managed ResearchStudy resources the passed patient
        is participating in and returns the study codes.

        :param patient: Patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :return: A list of ResearchStudy codes
        :rtype: list
        """

        # Find Research subjects (without identifiers, so as to exclude PPM resources)
        research_subjects = FHIR.query_ppm_research_subjects(patient, flatten_return=False)

        if not research_subjects:
            logger.debug("No Research Subjects, no Research Studies")
            return None

        # Get study IDs
        research_study_ids = [subject["study"]["reference"].split("/")[1] for subject in research_subjects]

        # Remove 'ppm-' prefix and return
        return [PPM.Study.get(research_study_id).value for research_study_id in research_study_ids]

    @staticmethod
    def query_research_studies(
        patient: Union[Patient, dict, str], flatten_return: bool = False
    ) -> list[Union[str, dict]]:
        """
        Fetches and returns any ResearchStudy linked to the given Patient
        via a ResearchSubject resource that is NOT PPM-related. A flattened
        return simply returns a list of the ResearchStudy title properties.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param flatten_return: Whether to flatten the return, defaults to False
        :type flatten_return: bool, optional
        :return: A list of ResearchStudy resources or a list of their titles
        :rtype: list[Union[str, dict]]
        """
        # Find ResearchSubjects and include ResearchStudies
        query = FHIR._patient_resource_query(patient, "individual")
        query["_include"] = "ResearchSubject:study"

        # Exclude PPM ResearchSubjects
        query["identifier:not"] = [
            f"{FHIR.research_subject_study_identifier_system}" f"|{PPM.Study.fhir_id(study)}" for study in PPM.Study
        ]

        # Perform the search
        bundle = FHIR._query_bundle("ResearchSubject", query=query)

        # Extract ResearchStudies from the bundle
        research_studies = FHIR._find_resources(bundle, "ResearchStudy")

        # Return the titles
        if flatten_return:
            return [r["title"] for r in research_studies]
        else:
            return research_studies

    @staticmethod
    def get_point_of_care_list(
        patient: Union[Patient, dict, str], flatten_return: bool = False
    ) -> list[Union[dict, str]]:
        """
        Fetches and returns the list of points of care that are stored in
        FHIR as a List that references Organization resources. If flattened,
        a simple list of Organization names are returned instead of the
        actual Organization resources.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param flatten_return: Whether to flatten the reuturn, defaults to False
        :type flatten_return: bool, optional
        :return: A list of Organization resources or a list of their names
        :rtype: list[Union[dict, str]]
        """
        # Build the query for their point of care list
        query = {
            "code": FHIR.SNOMED_VERSION_URI + "|" + FHIR.SNOMED_LOCATION_CODE,
            "_include": "List:item",
        }

        # Add patient query
        query.update(FHIR._patient_resource_query(patient))

        # Find matching resource(s)
        bundle = FHIR._query_bundle("List", query=query)

        if flatten_return:
            return FHIR.flatten_list(bundle, "Organization")
        else:
            return [entry["resource"] for entry in bundle.as_json().get("entry", [])]

    @staticmethod
    def query_ppm_communications(
        patient: Union[Patient, dict, str] = None, identifier: str = None, flatten_return: bool = False
    ) -> list[dict]:
        """
        Find all Communication resources filtered by patient and/or identifier.

        :param patient: The patient object/identifier to query on, defaults to None
        :type patient: Union[Patient, dict, str], optional
        :param identifier: The identifier of the Communications, optional
        :type identifier: str, defaults to None
        :param flatten_return: Flatten the resources, optional
        :type flatten_return: bool, defaults to False
        :return: A list of Communication resources or a list of flattened resources
        :rtype: list[dict]
        """
        # Build the query
        query = {}
        if patient:
            query.update(FHIR._patient_resource_query(patient, "recipient"))

        if identifier:
            query["identifier"] = f"{FHIR.ppm_comm_identifier_system}|{identifier}"

        # Find all resources
        resources = FHIR._query_resources("Communication", query=query)

        if flatten_return:
            return [FHIR.flatten_communication(resource) for resource in resources]
        else:
            return resources

    #
    # UPDATE
    #

    @staticmethod
    def update_patient(patient_id: str, form: dict) -> bool:

        # Get their resource
        resource = FHIR.fhir_read("Patient", patient_id)

        # Make the updates
        try:
            # Check form data and make updates where necessary
            first_name = form.get("firstname")
            if first_name:
                resource["name"][0]["given"][0] = first_name

            last_name = form.get("lastname")
            if last_name:
                resource["name"][0]["family"] = last_name

            # Update the whole address
            street_address1 = form.get("street_address1")
            street_address2 = form.get("street_address2")
            if street_address1:
                resource["address"][0]["line"] = (
                    [street_address1] if not street_address2 else [street_address1, street_address2]
                )

            city = form.get("city")
            if city:
                resource["address"][0]["city"] = city

            state = form.get("state")
            if state:
                resource["address"][0]["state"] = state

            zip_code = form.get("zip")
            if zip_code:
                resource["address"][0]["postalCode"] = zip_code

            phone = form.get("phone")
            if phone:
                for telecom in resource.get("telecom", []):
                    if telecom["system"] == FHIR.patient_phone_telecom_system:
                        telecom["value"] = phone
                        break
                else:
                    # Add it
                    resource.setdefault("telecom", []).append(
                        {"system": FHIR.patient_phone_telecom_system, "value": phone}
                    )

            email = form.get("contact_email")
            if email:
                for telecom in resource.get("telecom", []):
                    if telecom["system"] == FHIR.patient_email_telecom_system:
                        telecom["value"] = email
                        break
                else:
                    # Add it
                    resource.setdefault("telecom", []).append(
                        {"system": FHIR.patient_email_telecom_system, "value": email}
                    )

            else:
                # Delete an existing email if it exists
                for telecom in resource.get("telecom", []):
                    if telecom["system"] == FHIR.patient_email_telecom_system:
                        resource["telecom"].remove(telecom)
                        break

            # Update their referral method if needed
            referral = form.get("how_did_you_hear_about_us")
            if referral:
                for extension in resource.get("extension", []):
                    if extension["url"] == FHIR.referral_extension_url:
                        extension["valueString"] = referral
                        break
                else:
                    # Add it
                    resource.setdefault("extension", []).append(
                        {"url": FHIR.referral_extension_url, "valueString": referral}
                    )

            else:
                # Delete this if not specified
                for extension in resource.get("extension", []):
                    if extension["url"] == FHIR.referral_extension_url:
                        resource["extension"].remove(extension)
                        break

            active = form.get("active")
            if active is not None:
                resource["active"] = False if active in ["false", False] else True

            # Put it and return whether the response is non-None
            return (
                FHIR.fhir_update(
                    resource_type="Patient",
                    resource_id=patient_id,
                    resource=resource,
                )
                is not None
            )

        except Exception as e:
            logger.error(
                "FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient_id": patient_id,
                },
            )

        return False

    @staticmethod
    def update_patient_active(patient_id: str, active: bool) -> bool:
        """
        Updates a Patient resource's 'active' property.

        :param patient_id: The identifier of the Patient
        :type patient_id: str
        :param active: The value for the 'active' property
        :type active: bool
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Make the updates
        try:
            # Build the update
            patch = [{"op": "replace", "path": "/active", "value": True if active else False}]

            # Make the request and return whether the response is non-None
            return (
                FHIR.fhir_patch(
                    path=["Patient", patient_id],
                    patch=patch,
                )
                is not None
            )

        except Exception as e:
            logger.error("FHIR Error: {}".format(e), exc_info=True, extra={"patient_id": patient_id})

        return False

    @staticmethod
    def update_ppm_device(
        id: str,
        patient_id: str,
        study: str,
        code: str,
        display: str,
        title: str,
        identifier: str,
        shipped: datetime = None,
        returned: datetime = None,
        note: str = None,
        tracking: str = None,
    ) -> bool:
        """
        Updates the Device for the given ID. Optional fields will be updated
        if a value is passed or deleted if None is passed.

        :param id: The ID of the Device resource
        :type id: str
        :param patient_id: The ID of the participant
        :type patient_id: str
        :param study: The study for which the device pertains, defaults to None
        :type study: str
        :param code: The code of the device type, defaults to None
        :type code: str
        :param display: The name of the device type, defaults to None
        :type display: str
        :param title: The admin-assigned title of the device, defaults to None
        :type title: str
        :param identifier: The identifier of the device, defaults to None
        :type identifier: str, optional
        :param shipped: The date the item was shipped to the participant, defaults to None
        :type shipped: datetime, optional
        :param returned: The date the item was returned to PPM, defaults to None
        :type returned: datetime, optional
        :param note: Any admin-assigned note for this device, defaults to None
        :type note: str, optional
        :param tracking: A tracking number for the item, defaults to None
        :type tracking: str, optional
        :return: Whether the operation succeeded or not
        :rtype: boolean
        """
        # Make the updates
        url = response = None
        try:
            # Get the device
            device = FHIR.get_ppm_device(id=id, flatten_return=False)
            if not device:
                logger.debug(f"No PPM device could be found for {patient_id}/{id}/{identifier}")
                return False

            # Update the resource identifier
            ppm_identifier = next(
                (i for i in device.get("identifier", []) if i.get("system") == FHIR.device_identifier_system),
                None,
            )
            if ppm_identifier and ppm_identifier.get("value") != identifier:
                ppm_identifier["value"] = identifier

            elif not ppm_identifier:
                device.setdefault("identifier", []).append(
                    {
                        "system": FHIR.device_identifier_system,
                        "value": identifier,
                    }
                )

            # Set the study
            extension = next(
                (e for e in device.get("extension", []) if e.get("url") == FHIR.device_study_extension_url), None
            )
            if extension:
                extension["valueString"] = study
            else:
                device.setdefault("extension", []).append(
                    {
                        "url": FHIR.device_study_extension_url,
                        "valueString": study,
                    }
                )

            # Set the title
            title_identifier = next(
                (i for i in device.get("identifier", []) if i.get("system") == FHIR.device_title_system), None
            )
            if title_identifier and title_identifier.get("value") != title:
                title_identifier["value"] = title
            elif not title_identifier:
                device.setdefault("identifier", []).append(
                    {
                        "system": FHIR.device_title_system,
                        "value": title,
                    }
                )

            # Set the tracking
            tracking_identifier = next(
                (i for i in device.get("identifier", []) if i.get("system") == FHIR.device_tracking_system), None
            )
            if not tracking and tracking_identifier:
                device["identifier"].remove(tracking_identifier)
            elif tracking_identifier and tracking_identifier.get("value") != tracking:
                tracking_identifier["value"] = tracking
            elif tracking and not tracking_identifier:
                device.setdefault("identifier", []).append(
                    {
                        "system": FHIR.device_tracking_system,
                        "value": tracking,
                    }
                )

            # Update type
            type_code = next(
                (c for c in device.get("type", {}).get("coding", []) if c.get("system") == FHIR.device_coding_system),
                None,
            )
            if type_code and type_code.get("code") != code or type_code.get("display") != display:
                type_code["code"] = code
                type_code["display"] = display
                device["type"]["text"] = display
            elif not type_code:
                device.setdefault("type", {}).setdefault("coding", []).append(
                    {
                        "system": FHIR.device_coding_system,
                        "code": code,
                        "display": display,
                    }
                )
                device["type"]["text"] = display

            # Check dates
            if shipped:
                device["manufactureDate"] = shipped.isoformat()
            elif device.get("manufactureDate"):
                del device["manufactureDate"]

            if returned:
                device["expirationDate"] = returned.isoformat()
            elif device.get("expirationDate"):
                del device["expirationDate"]

            # Get the first note
            annotation = next((n for n in device.get("note", [])), None)
            if annotation and not note:
                del device["note"]
            elif annotation and annotation.get("text") != note:
                annotation["text"] = note
            elif not annotation and note:
                device["note"] = [
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "text": note,
                    }
                ]

            return FHIR.fhir_update("Device", device["id"], device) is not None

        except Exception as e:
            logger.error(
                f"PPM/FHIR: Device update error: {e}",
                exc_info=True,
                extra={
                    "ppm_id": patient_id,
                    "id": id,
                    "study": study,
                    "code": code,
                    "url": url,
                    "response": response,
                },
            )

        return False

    @staticmethod
    def update_patient_deceased(patient_id: str, date: date = None, active: bool = None) -> bool:
        """
        Updates a participant as deceased. If a date is passed, they are marked
        as such as well as updated be being inactive. If passed, 'active' will
        update this flag on the Patient simultaneously.

        :param patient_id: The patient identifier
        :type patient_id: str
        :param date: The date of death for the Patient
        :type date: date
        :param active: The value to set on the Patient's 'active' flag
        :type active: bool
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Make the updates
        try:
            # Build the update
            if date:
                patch = [
                    {
                        "op": "replace",
                        "path": "/deceasedDateTime",
                        "value": date.isoformat(),
                    }
                ]
            else:
                patch = [{"op": "remove", "path": "/deceasedDateTime"}]

            # Update active if needed
            if active is not None:
                patch.append({"op": "replace", "path": "/active", "value": active})

            return (
                FHIR.fhir_patch(
                    path=["Patient", patient_id],
                    patch=patch,
                )
                is not None
            )

        except Exception as e:
            logger.error("FHIR Error: {}".format(e), exc_info=True, extra={"ppm_id": patient_id})

        return False

    @staticmethod
    def update_patient_enrollment(patient: Union[Patient, dict, str], status: str, study: str = None) -> bool:
        """
        Updates the Patient's enrollment status via a Flag resource(s)
        that references the Patient. If no study is passed, all enrollment Flags
        are updated for the participant. This is useful in a case like the
        participant has been reported as deceased so enrollment will be
        common throughout the set of studies they may have been participating
        in.

        :param patient: The patient object/identifier to update for
        :type patient: Union[Patient, dict, str]
        :param study: The study for which the Flag tracks enrollment, defaults to None
        :type study: Optional[str]
        :param status: The value of the enrollment status to set
        :type status: str
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        flag = None
        try:
            # Get patient identifier
            patient_id = next(iter(FHIR._patient_query(patient).values()), None)
            logger.debug(f"PPM/FHIR/{study + '/' if study else ''}" f"/{patient_id}: Enrollment -> {status}")

            # Fetch the flag(s)
            flags = FHIR.query_enrollment_flags(patient, study)

            # Iterate flags
            for flag in [Flag(f) for f in flags]:

                # Get the study
                study = PPM.Study.get(
                    next(
                        iter(
                            [
                                i.value
                                for i in flag.identifier
                                if i.system == FHIR.enrollment_flag_study_identifier_system
                            ]
                        )
                    )
                )

                # Set logging prefix
                prefix = f"PPM/FHIR/{study}/{patient_id}:"

                # Get the coding
                code = flag.code.coding[0]

                # Update flag properties for particular states.
                logger.debug(f"{prefix}: Current status: {code.code}")
                if code.code != "accepted" and status == "accepted":
                    logger.debug(f'{prefix}: Setting enrollment flag status to "active"')

                    # Set status.
                    flag.status = "active"

                    # Set a start date.
                    if flag.period and flag.period.start:

                        # Remove the end
                        flag.period.end = None

                    else:
                        now = FHIRDateTime(datetime.now(timezone.utc).isoformat())
                        period = Period()
                        period.start = now
                        flag.period = period

                elif code.code != "terminated" and status == "terminated":
                    logger.debug(f'{prefix}: Setting enrollment flag status to "terminated"')

                    # Set status.
                    flag.status = "inactive"

                    # Set an end date if a flag is present
                    if flag.period:
                        now = FHIRDateTime(datetime.now(timezone.utc).isoformat())
                        flag.period.end = now
                    else:
                        logger.debug(f"{prefix}: Flag has no period/start, cannot set end")

                elif code.code != "completed" and status == "completed":
                    logger.debug(f'{prefix}: Setting enrollment flag status to "completed"')

                    # Set status.
                    flag.status = "inactive"

                    # Set an end date if a flag is present
                    if flag.period:
                        now = FHIRDateTime(datetime.now(timezone.utc).isoformat())
                        flag.period.end = now
                    else:
                        logger.debug(f"{prefix}: Flag has no period/start, cannot set end")

                elif code.code == "accepted" and status != "accepted":
                    logger.debug(f"{prefix}: Reverting back to inactive with no dates")

                    # Flag defaults to inactive with no start or end dates.
                    flag.status = "inactive"
                    flag.period = None

                elif code.code != "ineligible" and status == "ineligible":
                    logger.debug(f"{prefix}: Setting as ineligible, inactive with no dates")

                    # Flag defaults to inactive with no start or end dates.
                    flag.status = "inactive"
                    flag.period = None

                else:
                    logger.debug(f"{prefix}: Unhandled flag update: {code.code} -> {status}")

                # Set the code.
                code.code = status
                code.display = status.title()
                flag.code.text = status.title()

                # Perform the update
                return FHIR.fhir_put(flag.as_json(), path=["Flag", flag.id]) is not None

        except Exception as e:
            logger.exception(
                "FHIR error: {}".format(e),
                exc_info=True,
                extra={
                    "patient_id": patient_id,
                    "flag": flag.as_json() if flag else None,
                },
            )

        return False

    @staticmethod
    def update_consent_composition(
        patient: Union[Patient, dict, str], study: str, document_reference_id: str = None, composition: dict = None
    ) -> bool:
        """
        Updates a participant's consent Composition resource for changes in
        related references, e.g. the DocumentReference referencing a rendered
        PDF of the signed consent.

        :param patient: The patient object/identifier to update for
        :type patient: Union[Patient, dict, str]
        :param study: The study for which this consent was signed
        :type study str
        :param document_reference_id: An updated document reference ID,
        defaults to None
        :type document_reference_id: str
        :param composition: The Composition resource, if available
        :type composition: dict
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = next(iter(FHIR._patient_query(patient).values()))
        prefix = f"PPM/FHIR/{study}/{patient_id}"
        logger.debug(f"{prefix}: Update consent composition")

        try:
            # If not composition, get it
            if not composition:
                composition = FHIR.get_consent_composition(patient=patient, study=study)

            # Get references
            references = [
                s["entry"][0]["reference"]
                for s in composition["section"]
                if s.get("entry") and s["entry"] is list and len(s["entry"]) and "reference" in s["entry"][0]
            ]
            if document_reference_id:
                for reference in references:
                    # Check type
                    if "DocumentReference" in reference:

                        # Update it
                        reference = {
                            "reference": f"DocumentReference/{document_reference_id}",
                            "display": FHIR.ppm_consent_type_display,
                        }
                        logger.debug(f"{prefix}: Updated DocumentReference: " f"{reference}")
            else:
                # Remove it if included
                sections = []
                for section in composition["section"]:
                    if "entry" in section:
                        for entry in section.get("entry", []):
                            if "reference" in entry and "DocumentReference" in entry["reference"]:
                                # Nothing to do as we want to leave it out
                                pass
                            else:
                                sections.append(section)
                    else:
                        sections.append(section)

                # Set the new sections
                composition["section"] = sections

            for reference in references:
                # Ensure study is set
                if "ResearchStudy" in reference:
                    break
            else:
                # Add it
                composition["section"].append({"reference": f"ResearchStudy/{PPM.Study.fhir_id(study)}"})

            return (
                FHIR.fhir_update(
                    resource_type="Composition",
                    resource_id=composition["id"],
                    resource=composition,
                )
                is not None
            )

        except Exception as e:
            logger.error(
                "FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": patient,
                    "document_reference_id": document_reference_id,
                },
            )

        return False

    @staticmethod
    def update_research_subject(
        research_subject_id: str, start: Union[datetime, str] = None, end: Union[datetime, str, Literal[False]] = None
    ) -> bool:
        """
        Updates a ResearchSubject resource given the passed arguments.
        For 'start' and 'end', both str and datetime are accepted, as well
        as bool False if the property should be deleted.

        :param research_subject_id: The identifier of the ResearchSubject
        :type research_subject_id: str
        :param start: The start date, defaults to None
        :type start: Union[datetime, str]
        :param end: The end date, defaults to None
        :type end: Union[datetime, str, Literal[False]]
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        content = patch = None
        try:
            logger.debug(
                f"PPM/FHIR: Update ResearchSubject: "
                f"ResearchSubject: '{research_subject_id}', Start: '{start}', "
                f"End: '{end}'"
            )

            # Prepare list of operations
            patch = []

            # Set 'start' if date is passed
            if type(start) is datetime or type(start) is str:
                patch.append(
                    {
                        "op": "update",
                        "path": "/period/start",
                        "value": start.isoformat() if type(start) is datetime else start,
                    }
                )

            elif start:
                logger.error(
                    f"PPM/FHIR: Unexpected type for 'start': {type(start)}",
                    extra={"research_subject_id": research_subject_id, "start": start, "end": end},
                )

            # Set 'end' if date is passed
            if type(end) is datetime or type(end) is str:
                patch.append(
                    {"op": "add", "path": "/period/end", "value": end.isoformat() if type(end) is datetime else end}
                )

            elif end:
                logger.error(
                    f"PPM/FHIR: Unexpected type for 'end': {type(end)}",
                    extra={"research_subject_id": research_subject_id, "start": start, "end": end},
                )

            # Delete 'end' if False is passed
            elif end is False:
                patch.append({"op": "remove", "path": "/period/end"})

            return (
                FHIR.fhir_patch(
                    path=["ResearchSubject", research_subject_id],
                    patch=patch,
                )
                is not None
            )

        except Exception as e:
            logger.error(
                f"PPM/FHIR Error: {e}",
                exc_info=True,
                extra={
                    "research_subject_id": research_subject_id,
                    "start": start,
                    "end": end,
                    "content": content,
                    "patch": patch,
                },
            )

        return False

    @staticmethod
    def update_ppm_research_subject(
        patient: Union[Patient, dict, str],
        study: str = None,
        start: Union[datetime, str] = None,
        end: Union[datetime, str, Literal[False]] = None,
    ) -> bool:
        """
        Updates a PPM ResearchSubject resource for the given Patient. If
        boolean 'False' is passed for 'end' then that property is deleted
        from the ResearchSubject resource where as passing 'None' leaves it
        untouched.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param study: The PPM study this resource related to, defaults to None
        :type study: str, optional
        :param start: The start date, defaults to None
        :type start: Union[datetime, str], optional
        :param end: The end date, defaults to None
        :type end: Union[datetime, str, Literal[False]], optional
        :return: Whether the operation succeeded or not
        :rtype: bool
        """

        # Build the query
        query = FHIR._patient_resource_query(patient)

        # Get patient ID
        patient_id = next(iter(FHIR._patient_query(patient).values()))
        prefix = f"PPM/FHIR/{study}/{patient_id}"
        logger.debug(f"{prefix}: Update PPM ResearchSubject: {locals()}")

        # Build study identifier
        query["identifier"] = f"{FHIR.research_subject_study_identifier_system}|"
        if study:
            query["identifier"] += PPM.Study.fhir_id(study)

        research_subject_id = None
        success = True
        try:
            # Fetch the research subject.
            research_subjects = FHIR._query_resources("ResearchSubject", query=query)

            # Iterate resources
            for research_subject in research_subjects:
                research_subject_id = research_subject["id"]
                logger.debug(f"{patient}: Updating ResearchSubject/{research_subject_id}")

                # Only clear 'end' if it exists
                if not research_subject.get("period", {}).get("end") and end is False:
                    research_subject_end = None
                else:
                    research_subject_end = end

                # Do the update
                if not FHIR.update_research_subject(
                    research_subject_id=research_subject_id, start=start, end=research_subject_end
                ):
                    logger.error(f"{prefix}: Could not update ResearchSubject/" f"{research_subject_id}")

                    # Mark it as failed
                    success = False

            return success

        except Exception as e:
            logger.error(
                "PPM/FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": patient,
                    "study": study,
                    "start": start,
                    "end": end,
                    "research_subject_id": research_subject_id,
                },
            )

        return False

    @staticmethod
    def update_points_of_care_list(patient: Union[Patient, dict, str], points_of_care: list[str]) -> list[str]:
        """
        Adds a point of care to a Participant's existing list and returns the
        flattened updated list of points of care (just a list with the name of
        the Organization). Will return the existing list if the point of care
        is already in the list. Will look for an existing Organization before
        creating.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param point_of_care: A list of points of care names to add
        :type point_of_care: list[str]
        :returns: A list of the current points of care for the participant
        :rtype: list[str]
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Update PPM List: {locals()}")

        bundle = points_of_care_list = None
        try:
            # Get the list and related organizations
            resources = FHIR.get_point_of_care_list(patient, flatten_return=False)

            # Extract resources
            organizations = [r for r in resources if r["resourceType"] == "Organization"]
            points_of_care_list = next((r for r in resources if r["resourceType"] == "List"), None)

            # Copy argument
            points_of_care_to_add = points_of_care.copy()

            # Create if it doesn't exist
            if not points_of_care_list:

                # Set the list to persist
                logger.debug(f"{prefix}: List doesn't exist, will create")
                FHIR.create_point_of_care_list(patient, points_of_care)
                return points_of_care

            # Check if the name exists in the list already
            for organization in [o["name"] for o in organizations]:
                if organization in points_of_care:
                    logger.debug(f'{prefix}: "{organization}" is already in List')

                    # Pop it
                    points_of_care_to_add.remove(organization)

            # Check for empty list
            if not points_of_care_to_add:
                logger.debug(f"{prefix}: No remaining additions to List, returning")
                return points_of_care

            # Start a bundle request
            bundle = Bundle()
            bundle.entry = []
            bundle.type = "transaction"

            list_request = BundleEntryRequest()
            list_request.method = "PUT"
            list_request.url = "List/{}".format(points_of_care_list["id"])

            # Add Organization objects to bundle.
            for point_of_care in points_of_care_to_add:

                # Create the organization
                organization = Organization()
                organization.name = point_of_care
                organization_id = uuid.uuid1().urn

                organization_request = BundleEntryRequest()
                organization_request.method = "POST"
                organization_request.url = "Organization"

                organization_entry = BundleEntry()
                organization_entry.resource = organization
                organization_entry.fullUrl = organization_id
                organization_entry.request = organization_request

                # Add it to the transaction
                bundle.entry.append(organization_entry)

                # Add it
                points_of_care_list["entry"].append(
                    {
                        "item": {"reference": organization_id},
                    }
                )

            # Add List object to bundle.
            list_entry = BundleEntry()
            list_entry.resource = FHIRList(points_of_care_list)
            list_entry.request = list_request

            # Add the updated List to the transaction
            bundle.entry.append(list_entry)

            # Post the transaction
            success = FHIR.fhir_transaction(bundle.as_json())

            # Return whether it succeeded or not
            existing_points_of_care = [o["name"] for o in organizations]
            if success:
                return existing_points_of_care + points_of_care_to_add
            else:

                # Return the original list since the update failed
                return existing_points_of_care

        except Exception as e:
            logger.error(
                "PPM/FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": patient,
                    "points_of_care": points_of_care,
                    "points_of_care_list": points_of_care_list,
                    "bundle": bundle,
                },
            )

    @staticmethod
    def update_twitter(patient: Union[Patient, dict, str], handle: str = None, uses_twitter: bool = None) -> bool:
        """
        Accepts details of a Twitter integration and updates the Patient record.
        A handle automatically sets the 'uses-twitter' extension as true, whereas
        no handle and no value for 'uses-twitter' deletes the extension and the
        handle from the Patient.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param handle: The user's Twitter handle, defaults to None
        :type handle: Optional[bool]
        :param uses_twitter: The flag to set for whether the user has opted
        out of the integration, defaults to None
        :type uses_twitter: Optional[bool]
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Update Twitter: {locals()}")

        try:
            # Fetch the Patient.
            resource = FHIR.get_patient(patient)

            # Check if handle submitted or not
            if handle:

                # Set the value
                twitter = {
                    "system": FHIR.patient_twitter_telecom_system,
                    "value": "https://twitter.com/" + handle,
                }

                # Add it to their contact points
                resource.setdefault("telecom", []).append(twitter)

            else:
                # Check for existing handle and remove it
                for telecom in resource.get("telecom", []):
                    if "twitter.com" in telecom["value"]:
                        resource["telecom"].remove(telecom)

            # Check for an existing Twitter status extension
            extension = next(
                (extension for extension in resource.get("extension", []) if "uses-twitter" in extension.get("url")),
                None,
            )

            # See if we need to update the extension
            if handle is not None or uses_twitter is not None:

                # Set preference
                value = handle is not None or uses_twitter
                logger.debug(f'{prefix}: Updating "uses_twitter" -> {value}')

                if not extension:
                    # Add an extension indicating their use of Twitter
                    extension = {
                        "url": FHIR.twitter_extension_url,
                        "valueBoolean": value,
                    }

                    # Add it to their extensions
                    resource.setdefault("extension", []).append(extension)

                # Update the flag
                extension["valueBoolean"] = value

            elif extension:
                logger.debug(f'{prefix}: Deleting "uses_twitter" -> None')

                # Remove this extension
                resource["extension"].remove(extension)

            # Save and return
            return (
                FHIR.fhir_put(
                    resource=resource,
                    path=["Patient", resource["id"]],
                )
                is not None
            )

        except Exception as e:
            logger.error(
                "PPM/FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": resource,
                    "handle": handle,
                    "uses_twitter": uses_twitter,
                },
            )

        return False

    @staticmethod
    def update_patient_extension(
        patient: Union[Patient, dict, str],
        extension_url: str,
        value: Optional[Union[str, bool, int, datetime, date]] = None,
    ) -> bool:
        """
        Accepts an extension URL and a value and does the necessary update on
        the Patient. If None is passed for the value and the extension already
        exists, it is deleted from the Patient.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param extension_url: The URL for the extension
        :type extension_url: str
        :param value: The value to set
        :type value: Optional[Union[str, bool, int, datetime, date]]
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Update Patient extension: {locals()}")

        try:
            # Fetch the Patient.
            resource = FHIR.get_patient(patient)

            # Check for an existing Facebook status extension
            extension = next(
                (
                    extension
                    for extension in resource.get("extension", [])
                    if extension_url.lower() == extension.get("url", "").lower()
                ),
                None,
            )
            if value is not None:
                logger.debug(f"{prefix}: Updating '{extension_url}' -> '{value}'")

                # Check if an existing one was found
                if not extension:

                    # Add an extension indicating their use of Facebook
                    extension = {"url": extension_url}

                    # Add it to their extensions
                    resource.setdefault("extension", []).append(extension)

                # Check type and set the value accordingly
                if type(value) is str:
                    extension["valueString"] = value
                elif type(value) is bool:
                    extension["valueBoolean"] = value
                elif type(value) is int:
                    extension["valueInteger"] = value
                elif type(value) is datetime:
                    extension["valueDateTime"] = value.isoformat()
                elif type(value) is date:
                    extension["valueDate"] = value.isoformat()
                else:
                    logger.error(f"{prefix}: Unhandled value type " f"'{type(value)}' : '{value}'")
                    return False

            elif extension:
                logger.debug(f"{prefix}: Deleting {extension_url} -> None")

                # Remove this extension
                resource["extension"].remove(extension)

            return FHIR.fhir_put(resource=resource, path=["Patient", resource["id"]]) is not None

        except Exception as e:
            logger.error(
                "PPM/FHIR Error: {}".format(e),
                exc_info=True,
                extra={
                    "patient": patient,
                    "extension_url": extension_url,
                    "value": value,
                },
            )

        return False

    @staticmethod
    def update_picnichealth(patient: Union[Patient, dict, str], registered: bool = True) -> bool:
        """
        Updates the property on a Patient resource that tracks whether they
        have indicated that they signed up for Picnichealth or not.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param registered: The value to set for their status, defaults to True
        :type registered: bool, optional
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        return FHIR.update_patient_extension(
            patient=patient, extension_url=FHIR.picnichealth_extension_url, value=registered
        )

    @staticmethod
    def update_questionnaire_response(
        patient: Union[Patient, dict, str], questionnaire_response_id: str, questionnaire_response: dict
    ) -> bool:
        """
        Updates a participant's QuestionnaireResponse resource for the given
        Questionnaire resource.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param questionnaire_response_id: The ID of the QuestionnaireResponse to update
        :type questionnaire_response_id: str
        :param questionnaire_response: The update QuestionnaireResponse object to persist
        :type questionnaire_response: dict
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Update QuestionnaireResponse/" f"{questionnaire_response_id}")

        try:
            # Ensure the ID is set on the resource
            questionnaire_response["id"] = questionnaire_response_id

            return (
                FHIR.fhir_put(
                    resource=questionnaire_response,
                    path=["QuestionnaireResponse", questionnaire_response_id],
                )
                is not None
            )

        except Exception as e:
            logger.error(
                f"PPM/{patient}: FHIR Error: {e}",
                exc_info=True,
                extra={
                    "patient": patient,
                    "questionnaire_response_id": questionnaire_response_id,
                },
            )

        return False

    @staticmethod
    def update_or_create_questionnaire_response(
        patient: Union[Patient, dict, str], questionnaire_id: str, questionnaire_response: dict
    ) -> bool:
        """
        Updates or creates (if none exist for the given Questionnaire)
        a participant's QuestionnaireResponse resource for the given
        Questionnaire.

        :param patient: The patient's identifier
        :type patient: Union[Patient, dict, str]
        :param questionnaire_id: The ID of the Questionnaire the response was
        for
        :type questionnaire_id: str
        :param questionnaire_response: The QuestionnaireResponse object to
        persist
        :type questionnaire_response: dict
        :raises RuntimeError: If more than one QuestionnaireResponse already
        exist for the given Questionnaire
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Update/create QuestionnaireResponse for" f"{questionnaire_id}")

        questionnaire_response_id = None
        try:
            # Get the existing questionnaire response
            questionnaire_responses = FHIR.query_questionnaire_responses(
                patient=patient,
                questionnaire_id=questionnaire_id,
            )

            # Ensure only one, else raise exception
            if len(questionnaire_responses) > 1:
                raise RuntimeError(
                    f"{prefix}: Found multiple QuestionnaireResponse resources " f"for Questionnaire/{questionnaire_id}"
                )

            # Check if it exists and create if necessary
            if not questionnaire_responses:
                logger.debug(f"{prefix}: Create QuestionnaireResponse")
                return FHIR.save_questionnaire_response(
                    patient_id=patient,
                    questionnaire_id=questionnaire_id,
                    questionnaire_response=questionnaire_response,
                )

            # Get the ID
            questionnaire_response_id = next(entry.resource.id for entry in questionnaire_responses.entry)

            # Do the update
            logger.debug(f"{prefix}: Update QuestionnaireResponse/" f"{questionnaire_response_id}")
            return FHIR.update_questionnaire_response(
                patient=patient,
                questionnaire_response_id=questionnaire_response_id,
                questionnaire_response=questionnaire_response,
            )

        except Exception as e:
            logger.error(
                f"PPM/FHIR: Error: {e}",
                exc_info=True,
                extra={
                    "patient": patient,
                    "questionnaire_id": questionnaire_id,
                    "questionnaire_response_id": questionnaire_response_id,
                },
            )

        return False

    #
    # DELETE
    #

    @staticmethod
    def _delete_resources(resources: list[dict], transaction: bool = False) -> Union[bool, dict[str, bool]]:
        """
        Deletes the passed resources from FHIR as either a batch or a
        transaction. Transactions will revert to original state if any of the
        included operations fail whereas batch will delete what it can despite
        failures. If the entire operation fails or succeeds, a bool indicating
        so is returned. If some resources are deleted and others failed, a
        mapping of resource identifier to the result of the operation is
        returned.

        :param resources: A list of resources to delete in FHIR JSON format
        :type resources: list[dict]
        :param transaction: Whether to enforce the operation as a transaction,
        defaults to False
        :type transaction: bool
        :return: If the entire operation fails or succeeds, a bool indicating
        so is returned. If some resources are deleted and others failed, a
        mapping of resource identifier to the result of the operation is
        returned.
        :rtype: Union[bool, dict[str, bool]]
        """
        # Ensure they follow convention
        bundle = results = None
        try:
            # Build list of resource identifiers
            resource_identifiers = [f"{r['resourceType']}/{r['id']}" for r in resources]
            logger.debug(f"PPM/FHIR: Deleting resources: {', '.join(resource_identifiers)}")

            # Build the initial delete transaction bundle.
            bundle = {"resourceType": "Bundle", "type": "transaction" if transaction else "batch", "entry": []}

            # Iterate resource identifiers
            for resource_identifier in resource_identifiers:

                # Add it the request
                bundle["entry"].append({"request": {"url": resource_identifier, "method": "DELETE"}})

            # Make the request
            results = FHIR.fhir_transaction(bundle)

            # No bother parsing results for transaction
            if transaction:
                return results is not None

            # Parse the response
            resource_results = {}
            for index, response in enumerate(results["entry"]):

                # Add it to the results
                status = response.get("response", {}).get("status")

                # Add the result
                resource_results[resource_identifiers[index]] = status and status == "200 OK"

                # Log it if failed or unexpected
                if not status:

                    # Add whatever the entry was
                    logger.error(f"PPM/FHIR: Failed delete: {response}")

            return resource_results

        except Exception as e:
            logger.exception(
                "PPM/FHIR: Delete error: {}".format(e),
                exc_info=True,
                extra={
                    "bundle": bundle,
                    "results": results,
                },
            )

        return False

    @staticmethod
    def delete_participant(patient: Union[Patient, dict, str], study: str) -> bool:
        """
        Removes the participant from the passed study. This will delete
        the Patient resource if and only if that Patient is not linked to
        another study. Regardless, all resources related to the Patient
        and the passed study will be removed. Including the following:

        - ResearchSubject:individual
        - Flag:subject
        - DocumentReference:subject
        - QuestionnaireResponse:source
        - Composition:subject
        - Consent:patient
        - Contract:signer
        - List:subject
        - Device:patient
        - Communication:subject
        - RelatedPerson:patient

        # [ ]: Configure this method to handle multi-study participants

        :param patient: The Patient ID/object to delete
        :type patient: Union[Patient, dict, str]
        :param study: The study for which resources should be deleted
        :type study: str
        :return: Whether the delete succeeded or not
        :rtype: bool
        """
        results = patient_id = transaction = None
        try:
            # Get the participant and all of their resources
            participant = FHIR.get_participant(patient=patient, study=study)
            patient_id = FHIR._find_resource(participant, "Patient")["id"]
            logger.debug(f"PPM/FHIR: Deleting participant {study}/{patient_id}")

            # Only delete resources related to Patient
            resource_types = [r.split(":", 1)[0] for r in FHIR.PARTICIPANT_PATIENT_REVINCLUDES]
            resources = [r["resource"] for r in participant["entry"] if r["resource"]["resourceType"] in resource_types]

            # Build the initial delete transaction bundle.
            transaction = {"resourceType": "Bundle", "type": "transaction", "entry": []}

            # Iterate resources to be deleted
            for resource in resources:

                # Add it.
                transaction["entry"].append(
                    {"request": {"url": f"{resource['resourceType']}/{resource['id']}", "method": "DELETE"}}
                )

            # Add the Patient last
            transaction["entry"].append({"request": {"url": f"Patient/{patient_id}", "method": "DELETE"}})

            logger.debug(f"PPM/FHIR: Delete request: {libjson.dumps(transaction)}")

            # Do the delete.
            results = FHIR.fhir_transaction(transaction)

            # Log it.
            logger.debug("PPM/FHIR: Delete response: {}".format(results))

            return results is not None

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Delete error: {e}",
                exc_info=True,
                extra={
                    "patient": patient_id,
                    "transaction": transaction,
                    "results": results,
                },
            )

        return False

    @staticmethod
    def delete_research_subjects(patient: Union[Patient, dict, str]) -> bool:
        """
        Deletes all ResearchSubject resources related to the Patient
        but that are not related to a PPM study. The deletion is processed
        as a transaction so they will either all be deleted or non will be
        deleted if an error is encountered.

        :param patient: The Patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :returns: Whether the operation succeeded or not
        :return: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Delete non-PPM ResearchSubjects")

        # Find them
        research_subjects = FHIR.query_research_subjects(patient=patient, flatten_return=False)
        if not research_subjects:
            logger.warning(f"{prefix}: No non-PPM ResearchSubjects exist")
            return False

        # Delete them all
        return FHIR._delete_resources(
            resources=research_subjects,
            transaction=True,
        )

    @staticmethod
    def delete_point_of_care_list(patient: Union[Patient, dict, str]) -> bool:
        """
        Deletes the Patient's points of care List resource.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :returns: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{patient_id}"
        logger.debug(f"{prefix}: Delete points of care List")

        # Find it
        point_of_care_list = FHIR.get_point_of_care_list(
            patient=patient,
            flatten_return=False,
        )
        if not point_of_care_list:
            logger.warning(f"{prefix}: Point of Care List does not exist")
            return False

        # Attempt to delete the List resource.
        return FHIR.fhir_delete_resource(resource_type="List", resource_id=point_of_care_list["id"]) is not None

    @staticmethod
    def delete_consent(patient: Union[Patient, dict, str], study: str) -> bool:
        """
        Deletes the Composition and all other related resources that are
        created in relation to the consenting process in PPM. This includes
        Consent, Contract, and any QuestionnaireResponse resources that
        were filled out during the consent process.

        :param patient: The patient object/identifier to query on
        :type patient: Union[Patient, dict, str]
        :param study: The identifier of the PPM study this consent was for
        :type study: str
        :return: Whether the operation succeeded or not
        :rtype: bool
        """
        # Get patient ID
        patient_id = FHIR.find_patient_identifier(patient)
        prefix = f"PPM/FHIR/{study}/{patient_id}"
        logger.debug(f"{prefix}: Delete consent Composition")

        # Get Composition and all referenced resources
        participant = FHIR.get_participant(patient, study)

        # Build the transaction
        transaction = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [],
        }

        # Find the composition
        composition = FHIR._find_resource(participant, "Composition")

        # Add the Composition itself
        transaction["entry"].append(
            {
                "request": {
                    "url": f"Composition/{composition['id']}",
                    "method": "DELETE",
                }
            }
        )

        # Add linked resources
        for entry in composition["entry"]:

            # Add the referenced resource(s) to be deleted
            for reference in entry:
                transaction["entry"].append(
                    {
                        "request": {
                            "url": reference["reference"],
                            "method": "DELETE",
                        }
                    }
                )

        # Determine what QuestionnaireResponse resources to delete
        ppm_study = PPM.Study.get(study)
        if ppm_study is PPM.Study.ASD:

            questionnaire_ids = [
                "ppm-asd-consent-guardian-quiz",
                "ppm-asd-consent-individual-quiz",
                "individual-signature-part-1",
                "guardian-signature-part-1",
                "guardian-signature-part-2",
                "guardian-signature-part-3",
            ]

        elif ppm_study is PPM.Study.NEER:

            # Delete questionnaire responses
            questionnaire_ids = ["neer-signature", "neer-signature-v2", "neer-signature-v3"]

        elif ppm_study is PPM.Study.RANT:

            # Delete questionnaire responses
            questionnaire_ids = [
                "rant-signature",
            ]

        elif ppm_study is PPM.Study.EXAMPLE:

            # Delete questionnaire responses
            questionnaire_ids = [
                "example-signature",
            ]

        # Get all QuestionnaireResponse objects
        questionnaire_responses = FHIR._find_resources(participant, "QuestionnaireResponse")

        # Add the questionnaire response delete
        for questionnaire_id in questionnaire_ids:

            # Find QuestionnaireResponse
            questionnaire_response = next(
                (
                    r
                    for r in questionnaire_responses
                    if r["questionnaire"].endswith(f"Questionnaire/{questionnaire_id}")
                ),
                None,
            )

            # Add it to be deleted
            if questionnaire_response:
                transaction["entry"].append(
                    {
                        "request": {
                            "url": f"QuestionnaireResponse/{questionnaire_response['id']}",
                            "method": "DELETE",
                        }
                    }
                )

        # Make the FHIR request.
        results = FHIR.fhir_transaction(transaction)

        return results is not None

    #
    # BUNDLES
    #

    @staticmethod
    def find_research_studies(
        bundle: dict, ppm: bool = None, flatten_result: bool = True
    ) -> Union[list[dict], list[str]]:
        """
        Find and returns the set of ResearchStudy resources in the passed
        bundle. The `ppm` argument is used to determine if PPM-related
        ResearchStudy resources should be exclusively returned or excluded
        from the returned ResearchStudy resources. If the `flatten_result`
        argument is passed, only a list of the ResearchStudy names will be
        returned.

        :param bundle: The bundle containing all participant resources
        :type bundle: dict
        :param ppm: Determines whether to only return or exclude PPM-related
        ResearchStudy resources, defaults to None
        :type ppm: bool, optional
        :param flatten_result: Whether to flatten the result or not,
        defaults to True
        :type flatten_result: bool, optional
        :return: Either a list of ResearchStudy resources or a list of the
        ResearchStudy names
        :rtype: Union[list[dict], list[str]]
        """

        # Find Research subjects
        subjects = FHIR.find_research_subjects(bundle, ppm, flatten_result=False)
        if not subjects:
            logger.debug("No Research Subjects, no Research Studies")
            return None

        # Get study IDs
        research_study_ids = [subject["study"]["reference"].split("/")[1] for subject in subjects]

        # Check bundle first
        research_studies = [e for e in bundle["entry"] if e.get("resource", {}).get("id") in research_study_ids]

        # Make the query for any missing ResearchStudy resources
        missing_research_study_ids = [
            i for i in research_study_ids if i not in [r["resource"]["id"] for r in research_studies]
        ]
        if missing_research_study_ids:
            logger.debug(f"PPM/FHIR: Bundle missing ResearchStudy/" f"({', '.join(missing_research_study_ids)})")

            # Build the URL
            research_study_url = furl(PPM.fhir_url())
            research_study_url.path.add("ResearchStudy")
            research_study_url.query.params.add(
                key="_id",
                value=",".join(missing_research_study_ids),
            )

            # Fetch them
            research_study_response = FHIR.get(research_study_url.url)

            # Add them to the existing list
            research_studies.extend(research_study_response.json().get("entry", []))

        if flatten_result:
            # Return the titles
            return [research_study["resource"]["title"] for research_study in research_studies]
        else:
            return [research_study["resource"] for research_study in research_studies]

    @staticmethod
    def find_research_subjects(bundle: dict, ppm: bool = None, flatten_result: bool = True) -> list[dict]:
        """
        Find and returns the set of ResearchSubject resources in the passed
        bundle. The `ppm` argument is used to determine if PPM-related
        ResearchSubject resources should be exclusively returned or excluded
        from the returned ResearchSubject resources. If the `flatten_result`
        argument is passed, only a list of simplified dicts containing
        important properties of the ResearchSubject will be returned.

        :param bundle: The bundle containing all participant resources
        :type bundle: dict
        :param ppm: Determines whether to only return or exclude PPM-related
        ResearchStudy resources, defaults to None
        :type ppm: bool, optional
        :param flatten_result: Whether to flatten the result or not,
        defaults to True
        :type flatten_result: bool, optional
        :return: Either a list of ResearchSubject resources or a list of the
        simplified ResearchSubject objects
        :rtype: list[dict]
        """
        # Find ResearchSubject resources depending on arguments
        research_subjects = FHIR.find_resources(
            resource=bundle,
            resource_types=["ResearchSubject"],
        )
        if ppm:
            research_subjects = [r for r in research_subjects if FHIR.is_ppm_research_subject(r)]
        elif ppm is False:
            research_subjects = [r for r in research_subjects if not FHIR.is_ppm_research_subject(r)]

        if flatten_result:
            return [FHIR.flatten_research_subject(resource) for resource in research_subjects]
        else:
            return [resource for resource in research_subjects]

    #
    # OUTPUT
    #

    @staticmethod
    def get_name(patient: Union[dict, Patient], full: bool = False) -> str:
        """
        Given a Patient resource, assemble and return their name as a string.

        :param patient: The Patient resource
        :type patient: Union[dict, Patient]
        :param full: Whether to return their full name or not, defaults to False
        :type full: bool, optional
        :return: The Patient's name as a string
        :rtype: str
        """
        # Check type
        if type(patient) is Patient:
            patient = patient.as_json()

        # Default to a generic name
        names = []

        # Check official names
        for name in [name for name in patient["name"] if name.get("use") == "official"]:
            if name.get("given"):
                names.extend(name["given"])

            # Add family if full name
            if name.get("family") and (full or not names):
                names.append(name["family"])

        if not names:
            logger.error("Could not find name for {}".format(patient.id))

            # Default to their email address
            email = next(
                (
                    identifier["value"]
                    for identifier in patient["identifier"]
                    if identifier.get("system") == FHIR.patient_email_identifier_system
                ),
                None,
            )

            if email:
                names.append(email)

            else:
                logger.error("Could not find email for {}".format(patient.id))

        if not names:
            names = ["Participant"]

        return " ".join(names)

    @staticmethod
    def flatten_participant(
        bundle: Union[dict, Bundle], study: str = None, questionnaires: dict[str, dict] = None
    ) -> dict:
        """
        Accepts a Bundle containing everything related to a Patient resource
        and flattens the data into something easier to build templates/views with.

        :param bundle: The bundle of all a participant's resources
        :type bundle: Union[dict, Bundle]
        :param study: The study for which this participant's record should be
        constructed
        :type study: str, defaults to None
        :param questionnaires: The survey/questionnaires for the study
        :type questionnaires: dict[str, dict], defaults to None
        :return: A flattened dictionary of the participant's entire
        FHIR data record
        :rtype: dict
        """
        # Check type
        if type(bundle) is Bundle:
            bundle = bundle.as_json()

        # Build a dictionary
        participant = {}

        # Set aside common properties
        ppm_id = None
        email = None

        try:
            # Flatten patient profile
            participant = FHIR.flatten_patient(bundle)
            if not participant:
                logger.debug("No Patient in bundle")
                return {}

            # Get props
            ppm_id = participant["fhir_id"]
            email = participant["email"]

            ####################################################################
            # Study resource IDs
            ####################################################################

            participant["studies"] = FHIR._flatten_study_resource_ids(bundle)

            ####################################################################
            # Study
            ####################################################################

            # Get the PPM study/project resources
            studies = FHIR.flatten_ppm_studies(bundle)

            # Ensure they are in this study
            if study and not next((s for s in studies if s["study"] == study), None):
                logger.error(
                    f"PPM/{ppm_id}: Participant no in study: {study}",
                    extra={"study": study, "ppm_id": ppm_id, "studies": studies},
                )
                raise ValueError(f"Participant does not exist in study {study}")

            # If they're in multiple studies, ensure the specific study is defined
            elif not study and len(studies) > 1:
                logger.error(
                    f"PPM/{ppm_id}: Multiple PPM studies: {studies}",
                    extra={"study": study, "ppm_id": ppm_id, "studies": studies},
                )
                raise ValueError("Participant has multiple studies but requested study has not been defined")

            # If study wasn't passed, get it from the single entry list
            elif not study:

                # Get the study from the bundle
                study = studies[0]["study"]

            # Validate it
            study = PPM.Study.enum(study).value

            ####################################################################
            # Enrollment
            ####################################################################

            # Check for accepted and a start date
            participant["project"] = participant["study"] = study
            participant["date_registered"] = FHIR._format_date(studies[0]["start"], "%m/%d/%Y")
            participant["datetime_registered"] = studies[0]["start"]

            # Get the enrollment properties
            enrollment = FHIR.flatten_enrollment(bundle)

            # Set status and dates
            participant["enrollment"] = enrollment["enrollment"]
            participant["date_enrollment_updated"] = FHIR._format_date(enrollment["updated"], "%m/%d/%Y")
            participant["datetime_enrollment_updated"] = enrollment["updated"]
            if enrollment.get("start"):

                # Convert time zone to assumed ET
                participant["enrollment_accepted_date"] = FHIR._format_date(enrollment["start"], "%m/%d/%Y")

            else:
                participant["enrollment_accepted_date"] = ""

            # Check for completed/terminated
            if enrollment.get("end"):

                # Convert time zone to assumed ET
                participant["enrollment_terminated_date"] = FHIR._format_date(enrollment["end"], "%m/%d/%Y")
            #
            # else:
            #     participant['enrollment_terminated_date'] = ''

            ####################################################################
            # Consent
            ####################################################################

            # Flatten consent composition
            participant["composition"] = FHIR.flatten_consent_composition(bundle)

            ####################################################################
            # Questionnaires
            ####################################################################

            # Collect flattened questionnaires
            participant["questionnaires"] = {}

            # If not specified, use the value hard-coded in the PPM module
            if not questionnaires:
                eligibility_questionnaire_id = PPM.Questionnaire.questionnaire_for_study(study=study)
                logger.warning(
                    f"PPM/{study}/{ppm_id}: Using deprecated PPM.Questionnaire eligibility questionnaires: "
                    f" {eligibility_questionnaire_id}"
                )
            else:
                # Get needed questionnaire IDs
                eligibility_questionnaire_id = next(
                    (q["questionnaire_id"] for q in questionnaires if q.get("eligibility_for") == study),
                    PPM.Questionnaire.questionnaire_for_study(study=study),
                )

            # Handle eligibility questionnaire
            logger.debug(f"PPM/{study}/{ppm_id}: Eligibility questionnaire: {eligibility_questionnaire_id}")
            questionnaire = FHIR.flatten_questionnaire_response(bundle, eligibility_questionnaire_id)
            participant["questionnaire"] = participant["questionnaires"][eligibility_questionnaire_id] = questionnaire

            # If not specified, use hard-coded questionnaire IDs from PPM module
            if not questionnaires:
                questionnaire_ids = [q.value for q in PPM.Questionnaire.extra_questionnaires_for_study(study=study)]
                logger.warning(
                    f"PPM/{study}/{ppm_id}: Using deprecated PPM.Questionnaire questionnaires: " f" {questionnaire_ids}"
                )
            else:
                questionnaire_ids = [q["questionnaire_id"] for q in questionnaires if q.get("questionnaire_id")]

            # Parse remaining questionnaires
            logger.debug(f"PPM/{study}/{ppm_id}: Study questionnaires: {questionnaire_ids}")
            for questionnaire_id in questionnaire_ids:

                # Parse it and add it
                participant["questionnaires"][questionnaire_id] = FHIR.flatten_questionnaire_response(
                    bundle, questionnaire_id
                )

            ####################################################################
            # Points of care
            ####################################################################

            # Flatten points of care
            participant["points_of_care"] = FHIR.flatten_list(bundle, "Organization")

            ####################################################################
            # Devices
            ####################################################################

            # Flatten consent composition
            participant["devices"] = FHIR.flatten_ppm_devices(bundle)

            ####################################################################
            # Research Studies
            ####################################################################

            # Check for research studies
            research_studies = FHIR.find_research_studies(bundle, ppm=False)
            if research_studies:
                participant["research_studies"] = research_studies

            ####################################################################
            # Study-sepcific Resources
            ####################################################################

            # Get study specific resources
            if hasattr(FHIR, f"_flatten_{study}_participant"):

                # Run it
                values, study_values = getattr(FHIR, f"_flatten_{study}_participant")(
                    bundle=bundle,
                    ppm_id=ppm_id,
                    questionnaires=questionnaires,
                )

                # Set them
                participant.update(values)
                participant[study] = study_values

        except Exception as e:
            logger.exception(
                "FHIR error: {}".format(e),
                exc_info=True,
                extra={"study": study, "ppm_id": ppm_id, "email": email},
            )

        return participant

    @staticmethod
    def _flatten_study_resource_ids(bundle: dict) -> dict:
        """
        This method builds a dictionary mapping each PPM study found
        in the participant's bundle to a set of resource IDs are often
        updated as the participant moves through the study. This allows
        quick access to these resources for updates.

        :param bundle: The current participant's bundle of resources
        :type bundle: dict
        :return: A mapping of PPM study codes to a dict of resource IDs
        :rtype: dict
        """
        # Track resource IDs in 'studies' dict
        studies = {}

        # For each study, retain IDs of oft-updated resources
        enrollment_flags = FHIR.find_resources(resource=bundle, resource_types=["Flag"])
        research_subjects = FHIR.find_resources(
            resource=bundle,
            resource_types=["ResearchSubject"],
            filter=lambda r: FHIR.get_study_from_research_subject(r),
        )
        for research_subject in research_subjects:

            # Get study
            research_subject_study = FHIR.get_study_from_research_subject(research_subject)

            # Get flag
            enrollment_flag = next(
                (
                    f
                    for f in enrollment_flags
                    if next(
                        (
                            i
                            for i in f.get("identifier", [])
                            if i["system"] == FHIR.enrollment_flag_study_identifier_system
                            and i["value"] == PPM.Study.fhir_id(research_subject_study)
                        ),
                        None,
                    )
                ),
                None,
            )

            # Stash IDs
            studies.setdefault(
                research_subject_study,
                {
                    "flag": enrollment_flag["id"],
                    "researchsubject": research_subject["id"],
                },
            )

        return studies

    @staticmethod
    def _flatten_asd_participant(bundle: dict, ppm_id: str, questionnaires: dict = None) -> tuple[dict, dict]:
        """
        Continues flattening a participant by adding any study specific data to
        their record. This will include answers in questionnaires, etc. Returns
        a dictionary to merge into the root participant dictionary as well as
        a dictionary that will be keyed by the study value.

        :param bundle: The participant's entire FHIR record
        :type bundle: dict
        :param ppm_id: The PPM ID of the participant
        :type ppm_id: str
        :param questionnaires: The survey/questionnaires for the study
        :type questionnaires: dict, defaults to None
        :returns: A tuple of properties for the root participant object, and for
        the study sub-object
        :rtype: tuple[dict, dict]
        """
        logger.debug(f"PPM/{ppm_id}/FHIR: Flattening ASD participant")

        # Put values and study values in dictionaries
        values = {}
        study_values = {}

        # Initially none
        values["consent_quiz"] = None
        values["consent_quiz_answers"] = None

        # Check if they've even consented
        composition = FHIR.flatten_consent_composition(bundle)
        if composition:

            # Get the Questionnaire ID used for the quiz portion of the consent
            quiz_id = PPM.Questionnaire.questionnaire_for_consent(composition)

            # Flatten the Q's and A's for output
            quiz = FHIR.flatten_questionnaire_response(bundle, quiz_id)
            if quiz:

                # Add it
                values["consent_quiz"] = quiz
                values["consent_quiz_answers"] = FHIR._asd_consent_quiz_answers(bundle, quiz_id)

        return values, study_values

    @staticmethod
    def _flatten_neer_participant(bundle: dict, ppm_id: str, questionnaires: dict = None) -> tuple[dict, dict]:
        """
        Continues flattening a participant by adding any study specific data to
        their record. This will include answers in questionnaires, etc. Returns
        a dictionary to merge into the root participant dictionary as well as
        a dictionary that will be keyed by the study value.

        :param bundle: The participant's entire FHIR record
        :type bundle: dict
        :param ppm_id: The PPM ID of the participant
        :type ppm_id: str
        :param questionnaires: The survey/questionnaires for the study
        :type questionnaires: dict, defaults to None
        :returns: A tuple of properties for the root participant object, and for
        the study sub-object
        :rtype: tuple[dict, dict]
        """
        logger.debug(f"PPM/FHIR/{ppm_id}: Flattening NEER participant")

        # Put values and study values in dictionaries
        values = {}
        study_values = {}

        # Get questionnaire answers
        questionnaire_response = next(
            (
                q
                for q in FHIR._find_resources(bundle, "QuestionnaireResponse")
                if q["questionnaire"].endswith(f"Questionnaire/{PPM.Questionnaire.NEERQuestionnaire.value}")
            ),
            None,
        )
        if questionnaire_response:
            logger.debug(f"PPM/{ppm_id}/FHIR: Flattening QuestionnaireResponse/" f'{questionnaire_response["id"]}')

            # Map linkIds to keys
            text_answers = {
                "question-12": "diagnosis",
                "question-24": "pcp",
                "question-25": "oncologist",
            }

            date_answers = {
                "question-5": "birthdate",
                "question-14": "date_diagnosis",
            }

            # Iterate items
            for link_id, key in text_answers.items():
                try:
                    # Get the answer
                    answer = next(
                        i["answer"][0]["valueString"] for i in questionnaire_response["item"] if i["linkId"] == link_id
                    )

                    # Assign it
                    study_values[key] = answer
                except Exception as e:
                    logger.exception(
                        f"PPM/{ppm_id}/Questionnaire/{link_id}: {e}",
                        exc_info=True,
                        extra={
                            "ppm_id": ppm_id,
                            "link_id": link_id,
                            "key": key,
                            "questionnaire_response": f"QuestionnaireResponse/" f'{questionnaire_response["id"]}',
                            "item": next(
                                (i for i in questionnaire_response["item"] if i["linkId"] == link_id),
                                "",
                            ),
                        },
                    )

                    # Assign default value
                    study_values[key] = "---"

            # Iterate date items and attempt to parse dates, otherwise treat as text
            for link_id, key in date_answers.items():

                try:
                    # Get the answer
                    answer = next(i["answer"][0] for i in questionnaire_response["item"] if i["linkId"] == link_id)

                    try:
                        # Check type
                        if answer.get("valueDate") or answer.get("valueDateTime"):
                            # Date is already a date object, assign it
                            study_values[key] = answer.get("valueDate", answer.get("valueDateTime"))

                        elif answer.get("valueString"):

                            # Attempt to parse it
                            answer_date = parse(answer.get("valueString"))

                            # Assign it
                            study_values[key] = answer_date.isoformat()

                        else:
                            logger.error(f"PPM/{ppm_id}/Questionnaire/{link_id}: Unhandled answer type: {answer}")

                    except ValueError:
                        logger.debug(f"PPM/{ppm_id}/Questionnaire/{link_id}: Invalid date: {answer}")

                        # Assign the raw value
                        study_values[key] = answer

                except Exception as e:
                    logger.exception(
                        f"PPM/{ppm_id}/Questionnaire/{link_id}: {e}",
                        exc_info=True,
                        extra={
                            "ppm_id": ppm_id,
                            "link_id": link_id,
                            "key": key,
                            "questionnaire_response": f"QuestionnaireResponse/" f'{questionnaire_response["id"]}',
                            "item": next(
                                (i for i in questionnaire_response["item"] if i["linkId"] == link_id),
                                "",
                            ),
                        },
                    )

                    # Assign default value
                    study_values[key] = "---"

        return values, study_values

    @staticmethod
    def _flatten_rant_participant(bundle: dict, ppm_id: str, questionnaires: dict = None) -> tuple[dict, dict]:
        """
        Continues flattening a participant by adding any study specific data to
        their record. This will include answers in questionnaires, etc. Returns
        a dictionary to merge into the root participant dictionary as well as
        a dictionary that will be keyed by the study value.

        :param bundle: The participant's entire FHIR record
        :type bundle: dict
        :param ppm_id: The PPM ID of the participant
        :type ppm_id: str
        :param questionnaires: The survey/questionnaires for the study
        :type questionnaires: dict, defaults to None
        :returns: A tuple of properties for the root participant object, and for
        the study sub-object
        :rtype: tuple[dict, dict]
        """
        logger.debug(f"PPM/{ppm_id}/FHIR: Flattening RANT participant")

        # Put values and study values in dictionaries
        values = {}
        study_values = {}

        # Check for questionnaires
        if questionnaires:

            # Get needed questionnaire IDs
            points_of_care_questionnaire_id = next(
                (q["questionnaire_id"] for q in questionnaires if q.get("points_of_care_for") == PPM.Study.RANT.value),
                None,
            )

            # Add them
            study_values["points_of_care"] = FHIR._flatten_rant_points_of_care(
                bundle=bundle,
                ppm_id=ppm_id,
                questionnaire_id=points_of_care_questionnaire_id,
            )

        return values, study_values

    @staticmethod
    def _flatten_example_participant(bundle: dict, ppm_id: str, questionnaires: dict = None) -> tuple[dict, dict]:
        """
        Continues flattening a participant by adding any study specific data to
        their record. This will include answers in questionnaires, etc. Returns
        a dictionary to merge into the root participant dictionary as well as
        a dictionary that will be keyed by the study value.

        :param bundle: The participant's entire FHIR record
        :type bundle: dict
        :param ppm_id: The PPM ID of the participant
        :type ppm_id: str
        :param questionnaires: The survey/questionnaires for the study
        :type questionnaires: dict, defaults to None
        :returns: A tuple of properties for the root participant object, and for
        the study sub-object
        :rtype: tuple[dict, dict]
        """
        logger.debug(f"PPM/{ppm_id}/FHIR: Flattening EXAMPLE participant")

        # Put values and study values in dictionaries
        values = {}
        study_values = {}

        # Check for passed questionnaires
        if questionnaires:

            # Get needed questionnaire IDs
            points_of_care_questionnaire_id = next(
                (
                    q["questionnaire_id"]
                    for q in questionnaires
                    if q.get("points_of_care_for") == PPM.Study.EXAMPLE.value
                ),
                None,
            )

            # Add them
            study_values["points_of_care"] = FHIR._flatten_rant_points_of_care(
                bundle=bundle,
                ppm_id=ppm_id,
                questionnaire_id=points_of_care_questionnaire_id,
            )

        return values, study_values

    @staticmethod
    def _flatten_rant_points_of_care(bundle: dict, ppm_id: str, questionnaire_id: str) -> list[str]:
        """
        Extracts points of care from a RANT participant's set of resources
        since they were recorded in multiple locations.

        :param bundle: The participant's entire FHIR record
        :type bundle: dict
        :param ppm_id: The PPM ID of the participant
        :type ppm_id: str
        :param questionnaire_id: The questionnaire ID containing points of care
        :type questionnaire_id: str
        :returns: A list of points of care parsed from questionnaire
        :rtype: list
        """
        # Set a list
        points_of_care = []

        # Get questionnaire answers
        questionnaire_response = FHIR.find_resource(
            resource=bundle,
            resource_type="QuestionnaireResponse",
            filter=lambda r: r["questionnaire"].endswith(f"Questionnaire/{questionnaire_id}"),
        )
        if not questionnaire_response or not questionnaire_response.get("item"):
            logger.debug(f"PPM/FHIR/{questionnaire_id}/{ppm_id}: No response items")
            return None

        # Parse answers
        diagnosing_name = FHIR.get_questionnaire_response_item_value(
            questionnaire_response=questionnaire_response,
            link_id="question-1",
        )
        diagnosing_address = FHIR.get_questionnaire_response_item_value(
            questionnaire_response=questionnaire_response,
            link_id="question-2",
        )
        diagnosing_phone = FHIR.get_questionnaire_response_item_value(
            questionnaire_response=questionnaire_response,
            link_id="question-3",
        )

        # Add it.
        points_of_care.append(f"{diagnosing_name}, {diagnosing_phone}, {diagnosing_address}")

        # Check for another
        if (
            FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response, link_id="question-4"
            )
            == "No"
        ):

            # Parse answers
            current_name = FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response,
                link_id="question-5",
            )
            current_address = FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response,
                link_id="question-6",
            )
            current_phone = FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response,
                link_id="question-7",
            )

            # Add it.
            points_of_care.append(f"{current_name}, {current_phone}, {current_address}")

        # Get remaining RA places
        additional_ra_points_of_care = FHIR.get_questionnaire_response_item_value(
            questionnaire_response=questionnaire_response,
            link_id="question-8",
        )
        if additional_ra_points_of_care:
            points_of_care.append(additional_ra_points_of_care)

        # Check for another
        if (
            FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response, link_id="question-9"
            )
            == "Yes"
        ):

            # Get remaining places
            additional_points_of_care = FHIR.get_questionnaire_response_item_value(
                questionnaire_response=questionnaire_response,
                link_id="question-10",
            )
            if additional_points_of_care:
                points_of_care.append(additional_points_of_care)

        return points_of_care

    @staticmethod
    def get_questionnaire_response_item_value(questionnaire_response: dict, link_id: str) -> Optional[Any]:
        """
        Returns the value for the given questionnaire response and link ID.

        :param questionnaire_response: The QuestionnaireResponse resource
        to check
        :type questionnaire_response: dict
        :param link_id: The link ID of the item's value to return
        :type link_id: str
        :return: The value object, if it exists
        :rtype: Any, defaults to None
        """
        # Get answer value(s)
        values = FHIR.get_questionnaire_response_item_values(
            questionnaire_response=questionnaire_response, link_id=link_id
        )
        if values and len(values) > 1:
            # Get IDs
            questionnaire_id = questionnaire_response["questionnaire"].rsplit("/", 1)[-1]
            questionnaire_response_id = questionnaire_response["id"]
            logger.debug(
                f"PPM/FHIR/{questionnaire_id}/{questionnaire_response_id}/{link_id}: Ignoring other answer values"
            )
        return next(iter(values)) if values else None

    @staticmethod
    def get_questionnaire_response_item_values(questionnaire_response: dict, link_id: str) -> list[Any]:
        """
        Returns the value(s) for the given questionnaire response and link ID.

        :param questionnaire_response: The QuestionnaireResponse resource
        to check
        :type questionnaire_response: dict
        :param link_id: The link ID of the item's value to return
        :type link_id: str
        :return: A list of value objects
        :rtype: list[Any]
        """
        # Collect values
        values = []
        questionnaire_id = questionnaire_response_id = answer = None
        try:
            # Get IDs
            questionnaire_id = questionnaire_response["questionnaire"].rsplit("/", 1)[-1]
            questionnaire_response_id = questionnaire_response["id"]
            logger.debug(f"PPM/FHIR/{questionnaire_id}/{questionnaire_response_id}/{link_id}: Getting answer value(s)")

            # Get the item
            answers = next(
                (i.get("answer") for i in questionnaire_response["item"] if i["linkId"] == link_id),
                None,
            )

            # If answer, parse answer
            if not answers:
                logger.debug(f"PPM/FHIR/{questionnaire_id}/{questionnaire_response_id}/{link_id}: No answer for item")
                return None

            # Iterate values
            for answer in answers:
                # Check types
                if answer.get("valueString"):
                    values.append(answer["valueString"])
                elif answer.get("valueBoolean"):
                    values.append(answer["valueBoolean"])
                elif answer.get("valueInteger"):
                    values.append(answer["valueInteger"])
                elif answer.get("valueDecimal"):
                    values.append(answer["valueDecimal"])
                elif answer.get("valueDate"):
                    try:
                        values.append(parse(answer["valueDate"]))
                    except ValueError as e:
                        logger.exception(
                            f"PPM/FHIR: Date error: {e}",
                            exc_info=True,
                            extra={
                                "questionnaire_id": questionnaire_id,
                                "questionnaire_response": questionnaire_response_id,
                                "link_id": link_id,
                                "answer": answer,
                            },
                        )
                elif answer.get("valueDateTime"):
                    try:
                        values.append(parse(answer["valueDateTime"]))
                    except ValueError as e:
                        logger.exception(
                            f"PPM/FHIR: Date error: {e}",
                            exc_info=True,
                            extra={
                                "questionnaire_id": questionnaire_id,
                                "questionnaire_response": questionnaire_response_id,
                                "link_id": link_id,
                                "answer": answer,
                            },
                        )
                else:
                    logger.debug(
                        f"PPM/FHIR/{questionnaire_id}/{questionnaire_response_id}/{link_id}: "
                        f"Unhandled FHIR answer type: {answer}"
                    )
                    raise ValueError(f"Unhandled FHIR answer type: {answer}")

            return values

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Error getting item value: {e}",
                exc_info=True,
                extra={
                    "questionnaire_id": questionnaire_id,
                    "questionnaire_response": questionnaire_response_id,
                    "link_id": link_id,
                    "answer": answer,
                },
            )

    @staticmethod
    def flatten_questionnaire_response(bundle: Union[Bundle, dict], questionnaire_id: str) -> Optional[dict]:
        """
        Picks out the relevant Questionnaire and QuestionnaireResponse
        resources and returns a dict mapping the text of each question
        to a list of answer texts. To handle duplicate question texts,
        each question is prepended with an index. If no response is
        found for the given questionnaire ID, `None` is returned.

        :param bundle: A bundle of FHIR resources
        :type bundle: Union[Bundle, dict]
        :param questionnaire_id: The ID of the Questionnaire to parse for
        :type questionnaire_id: str
        :return: A dict of the flattened QuestionnaireResponse, defaults to None
        :rtype: Optional[dict]
        """
        logger.debug(f"PPM/FHIR: Flattening {questionnaire_id}")

        # Check bundle type
        if type(bundle) is dict:
            bundle = Bundle(bundle)

        # Pick out the questionnaire and its response
        questionnaire = next(
            (entry.resource for entry in bundle.entry if entry.resource.id == questionnaire_id),
            None,
        )
        questionnaire_response = next(
            (
                entry.resource
                for entry in bundle.entry
                if entry.resource.resource_type == "QuestionnaireResponse"
                and entry.resource.questionnaire.endswith(f"Questionnaire/{questionnaire_id}")
            ),
            None,
        )

        # Ensure resources exist
        if not questionnaire or not questionnaire_response:
            logger.debug(f"PPM/FHIR: No response for Questionnaire/{questionnaire_id}")
            return None

        # If no items, return empty
        if questionnaire_response.item:

            # Get questions and answers
            questions = FHIR.questionnaire_questions(questionnaire, questionnaire.item)
            answers = FHIR.questionnaire_response_answers(
                questionnaire, questionnaire_response, questionnaire_response.item
            )

            # Process sub-questions first
            for linkId, condition in {
                linkId: condition for linkId, condition in questions.items() if type(condition) is dict
            }.items():
                try:
                    # Assume only one condition, fetch the parent question linkId
                    parent = next(iter(condition))
                    if not parent:
                        logger.warning(
                            "FHIR Error: Subquestion not properly specified: {}:{}".format(linkId, condition),
                            extra={
                                "questionnaire": questionnaire_id,
                                "ppm_id": questionnaire_response.source,
                                "questionnaire_response": questionnaire_response.id,
                            },
                        )
                        continue

                    if len(condition) > 1:
                        logger.warning(
                            "FHIR Error: Subquestion has multiple conditions: {}:{}".format(linkId, condition),
                            extra={
                                "questionnaire": questionnaire_id,
                                "ppm_id": questionnaire_response.source,
                                "questionnaire_response": questionnaire_response.id,
                            },
                        )

                    # Ensure they've answered this one
                    if not answers.get(parent) or condition[parent] not in answers.get(parent):
                        continue

                    # Get the question and answer item
                    answer = answers[parent]
                    index = answer.index(condition[parent])

                    # Check for commas
                    sub_answers = answers[linkId]
                    if "," in next(iter(sub_answers)):

                        # Split it
                        sub_answers = [sub.strip() for sub in next(iter(sub_answers)).split(",")]

                    # Format them
                    value = '{} <span class="label label-primary">{}</span>'.format(
                        answer[index],
                        '</span>&nbsp;<span class="label label-primary">'.join(sub_answers),
                    )

                    # Append the value
                    answer[index] = mark_safe(value)

                except Exception as e:
                    logger.exception(
                        "FHIR error: {}".format(e),
                        exc_info=True,
                        extra={
                            "questionnaire": questionnaire_id,
                            "link_id": linkId,
                            "ppm_id": questionnaire_response.source,
                        },
                    )

            # Build the response
            response = collections.OrderedDict()

            # Determine index
            indices = FHIR.get_answer_indices(questionnaire, questions)
            for linkId, question in questions.items():

                # Check for the answer
                answer = answers.get(linkId)
                if not answer:

                    # Check if group or in a repeating group
                    item = FHIR.find_questionnaire_item(questionnaire.item, linkId)

                    # Skip repeating groups, those are handled below
                    if FHIR.get_questionnaire_repeating_group(questionnaire, linkId):
                        # If it's in a repeating group with no answer, then the
                        # group should be hidden
                        continue

                    elif item.type == "group" and item.item:

                        # This is a header
                        answer = []

                    # Check if dependent and enabled
                    elif FHIR.question_is_conditionally_enabled(
                        questionnaire, linkId
                    ) and not FHIR.questionnaire_response_is_enabled(questionnaire, questionnaire_response, linkId):

                        # If it's a sub-question, hide it
                        if re.match(r"question\-[\d]+\-[\d]+", linkId):
                            continue

                        # Else, show it as unanswered
                        else:
                            answer = [mark_safe('<span class="label label-info">N/A</span>')]

                    else:
                        # Set a default answer
                        answer = [mark_safe('<span class="label label-warning">N/A</span>')]

                        # Check if dependent and was enabled (or should have an answer but doesn't)
                        if FHIR.questionnaire_response_is_required(questionnaire, questionnaire_response, linkId):
                            logger.error(
                                f"FHIR Questionnaire: No answer found for {linkId}",
                                extra={
                                    "questionnaire": questionnaire_id,
                                    "link_id": linkId,
                                    "ppm_id": questionnaire_response.source,
                                },
                            )

                # Format the question text
                text = "{} {}".format(indices.get(linkId), question)

                # Add the answer
                response[text] = answer

            # Get repeating groups
            groups = [i for i in questionnaire_response.item if i.answer and next(iter(i.answer)).item]
            for group in groups:

                # Parse answers
                for group_answer in group.answer:

                    # Parse answers
                    group_answers = FHIR.questionnaire_response_answers(
                        questionnaire, questionnaire_response, group_answer.item
                    )

                    # Set a header
                    response[f"Response #{group_answer.valueInteger}"] = []

                    for linkId, question in questions.items():

                        # Check for the answer
                        answer = group_answers.get(linkId)
                        if not answer:

                            # Skip if not in this group
                            if not FHIR.get_questionnaire_repeating_group(questionnaire, linkId):
                                continue

                            else:
                                # Set as unanswered
                                answer = [mark_safe('<span class="label label-info">N/A</span>')]

                        # Format the question text
                        text = "{}| {} {}".format(group_answer.valueInteger, indices.get(linkId), question)

                        # Add the answer
                        response[text] = answer

        else:
            # Set an empty response
            response = {}
            logger.warning(
                f"PPM/FHIR: Empty QuestionnaireResponse/"
                f"{questionnaire_response.id} for Questionnaire/{questionnaire_id}"
            )

        # Add the date that the questionnaire was completed
        authored_date = questionnaire_response.authored.origval
        formatted_authored_date = FHIR._format_date(authored_date, "%m/%d/%Y")

        return {
            "ppm_id": FHIR._get_referenced_id(questionnaire_response.as_json(), "Patient"),
            "authored": formatted_authored_date,
            "responses": response,
            "questionnaire_id": questionnaire_id,
            "title": PPM.Questionnaire.title(questionnaire_id),
        }

    @staticmethod
    def get_questionnaire_repeating_group(questionnaire: dict, link_id: str) -> Optional[dict]:
        """
        Returns the containing group of the passed item if it's a
        repeating group. A repeating group is a set of questions
        that could repeat any number of times in a participant's
        response.

        :param questionnaire: The current Questionnaire
        :type questionnaire: dict
        :param link_id: The linkId of the question to check
        :type link_id: str
        :return: The QuestionnaireItem of the repeating group, defaults to None
        :rtype: Optional[dict]
        """
        # Check the path
        for item in FHIR.get_question_path(questionnaire, link_id):

            # Check if group and repeating
            if item.type == "group" and item.repeats:
                return item

        return None

    @staticmethod
    def int_to_roman(num: int) -> str:
        """
        A convenience method to return a roman numeral string for a given
        integer value.

        :param num: A positive integer
        :type num: int
        :return: A string representing the roman numeral version of the integer
        :rtype: str
        """
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        syb = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
        roman_num = ""
        i = 0
        while num > 0:
            for _ in range(num // val[i]):
                roman_num += syb[i]
                num -= val[i]
            i += 1
        return roman_num

    @staticmethod
    def get_answer_indices(questionnaire: dict, questions: dict) -> dict[str, str]:
        """
        Returns a mapping of a QuestionnaireItem linkId to the string to be
        used as its indexing in the listing of questions and answers in a
        view. This method relies on sequential linkIds being used and also
        manages child-questions indexing using letters, etc.

        Top-level questions: {item type}-3 -> "3. Some answer"
        Second-level questions: {item-type}-2-4 -> "2. d.  Some answer"
        Third-level questions: {item-type}-10-1-3 -> "10. a. iii. Some answer"

        :param questionnaire: The Questionnaire object
        :type questionnaire: dict
        :param questions: The dictionary of linkIds to question text
        :type questions: dict
        :return: The mapping of linkId to answer index text.
        with linkId
        :rtype: dict[str, str]
        """

        # Create a mapping of linkId to index
        indices = {}
        index = 0

        # Iterate questions
        for linkId, text in questions.items():

            # Check type
            question = FHIR.find_questionnaire_item(questionnaire.item, linkId)

            # If group, check if subitems are nested or not
            if question.type == "display" or linkId.startswith("display-"):

                # No index needed
                indices[linkId] = ""
                continue

            # Parse it up
            r = re.compile(r"-?([\d]+)")
            parts = r.findall(linkId)

            if len(parts) >= 1:

                # Increment if not children
                if len(parts) == 1:
                    index = index + 1

                # Set it
                indices[linkId] = f"{index}. "

            if len(parts) >= 2:

                letter_index = int(parts[1])

                # Add it
                letter_multiplier = int((letter_index - 1) / len(string.ascii_lowercase)) + 1
                letter = string.ascii_lowercase[(letter_index - 1) % len(string.ascii_lowercase)] * letter_multiplier
                indices[linkId] = f"{indices[linkId]}{letter}. "

            if len(parts) == 3:

                # Ensure we have siblings
                if len([link_id for link_id in questions.keys() if linkId.rsplit(parts[2], 1)[0] in link_id]) == 1:
                    continue

                i_count = int(parts[2])
                indices[linkId] = f"{indices[linkId]}{FHIR.int_to_roman(i_count).lower()}. "

        return indices

    @staticmethod
    def find_questionnaire_item(
        questionnaire_items: list[Union[QuestionnaireItem, QuestionnaireResponseItem]], linkId: str
    ) -> Optional[Union[QuestionnaireItem, QuestionnaireResponseItem]]:
        """
        Finds and returns the QuestionnaireItem for the given `linkId`. This
        will search recursively through the list of items since a
        QuestionnaireItem may contain nested lists of QuestionnaireItems. If
        no QuestionnaireItem is found, `None` is returned. This method will
        also accept and return QuestionnaireResponseItem resources due to
        classes being similar enough for this method.

        :param questionnaire_items: The list of QuestionnaireItems to search
        :type questionnaire_items: list[Union[QuestionnaireItem, QuestionnaireResponseItem]]
        :param linkId: The link ID of the desired QuestionnaireItem
        :type linkId: str
        :return: The matching QuestionnaireItem if found, defaults to None
        :rtype: Optional[Union[QuestionnaireItem, QuestionnaireResponseItem]]
        """
        # Find it
        for item in questionnaire_items:

            # Compare
            if item.linkId == linkId:
                return item

            # Check for subitems
            if item.item:
                sub_item = FHIR.find_questionnaire_item(item.item, linkId)
                if sub_item:
                    return sub_item

        return None

    @staticmethod
    def get_questionnaire_response_item_answers(
        questionnaire_response_items: list[QuestionnaireResponseItem], linkId: str
    ) -> list[str | bool | int | float]:
        """
        Finds and returns the values for the passed `linkId` argument in the
        list of QuestionnaireResponseItems.

        :param questionnaire_response_items: The list of items to search
        :type questionnaire_response_items: list[QuestionnaireResponseItem]
        :param linkId: The link ID of the item to search for
        :type linkId: str
        :return: The values of the item for the passed link ID
        :rtype: list[str | bool | int | float]
        """
        # Find it
        item = FHIR.find_questionnaire_item(questionnaire_response_items, linkId)

        # It is possible for a linkId to not match any response items (group, display, etc)
        if not item or not item.answer:
            return None

        # Iterate answers
        answers = []
        for answer in item.answer:
            if answer.valueString is not None:
                answers.append(answer.valueString)
            elif answer.valueBoolean is not None:
                answers.append(answer.valueBoolean)
            elif answer.valueInteger is not None:
                answers.append(answer.valueInteger)
            elif answer.valueDecimal is not None:
                answers.append(answer.valueDecimal)
            elif answer.valueDate is not None:
                answers.append(answer.valueDate.isostring)
            elif answer.valueDateTime is not None:
                answers.append(answer.valueDateTime.isostring)
            else:
                logger.error(f"PPM/FHIR: Unhandled answer type: {answer.as_json()}")

        return answers

    @staticmethod
    def get_question_path(
        questionnaire: Questionnaire, linkId: str, parent: QuestionnaireItem = None
    ) -> list[QuestionnaireItem]:
        """
        Returns a list of QuestionnaireItem objects that form the lineage
        of parents of the requested item by linkId. The first item in the list
        is at the top-most level followed by second level, and so on until
        the requested item, at whatever level it exists.

        :param questionnaire: The questionnaire being processed
        :type questionnaire: Questionnaire
        :param linkId: The link ID of the question to check
        :type linkId: str
        :param parent: The nested item we are searching, defaults to None
        :type parent: QuestionnaireItem
        :return: The list of QuestionnaireItems forming a path to the question
        with linkId
        :rtype: list[QuestionnaireItem]
        """
        # Build items
        items = [parent] if parent else []

        # If not parent, start with root of Questionnaire
        if not parent:
            parent = questionnaire

        # Iterate items and break as soon as we find the correct node or path
        for item in parent.item:

            # Compare
            if item.linkId == linkId:

                # Check what to return
                items.append(item)
                break

            # Check for subitems
            subitems = item.item and FHIR.get_question_path(questionnaire, linkId, parent=item)
            if subitems:
                items.extend(subitems)
                break

        else:
            # If not found, return empty list
            return []

        # Return items
        return items

    @staticmethod
    def question_is_conditionally_enabled(questionnaire: Questionnaire, linkId: str) -> bool:
        """
        Returns whether the passed question is conditionally enabled or not.
        Conditionally enabled means this QuestionnaireItem or one of its
        antecedents has an enableWhen property that determines when and if
        it and its descendents are enabled.

        :param questionnaire: The questionnaire being processed
        :type questionnaire: Questionnaire
        :param linkId: The link ID of the question to check
        :type linkId: str
        :return: Whether it is conditionally enabled or not
        :rtype: bool
        """
        # Find first condition
        for item in FHIR.get_question_path(questionnaire, linkId):

            # Check this and parent for enableWhen
            if item.enableWhen:
                return True

        return False

    @staticmethod
    def questionnaire_response_is_enabled(
        questionnaire: Questionnaire, questionnaire_response: QuestionnaireResponse, linkId: str
    ) -> bool:
        """
        Inspects the Questionnaire for the given link ID and returns whether
        it is conditionally enabled or not based on responses given.

        :param questionnaire: The Questionnaire for which the response was
        created
        :type questionnaire: Questionnaire
        :param questionnaire_response: The QuestionnaireResponse to check
        :type questionnaire_response: QuestionnaireResponse
        :param linkId: The link ID of the item to find and check
        :type linkId: str
        :return: Whether the item is enabled based on the responses
        :rtype: bool
        """
        # Compile list of conditions
        enable_whens = []

        # Find first condition
        for item in FHIR.get_question_path(questionnaire, linkId):

            # Check this and parent for enableWhen
            if item.enableWhen:
                enable_whens.extend(item.enableWhen)

        # Iterate conditions and check for failures
        for enable_when in enable_whens:

            # Get their answer as a list, if not already
            answer = FHIR.get_questionnaire_response_item_answers(questionnaire_response.item, enable_when.question)

            # Check operation (this is not available on FHIR R3 and below)
            enable_when_operation = getattr(enable_when, "operation", "=")

            # Check equality of condition and answer
            if enable_when_operation == "=":

                # Check for answer type and check if it's in their list of items
                if enable_when.answerString is not None:
                    if enable_when.answerString not in answer:
                        return False
                elif enable_when.answerBoolean is not None:
                    if enable_when.answerBoolean not in answer:
                        return False
                elif enable_when.answerDate is not None:
                    if enable_when.answerDate.isostring not in answer:
                        return False
                elif enable_when.answerDateTime is not None:
                    if enable_when.answerDateTime.isostring not in answer:
                        return False
                elif enable_when.answerInteger is not None:
                    if enable_when.answerInteger not in answer:
                        return False
                elif enable_when.answerDecimal is not None:
                    if enable_when.answerDecimal not in answer:
                        return False
                else:
                    logger.error(f"PPM/FHIR: Unhandled enableWhen answer type: {enable_when.as_json()}")
                    return False

            else:
                logger.error(f"PPM/FHIR: Unhandled enableWhen operation type: {enable_when.as_json()}")
                return False

        # If we are here, this item is enabled as dependencies are satisfied (if any)
        return True

    @staticmethod
    def questionnaire_response_is_required(
        questionnaire: Questionnaire, questionnaire_response: QuestionnaireResponse, linkId: str
    ) -> bool:
        """
        Inspects the Questionnaire for the given link ID and returns whether
        it is conditionally required or not based on responses given.

        :param questionnaire: The Questionnaire for which the response was
        was created
        :type questionnaire: Questionnaire
        :param questionnaire_response: The response to search
        :type questionnaire_response: QuestionnaireResponse
        :param linkId: The link ID of the item to check
        :type linkId: str
        :return: Whether the item is required or not based on responses
        :rtype: bool
        """

        # Get the question
        item = FHIR.find_questionnaire_item(questionnaire.item, linkId)

        # If not required, return right away
        if not getattr(item, "required", False):
            return False

        # Check this and parent for enableWhen
        if not FHIR.questionnaire_response_is_enabled(questionnaire, questionnaire_response, linkId):
            return False

        # If we are here, this item is required and all dependencies are satisfied (if any)
        return True

    @staticmethod
    def questionnaire_questions(questionnaire: Questionnaire, items: list[QuestionnaireItem]) -> list[str]:
        """
        This accepts a questionnaire resource and a list of items for
        which to find and return the text values of the questions asked
        by the items. This methid will recurse into subitems and add them to the
        mapping, although the mapping will be flat.

        :param questionnaire: The FHIR Questionnaire resource
        :type questionnaire: Questionnaire
        :param items: The FHIR QuestionnaireResponseItem items list
        :type items: list
        :return: A flat list of the item's question values
        :rtype: list[str]
        """

        # Iterate items
        questions = {}
        for item in items:

            # Leave out display or ...
            if item.type == "display":
                continue

            elif item.type == "group" and item.item:

                # Get answers
                sub_questions = FHIR.questionnaire_questions(questionnaire, item.item)

                # Check for text
                if item.text:
                    questions[item.linkId] = item.text

                # Add them
                questions.update(sub_questions)

            elif item.enableWhen:

                # This is a sub-question
                questions[item.linkId] = {
                    next(condition.question for condition in item.enableWhen): next(
                        condition.answerString for condition in item.enableWhen
                    )
                }
                questions[item.linkId] = item.text

            else:

                # Ensure it has text
                if item.text:
                    # List them out
                    questions[item.linkId] = item.text

                else:
                    # Indicate a blank question text, presumably a sub-question
                    questions[item.linkId] = "-"

                # Check for subtypes
                if item.item:
                    # Get answers
                    sub_questions = FHIR.questionnaire_questions(questionnaire, item.item)

                    # Add them
                    questions.update(sub_questions)

        return questions

    @staticmethod
    def questionnaire_response_answers(
        questionnaire: Questionnaire,
        questionnaire_response: QuestionnaireResponse,
        items: list[QuestionnaireResponseItem],
    ) -> dict[str, str]:
        """
        This accepts a questionnaire, a questionnaire response and a list
        of items from the questionnaire response and returns a dictionary of
        question link IDs mapped to parsed answers from the response. This
        will recurse into subitems and add them to the mapping, although the
        mapping will be flat.

        :param questionnaire: The FHIR Questionnaire resource
        :type questionnaire: Questionnaire
        :param questionnaire_response: The FHIR QuestionnaireResponse resource
        :type questionnaire_response: QuestionnaireResponse
        :param items: A list of response items to iterate through
        :type items: list[QuestionnaireResponseItem]
        :return: A mapping of found item link IDs to the answers from the
        response
        :rtype: dict[str, str]
        """
        # Iterate items
        responses = {}
        for item in items:

            # List them out
            responses[item.linkId] = []

            # Ensure we've got answers
            if not item.answer:

                # Check if omitted due to error
                if FHIR.questionnaire_response_is_required(questionnaire, questionnaire_response, item.linkId):
                    logger.error(
                        f"FHIR/QuestionnaireResponse/{item.linkId}: Missing answer item(s) for question item",
                        extra={
                            "questionnaire": questionnaire.id,
                            "questionnaire_response": questionnaire_response.id,
                            "link_id": item.linkId,
                        },
                    )

                    # Set an N/A value
                    responses[item.linkId] = [mark_safe('<span class="label label-warning">N/A</span>')]
                else:
                    # Set an N/A value
                    responses[item.linkId] = [mark_safe('<span class="label label-info">N/A</span>')]

            else:

                # Iterate answers
                for answer in item.answer:

                    # Get the value
                    if answer.valueBoolean is not None:
                        responses[item.linkId].append(answer.valueBoolean)
                    elif answer.valueString is not None:
                        responses[item.linkId].append(answer.valueString)
                    elif answer.valueInteger is not None:
                        responses[item.linkId].append(answer.valueInteger)
                    elif answer.valueDecimal is not None:
                        responses[item.linkId].append(answer.valueDecimal)
                    elif answer.valueDate is not None:
                        responses[item.linkId].append(answer.valueDate.isostring)
                    elif answer.valueDateTime is not None:
                        responses[item.linkId].append(answer.valueDateTime.isostring)

                    else:
                        logger.error(
                            f"FHIR/QuestionnaireResponse/{item.linkId}: Unhandled answer value "
                            f"type: {answer.as_json()}",
                            extra={
                                "questionnaire": questionnaire.id,
                                "questionnaire_response": questionnaire_response.id,
                                "link_id": item.linkId,
                                "answer": answer.as_json(),
                            },
                        )

            # Check for subtypes
            if item.item:
                # Get answers
                sub_answers = FHIR.questionnaire_response_answers(questionnaire, questionnaire_response, item.item)

                # Add them
                responses[item.linkId].extend(sub_answers)

        return responses

    @staticmethod
    def flatten_patient(bundle: Union[Bundle, dict, Patient]) -> Optional[dict]:
        """
        Accepts a bundle of resources or a Patient resource itself and
        flattens the object to a simplified form. If no Patient is found
        `None` is returned.

        An example of the returned dictionary:

        {
            "ppm_id": str,
            "email": str,
            "active": bool,
            "firstname": str,
            "lastname": str,
            "street_address1": str,
            "street_address2": str,
            "city": str,
            "state": str,
            "zip": str,
            "phone": str,
            "deceased": str,
            "twitter_handle": str,
            "contact_email": str,
            "admin_notified": str,
            "how_did_you_hear_about_us": str,
            "uses_twitter": bool,
            "uses_fitbit": bool,
            "uses_facebook": bool,
            "uses_procure": bool,
            "uses_smart_on_fhir": bool,
            "picnichealth": bool,
        }

        :param bundle: The set of resources to find the Patient in or
        the Patient itself
        :type bundle: Union[Bundle, dict, Patient]
        :return: A dict as a simplified representation of the Patient,
        defaults to None
        :rtype: Optional[dict]
        """

        # Get the patient
        resource = FHIR.find_resource(bundle, "Patient")

        # Check for a resource
        if not resource:
            logger.debug("Cannot flatten Patient, one did not exist in bundle")
            return None

        # Collect properties
        patient = dict()

        # Get FHIR IDs
        patient["fhir_id"] = patient["ppm_id"] = resource["id"]

        # Parse out email
        patient["email"] = next(
            (
                identifier["value"]
                for identifier in resource.get("identifier", [])
                if identifier.get("system") == FHIR.patient_email_identifier_system
            )
        )
        if not patient.get("email"):
            logger.error("Could not parse email from Patient/{}! This should not be possible".format(resource["id"]))
            return {}

        # Get status
        patient["active"] = FHIR._get_or(resource, ["active"], "")

        # Get the remaining optional properties
        patient["firstname"] = FHIR._get_or(resource, ["name", 0, "given", 0], "")
        patient["lastname"] = FHIR._get_or(resource, ["name", 0, "family"], "")
        patient["street_address1"] = FHIR._get_or(resource, ["address", 0, "line", 0], "")
        patient["street_address2"] = FHIR._get_or(resource, ["address", 0, "line", 1], "")
        patient["city"] = FHIR._get_or(resource, ["address", 0, "city"], "")
        patient["state"] = FHIR._get_or(resource, ["address", 0, "state"], "")
        patient["zip"] = FHIR._get_or(resource, ["address", 0, "postalCode"], "")
        patient["phone"] = FHIR._get_or(resource, ["telecom", 0, "postalCode"], "")

        # Check for deceased
        if FHIR._get_or(resource, ["deceasedDateTime"], None):
            patient["deceased"] = FHIR._format_date(resource["deceasedDateTime"], "%m/%d/%Y")

        # Parse telecom properties
        patient["phone"] = next(
            (
                telecom.get("value", "")
                for telecom in resource.get("telecom", [])
                if telecom.get("system") == FHIR.patient_phone_telecom_system
            ),
            "",
        )
        patient["twitter_handle"] = next(
            (
                telecom.get("value", "")
                for telecom in resource.get("telecom", [])
                if telecom.get("system") == FHIR.patient_twitter_telecom_system
            ),
            "",
        )
        patient["contact_email"] = next(
            (
                telecom.get("value", "")
                for telecom in resource.get("telecom", [])
                if telecom.get("system") == FHIR.patient_email_telecom_system
            ),
            "",
        )

        # Determine if admins have been notified of their completion of initial registration
        patient["admin_notified"] = next(
            (
                extension["valueDateTime"]
                for extension in resource.get("extension", [])
                if "admin-notified" in extension.get("url")
            ),
            None,
        )

        # Get how they heard about PPM
        patient["how_did_you_hear_about_us"] = next(
            (
                extension["valueString"]
                for extension in resource.get("extension", [])
                if "how-did-you-hear-about-us" in extension.get("url")
            ),
            "",
        )

        # Get if they are not using Twitter
        patient["uses_twitter"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if "uses-twitter" in extension.get("url")
            ),
            True,
        )

        # Get if they are not using Fitbit
        patient["uses_fitbit"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if "uses-fitbit" in extension.get("url")
            ),
            True,
        )

        # Get if they are not using Fitbit
        patient["uses_facebook"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if "uses-facebook" in extension.get("url")
            ),
            True,
        )

        # Get if they are not using SMART on FHIR / EHR
        patient["uses_smart_on_fhir"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if "uses-smart-on-fhir" in extension.get("url")
            ),
            True,
        )

        # Get if they are not using Fitbit
        patient["uses_procure"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if FHIR.procure_extension_url in extension.get("url")
            ),
            True,
        )

        # Get if they are registered with Picnichealth
        patient["picnichealth"] = next(
            (
                extension["valueBoolean"]
                for extension in resource.get("extension", [])
                if FHIR.picnichealth_extension_url in extension.get("url")
            ),
            False,
        )

        return patient

    @staticmethod
    def flatten_research_subject(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "start": str,
            "end": Optional[str],
            "study": str,
            "ppm_id": str,
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """

        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Get the resource.
        record = dict()

        # Try and get the values
        record["start"] = FHIR._get_or(resource, ["period", "start"])
        record["end"] = FHIR._get_or(resource, ["period", "end"])

        # Get the study ID
        record["study"] = FHIR.get_study_from_research_subject(resource)

        # Link back to participant
        record["ppm_id"] = FHIR._get_referenced_id(resource, "Patient")

        return record

    @staticmethod
    def flatten_research_study(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "start": str,
            "end": Optional[str],
            "status": str,
            "title": str,
            "identifier": Optional[str],
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """

        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Get the resource.
        record = dict()

        # Try and get the values
        record["start"] = FHIR._get_or(resource, ["period", "start"])
        record["end"] = FHIR._get_or(resource, ["period", "end"])
        record["status"] = FHIR._get_or(resource, ["status"])
        record["title"] = FHIR._get_or(resource, ["title"])

        if resource.get("identifier"):
            record["identifier"] = FHIR._get_or(resource, ["identifier", 0, "value"])

        return record

    @staticmethod
    def flatten_ppm_studies(bundle: Union[Bundle, dict]) -> list[dict]:
        """
        Find and returns the research subject resources related to PPM studies
        as their simplified form via `FHIR.flatten_research_subject`

        :param bundle: The bundle of resources to find research subjects in
        :type bundle: Union[Bundle, dict]
        :return: A list of flattened research subject resources, if any
        :rtype: list[dict]
        """
        # Collect them
        research_subjects = []
        for research_subject in FHIR._find_resources(bundle, "ResearchSubject"):

            # Ensure it's the PPM kind
            if FHIR.is_ppm_research_subject(research_subject):

                # Flatten it and add it
                research_subjects.append(FHIR.flatten_research_subject(research_subject))

        if not research_subjects:
            logger.debug("No ResearchSubjects found in bundle")

        return research_subjects

    @staticmethod
    def flatten_ppm_devices(bundle):
        """
        Find and returns the flattened device resources used by PPM
        as a method to track physical items sent to and returned by
        participants as a part of the data collection process. Resources
        are returned as flattened representations via the
        `FHIR.flatten_ppm_device` method.

        :param bundle: The bundle of resources to find device in
        :type bundle: Union[Bundle, dict]
        :return: A list of flattened device resources, if any
        :rtype: list[dict]
        """
        # Collect flattened items
        devices = []

        # Iterate all Device resources in the bundle
        for device in FHIR._find_resources(bundle, "Device"):

            # Ensure it's a PPM device
            for identifier in device.get("identifier", []):
                if identifier.get("system") == FHIR.device_identifier_system:

                    # Flatten it
                    devices.append(FHIR.flatten_ppm_device(device))

        return devices

    @staticmethod
    def flatten_ppm_device(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "id": str,
            "type": str,
            "name": str,
            "title": str,
            "status": str,
            "ppm_id": str,
            "study": Optional[str],
            "shipped": Optional[str],
            "returned": Optional[str],
            "identifier": Optional[str],
            "tracking": Optional[str],
            "note": Optional[str],
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """

        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Get the resource.
        record = dict()

        # Try and get the values
        record["id"] = resource["id"]
        record["status"] = FHIR._get_or(resource, ["status"])

        # Try to get dates
        if resource.get("manufactureDate"):
            record["shipped"] = parse(resource["manufactureDate"])
        if resource.get("expirationDate"):
            record["returned"] = parse(resource["expirationDate"])

        # Get the study
        record["study"] = ""
        for e in resource.get("extension", []):
            if e.get("url") == FHIR.device_study_extension_url:
                record["study"] = e["valueString"]

        # Get the proper identifier
        record["identifier"] = ""
        record["title"] = ""
        record["tracking"] = ""
        for identifier in resource.get("identifier", []):
            if identifier.get("system") == FHIR.device_identifier_system:

                # Set properties
                record["identifier"] = identifier["value"]

            if identifier.get("system") == FHIR.device_title_system:

                # Set properties
                record["title"] = identifier["value"]

            if identifier.get("system") == FHIR.device_tracking_system:

                # Set properties
                record["tracking"] = identifier["value"]

        # Get notes
        record["note"] = ""
        for note in resource.get("note", []):
            if note.get("text"):
                record["note"] = note["text"]

        # Get the proper coding
        record["type"] = ""
        record["name"] = ""
        for coding in FHIR._get_or(resource, ["type", "coding"], []):
            if coding.get("system") == FHIR.device_coding_system:

                # Set properties
                record["type"] = coding["code"]
                record["name"] = coding["display"]

        # Link back to participant
        record["ppm_id"] = FHIR._get_referenced_id(resource, "Patient", key="patient")

        return record

    @staticmethod
    def flatten_enrollment(bundle: Union[Bundle, dict]) -> Optional[dict]:
        """

        Find and returns the flattened enrollment Flag used to track
        PPM enrollment status. If not flag resource is found, `None` is
        returned.

        :param bundle: The bundle of resources to search
        :type bundle: Union[Bundle, dict]
        :return: A flattened representation of the enrollment flag,
        defaults to None
        :rtype: Optional[dict]
        """
        for flag in FHIR._find_resources(bundle, "Flag"):

            # Ensure it's the enrollment flag
            if FHIR.enrollment_flag_coding_system == FHIR._get_or(flag, ["code", "coding", 0, "system"]):

                # Flatten and return it
                return FHIR.flatten_enrollment_flag(flag)

            logger.error("No Flag with coding: {} found".format(FHIR.enrollment_flag_coding_system))

        logger.debug("No Flags found in bundle")
        return None

    @staticmethod
    def flatten_enrollment_flag(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "ppm_id": str,
            "enrollment": str,
            "status": str,
            "start": str,
            "end": Optional[str],
            "updated": str,
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """

        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Get the resource.
        record = dict()

        # Try and get the values
        record["enrollment"] = FHIR._get_or(resource, ["code", "coding", 0, "code"])
        record["status"] = FHIR._get_or(resource, ["status"])
        record["start"] = FHIR._get_or(resource, ["period", "start"])
        record["end"] = FHIR._get_or(resource, ["period", "end"])
        record["updated"] = FHIR._get_or(resource, ["meta", "lastUpdated"])

        # Link back to participant
        record["ppm_id"] = FHIR._get_referenced_id(resource, "Patient")

        return record

    @staticmethod
    def flatten_consent_composition(bundle: Union[Bundle, dict]) -> Optional[dict]:
        """
        This method flattens a participant's consent. As the consent in
        FHIR is represented by a Composition resource that links to various
        other resources, this method finds and uses all referenced resources
        in order to generate the simplified version of the consent to
        return. If no Composition resource is found, `None` is returned.

        :param bundle: The bundle of resources containing the consent resources
        :type bundle: Union[Bundle, dict]
        :return: A simplified object representing all resources used to
        describe a participant's consent for a study
        :rtype: Optional[dict]
        """
        logger.debug("Flatten composition")

        # Parse the bundle in not so strict mode
        if type(bundle) is dict:
            incoming_bundle = Bundle(bundle, strict=True)
        else:
            incoming_bundle = bundle

        # Prepare the object.
        consent_object = {
            "consent_questionnaires": [],
            "assent_questionnaires": [],
        }
        consent_exceptions = []
        assent_exceptions = []

        if incoming_bundle.total > 0:

            for bundle_entry in incoming_bundle.entry:
                if bundle_entry.resource.resource_type == "Consent":

                    signed_consent = bundle_entry.resource

                    # We can pull the date from the Consent Resource. It's stamped
                    # in a few places.
                    date_time = signed_consent.dateTime.origval

                    # Format it
                    consent_object["date_signed"] = FHIR._format_date(date_time, "%m/%d/%Y")

                    # Exceptions are for when they refuse part of the consent.
                    if signed_consent.extension:

                        # Get the extensions holding exceptions
                        consent_exception_extension = next(
                            (e for e in signed_consent.extension if e.url == FHIR.consent_exception_extension_url), None
                        )
                        if consent_exception_extension:

                            # Iterate exception codings and add to list
                            for consent_exception in consent_exception_extension.valueCodeableConcept.coding:
                                consent_exceptions.append(FHIR._exception_description(consent_exception.display))

                elif bundle_entry.resource.resource_type == "Composition":

                    composition = bundle_entry.resource

                    entries = [section.entry for section in composition.section if section.entry is not None]
                    references = [
                        entry[0].reference for entry in entries if len(entry) > 0 and entry[0].reference is not None
                    ]
                    text = [section.text.div for section in composition.section if section.text is not None][0]

                    # Check the references for a Consent object, making this comp the
                    # consent one.
                    if len([r for r in references if "Consent" in r]) > 0:
                        consent_object["consent_text"] = text
                    else:
                        consent_object["assent_text"] = text

                elif bundle_entry.resource.resource_type == "RelatedPerson":
                    pass
                elif bundle_entry.resource.resource_type == "Contract":

                    contract = bundle_entry.resource

                    # Parse out common contract properties
                    consent_object["type"] = "INDIVIDUAL"
                    consent_object["signer_signature"] = base64.b64decode(contract.signer[0].signature[0].data).decode()
                    consent_object["participant_name"] = contract.signer[0].signature[0].who.display

                    # These don't apply on an Individual consent.
                    consent_object["participant_acknowledgement_reason"] = "N/A"
                    consent_object["participant_acknowledgement"] = "N/A"
                    consent_object["signer_name"] = "N/A"
                    consent_object["signer_relationship"] = "N/A"
                    consent_object["assent_signature"] = "N/A"
                    consent_object["assent_date"] = "N/A"
                    consent_object["explained_signature"] = "N/A"

                    # Contracts with a binding reference are either the individual
                    # consent or the guardian consent.
                    if contract.legallyBindingReference:

                        # Fetch the questionnaire and its responses.
                        questionnaire_response_id = contract.legallyBindingReference.reference.rsplit("/", 1)[-1]
                        q_response = next(
                            (
                                entry.resource
                                for entry in incoming_bundle.entry
                                if entry.resource.resource_type == "QuestionnaireResponse"
                                and entry.resource.id == questionnaire_response_id
                            ),
                            None,
                        )

                        if not q_response:
                            logger.error(
                                "Could not find legallyBindingReference QR for Contract/{}".format(contract.id)
                            )
                            break

                        # Get the questionnaire and its response.
                        questionnaire_id = q_response.questionnaire.rsplit("/", 1)[-1]
                        questionnaire = next(
                            (
                                entry.resource
                                for entry in incoming_bundle.entry
                                if entry.resource.id == questionnaire_id
                            ),
                            None,
                        )

                        if not q_response or not questionnaire:
                            logger.error(
                                "FHIR Error: Could not find legallyBindingReference "
                                "Questionnaire/Response for Contract/{}".format(contract.id),
                                extra={
                                    "ppm_id": contract.subject,
                                    "questionnaire": questionnaire_id,
                                    "questionnaire_response": questionnaire_response_id,
                                },
                            )
                            break

                        # The reference refers to a Questionnaire which is linked to
                        # a part of the consent form.
                        if q_response.questionnaire.endswith("Questionnaire/guardian-signature-part-1"):

                            # This is a person consenting for someone else.
                            consent_object["type"] = "GUARDIAN"

                            related_id = contract.signer[0].party.reference.split("/")[1]
                            related_person = [
                                entry.resource
                                for entry in incoming_bundle.entry
                                if entry.resource.resource_type == "RelatedPerson" and entry.resource.id == related_id
                            ][0]

                            consent_object["signer_name"] = related_person.name[0].text
                            consent_object["signer_relationship"] = related_person.relationship.text

                            consent_object["participant_name"] = contract.signer[0].signature[0].onBehalfOf.display
                            consent_object["signer_signature"] = base64.b64decode(
                                contract.signer[0].signature[0].data
                            ).decode()

                        elif q_response.questionnaire.endswith("Questionnaire/guardian-signature-part-2"):

                            # This is the question about being able to get
                            # acknowledgement from the participant by the
                            # guardian/parent.
                            consent_object["participant_acknowledgement"] = next(
                                item.answer[0].valueString for item in q_response.item if item.linkId == "question-1"
                            ).title()

                            # If the answer to the question is no, grab the reason.
                            if consent_object["participant_acknowledgement"].lower() == "no":
                                consent_object["participant_acknowledgement_reason"] = next(
                                    item.answer[0].valueString
                                    for item in q_response.item
                                    if item.linkId == "question-1-1"
                                )

                            # This is the Guardian's signature letting us know they
                            # tried to explain this study.
                            consent_object["explained_signature"] = base64.b64decode(
                                contract.signer[0].signature[0].data
                            ).decode()

                        elif q_response.questionnaire.endswith("Questionnaire/guardian-signature-part-3"):

                            # A contract without a reference is the assent page.
                            consent_object["assent_signature"] = base64.b64decode(
                                contract.signer[0].signature[0].data
                            ).decode()
                            consent_object["assent_date"] = contract.issued.origval

                            # Append the Questionnaire Text if the response is true.
                            for current_response in q_response.item:

                                if current_response.answer[0].valueBoolean:
                                    answer = [
                                        item for item in questionnaire.item if item.linkId == current_response.linkId
                                    ][0]
                                    assent_exceptions.append(FHIR._exception_description(answer.text))

                        # Prepare to parse the questionnaire.
                        questionnaire_object = {
                            "template": "dashboard/{}.html".format(questionnaire.id),  # TODO: Remove this after PPM-603
                            "questionnaire": questionnaire.id,
                            "questions": [],
                        }

                        for item in questionnaire.item:

                            question_object = {
                                "type": item.type,
                            }

                            if item.type == "display":
                                question_object["text"] = item.text

                            elif item.type == "boolean" or item.type == "question":
                                # Get the answer.
                                for response in q_response.item:
                                    if response.linkId == item.linkId:
                                        # Process the question, answer and response.
                                        if item.type == "boolean":
                                            question_object["text"] = item.text
                                            question_object["answer"] = response.answer[0].valueBoolean

                                        elif item.type == "question":
                                            question_object["yes"] = item.text
                                            question_object["no"] = (
                                                "I was not able to explain this study "
                                                "to my child or individual in my care "
                                                "who will be participating"
                                            )
                                            question_object["answer"] = response.answer[0].valueString.lower() == "yes"

                            # Add it.
                            questionnaire_object["questions"].append(question_object)

                        # Check the type.
                        if q_response.questionnaire.endswith("Questionnaire/guardian-signature-part-3"):
                            consent_object["assent_questionnaires"].append(questionnaire_object)
                        else:
                            consent_object["consent_questionnaires"].append(questionnaire_object)

                        # Link back to participant
                        consent_object["ppm_id"] = FHIR._get_referenced_id(q_response.as_json(), "Patient")

        consent_object["exceptions"] = consent_exceptions
        consent_object["assent_exceptions"] = assent_exceptions

        return consent_object

    @staticmethod
    def _exception_description(display: str) -> str:
        """
        This is a convenience method to accept the code for a consent
        exception and to return an HTML-formatted description of that
        exception for rendering.

        :param display: The display code for the consent exception
        :type display: str
        :return: HTML-formatted code describing the consent exception
        :rtype: str
        """

        # Check the various exception display values
        if "equipment monitoring" in display.lower() or "fitbit" in display.lower():
            return mark_safe('<span class="label label-danger">Fitbit monitoring</span>')

        elif "referral to clinical trial" in display.lower():
            return mark_safe('<span class="label label-danger">Future contact/questionnaires</span>')

        elif "saliva" in display.lower():
            return mark_safe('<span class="label label-danger">Saliva sample</span>')

        elif "blood sample" in display.lower():
            return mark_safe('<span class="label label-danger">Blood sample</span>')

        elif "stool sample" in display.lower():
            return mark_safe('<span class="label label-danger">Stool sample</span>')

        elif "tumor" in display.lower():
            return mark_safe('<span class="label label-danger">Tumor tissue samples</span>')

        else:
            logger.warning("Could not format exception: {}".format(display))
            return display

    @staticmethod
    def flatten_list(bundle: Bundle, resource_type: str) -> Optional[list[Union[dict, str]]]:
        """
        This method will find and flatten a List resource that is found
        in the passed bundle. Flattening will depend on the resource type
        that is contained in the List. If no List resource is found, `None`
        is returned.

        :param bundle: The bundle of resources containing the list resource
        :type bundle: Bundle
        :param resource_type: The resource type the desired list tracks
        :type resource_type: str
        :return: A list of simplified representations of the tracked resources,
        defaults to None
        :rtype: Optional[list[Union[dict, str]]]
        """

        try:
            # Check the bundle type
            if type(bundle) is dict:
                bundle = Bundle(bundle)

            resource = FHIR._get_list(bundle, resource_type)
            if not resource:
                logger.debug("No List for resource {} found".format(resource_type))
                return None

            # Get the references
            references = [entry.item.reference for entry in resource.entry if entry.item.reference]

            # Find it in the bundle
            resources = [
                entry.resource
                for entry in bundle.entry
                if "{}/{}".format(resource_type, entry.resource.id) in references
            ]

            # Check for missing resources
            missing_resource_ids = [
                r.rsplit("/", 1)[-1] for r in references if r.rsplit("/", 1)[-1] not in [r.id for r in resources]
            ]

            # If no resources, we must fetch them
            if missing_resource_ids:
                logger.debug(f"PPM/FHIR: Missing {resource_type}/({', '.join(missing_resource_ids)})")
                resources.extend(
                    [
                        FHIRElementFactory.instantiate(resource_type, r)
                        for r in FHIR._query_resources(resource_type, query={"_id": ",".join(missing_resource_ids)})
                    ]
                )

            # Flatten them according to type
            if resource_type == "Organization":

                return [organization.name for organization in resources]

            elif resource_type == "ResearchStudy":

                return [study.title for study in resources]

            else:
                logger.error("Unhandled list resource type: {}".format(resource_type))
                return None

        except Exception as e:
            logger.exception(f"PPM/FHIR: Error: {e}", exc_info=True)

        return None

    @staticmethod
    def flatten_document_reference(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "id": str,
            "ppm_id": str,
            "timestamp": str,
            "date": optional[str],
            "code": str,
            "display": str,
            "title": str,
            "size": str,
            "hash": str,
            "url": str,
            "data": dict,
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """
        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Pick out properties and build a dict
        reference = dict({"id": FHIR._get_or(resource, ["id"])})

        # Get dates
        reference["timestamp"] = FHIR._get_or(resource, ["date"])
        if reference.get("timestamp"):
            reference["date"] = FHIR._format_date(reference["timestamp"], "%m/%d/%Y")

        # Get data provider
        reference["code"] = FHIR._get_or(resource, ["type", "coding", 0, "code"])
        reference["display"] = FHIR._get_or(resource, ["type", "coding", 0, "display"])

        # Get data properties
        reference["title"] = FHIR._get_or(resource, ["content", 0, "attachment", "title"])
        reference["size"] = FHIR._get_or(resource, ["content", 0, "attachment", "size"])
        reference["hash"] = FHIR._get_or(resource, ["content", 0, "attachment", "hash"])
        reference["url"] = FHIR._get_or(resource, ["content", 0, "attachment", "url"])

        # Flatten the list of identifiers into a key value dictionary
        if resource.get("identifier"):
            for identifier in resource.get("identifier", []):
                if identifier.get("system") and identifier.get("value"):
                    reference[identifier.get("system")] = identifier.get("value")

        # Get person
        reference["patient"] = FHIR._get_or(resource, ["subject", "reference"])
        if reference.get("patient"):
            reference["ppm_id"] = reference["fhir_id"] = FHIR._get_referenced_id(resource, "Patient")

        # Check for data
        reference["data"] = FHIR._get_or(resource, ["content", 0, "attachment", "data"])

        return reference

    @staticmethod
    def flatten_communication(resource: dict) -> dict:
        """
        Flattens the passed FHIR resource into a simplified
        representation for easier parsing.

        An example of the returned dict:

        {
            "identifier": str,
            "sent": str,
            "payload": str,
            "ppm_id": str,
        }

        :param resource: The resource to flatten
        :type resource: dict
        :return: A simplified representation of the resource as a dict
        :rtype: dict
        """
        # Get the actual resource in case we were handed a BundleEntry
        resource = FHIR._get_or(resource, ["resource"], resource)

        # Build it out
        record = dict()

        # Get identifier
        record["identifier"] = FHIR._get_or(resource, ["identifier", 0, "value"])
        record["sent"] = FHIR._get_or(resource, ["sent"])
        record["payload"] = FHIR._get_or(resource, ["payload", 0, "contentString"])

        # Get the recipient
        record["ppm_id"] = FHIR._get_referenced_id(resource, "Patient")

        return record

    @staticmethod
    def _asd_consent_quiz_answers(bundle: Union[Bundle, dict], questionnaire_id: str) -> list[str]:
        """
        Returns a list of the correct answer values for the given
        questionnaire quiz. This is pretty hardcoded so not that useful
        for anything but ASD consent quizzes.

        :param bundle_dict: A bundle resource from FHIR containing the Questionnaire
        :type bundle_dict: dict
        :param questionnaire_id: The FHIR ID of the Questionnaire to handle
        :type questionnaire_id: str
        :return: List of correct answer values for the consent quiz
        :rtype: list[str]
        """

        # Build the bundle
        if type(bundle) is dict:
            bundle = Bundle(bundle)

        # Pick out the questionnaire and its response
        questionnaire = next(
            (entry.resource for entry in bundle.entry if entry.resource.id == questionnaire_id),
            None,
        )

        # Ensure resources exist
        if not questionnaire:
            logger.debug("Missing Questionnaire: {}".format(questionnaire_id))
            return []

        # Return the correct answers
        answers = []

        # Check which questionnaire
        if questionnaire_id == "ppm-asd-consent-individual-quiz":

            answers = [
                questionnaire.item[0].option[0].valueString,
                questionnaire.item[1].option[0].valueString,
                questionnaire.item[2].option[1].valueString,
                questionnaire.item[3].option[3].valueString,
            ]

        elif questionnaire_id == "ppm-asd-consent-guardian-quiz":

            answers = [
                questionnaire.item[0].option[0].valueString,
                questionnaire.item[1].option[0].valueString,
                questionnaire.item[2].option[1].valueString,
                questionnaire.item[3].option[3].valueString,
            ]

        return answers

    class Resources:
        @staticmethod
        def enrollment_flag(
            patient_ref: str, study: str, status: str = "proposed", start: datetime = None, end: datetime = None
        ) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource. Passed `datetime`
            objects must be timezone-aware as arequirement set by the
            FHIR R4 specification.

            :param patient_ref: The reference to the Patient
            :type patient_ref: str
            :param study: The PPM study code for which this flag tracks for
            :type study: str
            :param status: The status of the participants enrollment, defaults to "proposed"
            :type status: str, optional
            :param start: The start date of enrollment, defaults to None
            :type start: datetime, optional
            :param end: The end date of enrollment, defaults to None
            :type end: datetime, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """

            data = {
                "resourceType": "Flag",
                "meta": {"lastUpdated": datetime.now(timezone.utc).isoformat()},
                "status": "active" if status == "accepted" else "inactive",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://hl7.org/fhir/flag-category",
                                "code": "admin",
                                "display": "Admin",
                            }
                        ],
                        "text": "Admin",
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": FHIR.enrollment_flag_coding_system,
                            "code": status,
                            "display": status.title(),
                        }
                    ],
                    "text": status.title(),
                },
                "subject": {"reference": patient_ref},
                "identifier": [
                    {
                        "system": FHIR.enrollment_flag_study_identifier_system,
                        "value": study,
                    },
                    {
                        "system": FHIR.enrollment_flag_patient_identifier_system,
                        "value": patient_ref.replace("urn:uuid:", ""),
                    },
                ],
            }

            # Set dates if specified.
            if start:
                data["period"] = {"start": start.isoformat()}
                if end:
                    data["period"]["end"] = end.isoformat()

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        @staticmethod
        def research_study(title: str, ppm_study: str = None, start: datetime = None, end: datetime = None) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param title: The title of the study
            :type title: str
            :param ppm_study: The code for the PPM-study, defaults to None
            :type ppm_study: str
            :param start: The start date of enrollment, defaults to None
            :type start: datetime, optional
            :param end: The end date of enrollment, defaults to None
            :type end: datetime, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """
            data = {
                "resourceType": "ResearchStudy",
                "title": title,
            }

            # If a PPM study, set ID and identifiers
            if ppm_study:

                data["id"] = PPM.Study.fhir_id(ppm_study)
                data.setdefault("identifier", []).append(
                    {
                        "system": FHIR.research_study_identifier_system,
                        "value": PPM.Study.fhir_id(ppm_study),
                    }
                )

                # Set status
                data["status"] = "active"

                # Set title
                data["title"] = f"People-Powered Medicine - {title}"

            # Hard code dates if not specified
            study = PPM.Study.get(ppm_study)
            if start:
                data["period"] = {"start": start.isoformat()}

            elif study is PPM.Study.NEER:
                data["period"] = {"start": "2018-05-01T00:00:00Z"}

            elif study is PPM.Study.ASD:
                data["period"] = {"start": "2017-07-01T00:00:00Z"}

            elif study is PPM.Study.RANT:
                data["period"] = {"start": "2020-11-01T00:00:00Z"}

            elif study is PPM.Study.EXAMPLE:
                data["period"] = {"start": "2020-01-01T00:00:00Z"}

            # End end if specified
            if end:
                data.setdefault("period", {})["end"] = end.isoformat()

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        @staticmethod
        def research_subject(
            patient_ref: str,
            research_study_ref: str,
            status: str = "candidate",
            start: datetime = datetime.now(timezone.utc),
        ) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient_ref: The reference to the Patient
            :type patient_ref: str
            :param research_study_ref: The reference to the ResearchStudy
            :type research_study_ref: str
            :param status: The status to set for the subject, defaults to None
            :type status: str
            :param start: The start date of enrollment, defaults to now
            :type start: datetime, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """

            data = {
                "resourceType": "ResearchSubject",
                "study": {"reference": research_study_ref},
                "individual": {"reference": patient_ref},
            }

            # Check if a PPM project
            try:
                study_id = research_study_ref.split("/", 1)[1]
                study = PPM.Study.get(study_id)

                # Set identifier
                data.setdefault("identifier", []).extend(
                    [
                        {
                            "system": FHIR.research_subject_study_identifier_system,
                            "value": PPM.Study.fhir_id(study),
                        },
                        {
                            "system": FHIR.research_subject_patient_identifier_system,
                            "value": patient_ref.replace("urn:uuid:", ""),
                        },
                    ]
                )

                # Set status
                data["status"] = status

                # Set period to now
                data.setdefault("period", {})["start"] = start.isoformat()

            except Exception:
                pass

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        @staticmethod
        def ppm_device(
            patient_ref: str,
            study: str,
            code: str,
            display: str,
            title: str,
            identifier: str,
            shipped: datetime = None,
            returned: datetime = None,
            status: str = "active",
            note: str = None,
            tracking: str = None,
        ) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient_ref: The reference to the Patient
            :type patient_ref: str
            :param study: The study for which this device is being used
            :type study: str
            :param code: The code to use for the device
            :type code: str
            :param display: The code display for the device
            :type display: str
            :param title: The title to use for the device
            :type title: str
            :param identifier: The identifier of the device
            :type identifier: str
            :param shipped: When it was shipped, defaults to None
            :type shipped: datetime, optional
            :param returned: When it was returned, defaults to None
            :type returned: datetime, optional
            :param status: The status of the device, defaults to "active"
            :type status: str, optional
            :param note: An optional note to add to the device, defaults to None
            :type note: str, optional
            :param tracking: The tracking number for the device, defaults to None
            :type tracking: str, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """

            data = {
                "resourceType": "Device",
                "identifier": [
                    {
                        "system": FHIR.device_identifier_system,
                        "value": identifier,
                    },
                    {
                        "system": FHIR.device_title_system,
                        "value": title,
                    },
                ],
                "type": {
                    "coding": [
                        {
                            "system": FHIR.device_coding_system,
                            "code": code,
                            "display": display,
                        }
                    ],
                    "text": display,
                },
                "status": status,
                "patient": {"reference": patient_ref},
                "extension": [
                    {
                        "url": FHIR.device_study_extension_url,
                        "valueString": study,
                    }
                ],
            }

            # Check dates
            if shipped:

                # Ensure datetime has timezone
                if shipped.tzinfo is None or shipped.tzinfo.utcoffset(shipped) is None:
                    shipped = shipped.replace(tzinfo=timezone.utc)

                data["manufactureDate"] = shipped.isoformat()

            if returned:

                # Ensure datetime has timezone
                if returned.tzinfo is None or returned.tzinfo.utcoffset(returned) is None:
                    returned = returned.replace(tzinfo=timezone.utc)

                data["expirationDate"] = returned.isoformat()

            if note:
                data["note"] = [
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "text": note,
                    }
                ]

            if tracking:
                data["identifier"].append(
                    {
                        "system": FHIR.device_tracking_system,
                        "value": tracking,
                    }
                )

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        @staticmethod
        def communication(
            patient_ref: str,
            identifier: str,
            content: str = None,
            status: str = "completed",
            sent: datetime = datetime.now(timezone.utc),
        ) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient_ref: The reference to the Patient
            :type patient_ref: str
            :param identifier: The identifier of the communication
            :type identifier: str
            :param content: The content of the communication
            :type content: str
            :param status: The status of the communication, defaults to "sent"
            :type status: str, optional
            :param sent: When it was sent, defaults to now
            :type sent: datetime, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """
            data = {
                "resourceType": "Communication",
                "identifier": [
                    {
                        "system": FHIR.ppm_comm_identifier_system,
                        "value": identifier,
                    }
                ],
                "sent": sent,
                "recipient": [{"reference": patient_ref}],
                "status": status,
            }

            # Hard code dates
            if content:
                data["payload"] = [{"contentString": content}]

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        @staticmethod
        def patient(
            email: str,
            first_name: str,
            last_name: str,
            addresses: list[str],
            city: str,
            state: str,
            zip: str,
            phone: str = None,
            contact_email: str = None,
            how_heard_about_ppm: str = None,
        ) -> dict:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param email: The email of the participant
            :type email: str
            :param first_name: The first name of the participant
            :type first_name: str
            :param last_name: The last name of the participant
            :type last_name: str
            :param addresses: The list of street address strings for the
            participant
            :type addresses: list[str]
            :param city: The participants address city
            :type city: str
            :param state: The participants address state
            :type state: str
            :param zip: The participants address zip
            :type zip: str
            :param phone: The participants phone number, defaults to None
            :type phone: str, optional
            :param contact_email: The participants alternative contact email,
            defaults to None
            :type contact_email: str, optional
            :param how_heard_about_ppm: How the participant heard about PPM,
            defaults to None
            :type how_heard_about_ppm: str, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource as a JSON-formatted dict
            :rtype: dict
            """

            # Build a FHIR-structured Patient resource.
            data = {
                "resourceType": "Patient",
                "active": True,
                "identifier": [
                    {
                        "system": FHIR.patient_email_identifier_system,
                        "value": email,
                    },
                ],
                "name": [
                    {
                        "use": "official",
                        "family": last_name,
                        "given": [first_name],
                    },
                ],
                "address": [
                    {
                        "line": addresses,
                        "city": city,
                        "postalCode": zip,
                        "state": state,
                    }
                ],
                "telecom": [
                    {
                        "system": FHIR.patient_phone_telecom_system,
                        "value": phone,
                    },
                ],
            }

            if contact_email:
                logger.debug("Adding contact email")
                data["telecom"].append(
                    {
                        "system": FHIR.patient_email_telecom_system,
                        "value": contact_email,
                    }
                )

            if how_heard_about_ppm:
                logger.debug('Adding "How did you hear about us"')
                data["extension"] = [
                    {
                        "url": FHIR.referral_extension_url,
                        "valueString": how_heard_about_ppm,
                    }
                ]

            # Validate the resource
            FHIRElementFactory.instantiate(data["resourceType"], data)

            return data

        def questionnaire_response_answer(
            value: Union[str, bool, int, float, date, datetime, list]
        ) -> list[dict[str, Union[str, int, float, bool]]]:
            """
            Takes the value for the passed answer and formats it as a FHIR
            value element to be set for a questionnaire response item answer.

            :param value: The value for the answer
            :type value: Union[str, bool, int, float, date, datetime, list]
            :raises Exception: Raises exception if value is an unhandled type
            :return: The FHIR answer items
            :rtype: list[dict[str, Union[str, int, float, bool]]]
            """
            # Get answers
            answers = None

            # Check type
            if type(value) is str:
                answers = [{"valueString": value}]

            elif type(value) is int:
                answers = [{"valueInteger": value}]

            elif type(value) is float:
                answers = [{"valueDecimal": value}]

            elif type(value) is date:
                answers = [{"valueDate": value.isoformat()}]

            elif type(value) is datetime:
                answers = [{"valueDateTime": value.isoformat()}]

            elif type(value) is bool:
                answers = [{"valueBoolean": value}]

            elif type(value) is list:
                answers = [FHIR.Resources.questionnaire_response_answer(a)[0] for a in value]

            else:
                raise Exception(f"FHIR/Resources: Unhandled answer type {value} ({type(value)})")

            return answers

        @staticmethod
        def reference_to(resource: DomainResource) -> FHIRReference:
            """
            Creates and returns a reference object to be used between FHIR
            resources. If a resource with a temporary ID is passed
            (e.g. an UUID) then the reference string is modified to not
            include the resource type as a prefix.

            :param resource: A FHIR resource
            :type resource: DomainResource
            :returns: A FHIR reference object
            :rtype: FHIRReference
            """
            reference = FHIRReference()

            # Check for a temporary ID and format reference accordingly
            if resource.id.startswith("urn:"):
                reference.reference = resource.id
            else:
                reference.reference = f"{resource.resource_type}/{resource.id}"

            return reference

        @staticmethod
        def reference(resource_type: str, resource_id: str) -> FHIRReference:
            """
            Creates and returns a reference object to be used between FHIR
            resources. If a resource with a temporary ID is passed
            (e.g. an UUID) then the reference string is modified to not
            include the resource type as a prefix.

            :param resource_type: The FHIR resource type
            :type resource_type: str
            :param resource_id: The FHIR resource ID to reference
            :type resource_id: str
            :returns: A FHIR reference object
            :rtype: FHIRReference
            """
            # Check for a temporary ID and format reference accordingly
            if resource_id.startswith("urn:"):
                reference = FHIRReference({"reference": resource_id})
            else:
                reference = FHIRReference({"reference": f"{resource_type}/{resource_id}"})

            return reference

        @staticmethod
        def questionnaire_response(
            questionnaire: Questionnaire,
            patient: Patient,
            date: datetime = datetime.now(timezone.utc),
            answers: dict[str, Any] = {},
            author: DomainResource = None,
        ) -> QuestionnaireResponse:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param questionnaire: The source Questionnaire resource
            :type questionnaire: Questionnaire
            :param patient: The Patient who created the response
            :type patient: Patient
            :param date: The date of the response, defaults to
            datetime.now(timezone.utc)
            :type date: datetime, optional
            :param answers: The mapping of link ID to answers, defaults to {}
            :type answers: dict[str, Any], optional
            :param author: The author, if not the Patient, defaults to None
            :type author: DomainResource, optional
            :raises FHIRValidationError: If the resource fails FHIR validation
            :return: The FHIR resource
            :rtype: QuestionnaireResponse
            """

            # Get URL
            canonical_url = furl(PPM.fhir_url()) / "Questionnaire" / questionnaire.id

            # Build the response
            response = QuestionnaireResponse()
            response.id = uuid.uuid1().urn
            response.questionnaire = canonical_url.url
            response.source = FHIR.Resources.reference_to(patient)
            response.status = "completed"
            response.authored = FHIRDateTime(date.isoformat())
            response.author = FHIR.Resources.reference_to(author if author else patient)
            response.subject = FHIR.Resources.reference_to(questionnaire)

            # Collect response items flattened
            response.item = FHIR.Resources.questionnaire_response_items(questionnaire, answers)

            # Set it on the questionnaire
            return response

        @staticmethod
        def questionnaire_response_items(
            questionnaire_item: QuestionnaireItem, form: dict[str, Any]
        ) -> list[QuestionnaireResponseItem]:
            """
            Creates and returns a list of FHIR resources of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param questionnaire_item: The item from the questionnaire
            :type questionnaire_item: QuestionnaireItem
            :param form: The mapping of questionnaire link IDs to answers
            :type form: dict[str, Any]
            :return: A list of the FHIR resources
            :rtype: list[QuestionnaireResponseItem]
            """

            # Collect items
            items = []

            # Iterate through questions
            for question in questionnaire_item.item:

                # Determine if this is a required item or a dependently required item
                dependent = question.enableWhen or getattr(questionnaire_item, "enableWhen", False)

                # Disregard invalid question types
                if not question.linkId or not question.type or question.type == "display":
                    continue

                # If a group, process subelements and append them to current level
                elif question.type == "group":

                    # We don't respect heirarchy for groupings
                    group_items = FHIR.Resources.questionnaire_response_items(question, form)
                    if group_items:
                        items.extend(group_items)
                    continue

                # Get the value
                value = form.get(question.linkId, form.get(question.linkId, None))

                # Add the item
                if value is None or not str(value):
                    if question.required and not dependent:
                        logger.warning("PPM/{}: No answer for {}".format(form.get("questionnaire_id"), question.linkId))
                    continue

                # Check for an empty list
                elif type(value) is list and len(value) == 0:
                    if question.required and not dependent:
                        logger.warning(
                            "PPM/{}: Empty answer set for {}".format(form.get("questionnaire_id"), question.linkId)
                        )
                    continue

                # Create the item
                response_item = FHIR.Resources.questionnaire_response_item(question.linkId, value)

                # Add the item
                items.append(response_item)

                # Check for subitems
                if question.item:

                    # Get the items
                    question_items = FHIR.Resources.questionnaire_response_items(question, form)
                    if question_items:
                        # TODO: Uncomment Line
                        # After QuestionnaireResponse parsing is updated to
                        # look for subanswers in subitems as opposed to one
                        # flat list, enable the following line:
                        # item.item = question_items

                        # Save all answers flat for now
                        items.extend(question_items)

            return items

        @staticmethod
        def questionnaire_response_item(link_id: str, cleaned_data: dict[str, Any]):
            """
            Creates and returns a list of FHIR resources of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param link_id: The link ID of the item from the questionnaire
            :type link_id: str
            :param cleaned_data: The mapping of questionnaire link IDs to answers
            :type cleaned_data: dict[str, Any]
            :return: The FHIR resources
            :rtype: QuestionnaireResponseItem
            """

            # Create the response item
            item = QuestionnaireResponseItem()
            item.linkId = link_id

            # Create the answer items list
            item.answer = []

            # Check the value type
            if type(cleaned_data) is list:

                # Add each item in the list
                for value in cleaned_data:
                    item.answer.append(FHIR.Resources.questionnaire_response_item_answer(value))

            else:

                # Add the single item
                item.answer.append(FHIR.Resources.questionnaire_response_item_answer(cleaned_data))

            return item

        @staticmethod
        def questionnaire_response_item_answer(
            value: Union[str, bool, int, date, datetime, list]
        ) -> QuestionnaireResponseItemAnswer:
            """
            Takes the value for the passed answer and formats it as a FHIR
            value element to be set for a questionnaire response item answer.
            If the type of the value is not specifically handled, it will be
            cast as a string.

            :param value: The value for the answer
            :type value: Union[str, bool, int, date, datetime, list]
            :raises Exception: Raises exception if value is an unhandled type
            :return: The FHIR resource
            :rtype: QuestionnaireResponseItemAnswer
            """

            # Create the item
            answer = QuestionnaireResponseItemAnswer()

            # Check type
            if type(value) is str:
                answer.valueString = str(value)

            elif type(value) is bool:
                answer.valueBoolean = value

            elif type(value) is int:
                answer.valueInteger = value

            elif type(value) is datetime:
                answer.valueDateTime = FHIRDateTime(value.isoformat())

            elif type(value) is date:
                answer.valueDate = FHIRDate(value.isoformat())

            else:
                logger.warning("Unhandled answer type: {} - {}".format(type(value), value))

                # Cast it as string
                answer.valueString = str(value)

            return answer

        @staticmethod
        def consent_exceptions(codes: list[str]) -> Extension:
            """
            Accepts a list of PPM consent exception codes and returns
            an Exception object that can be set on a FHIR resource to
            track what parts of the study the participant opted out of.

            :param codes: The list of PPM exception codes
            :type codes: list[str]
            :return: A FHIR Extension object
            :rtype: Extension
            """

            # Map codes to displays
            displays = {
                "284036006": "Equipment monitoring",
                "702475000": "Referral to clinical trial",
                "82078001": "Taking blood sample",
                "165334004": "Stool sample sent to lab",
                "258435002": "Tumor tissue sample",
                "225098009": "Collection of sample of saliva",
            }

            # Create codeable concept
            codeable_concept = CodeableConcept()
            codeable_concept.coding = [
                FHIR.Resources.coding(system="http://snomed.info/sct", code=c, display=displays[c]) for c in codes
            ]
            codeable_concept.text = "Deny"

            # Create extension
            extension = Extension()
            extension.url = FHIR.consent_exception_extension_url
            extension.valueCodeableConcept = codeable_concept

            return extension

        @staticmethod
        def related_person(patient: Patient, name: str, relationship: str) -> RelatedPerson:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient: The Patient this person is related to
            :type patient: Patient
            :param name: The name of the related person
            :type name: str
            :param relationship: The relationship between Patient and person
            :type relationship: str
            :return: The FHIR resource
            :rtype: RelatedPerson
            """

            # Make it
            person = RelatedPerson(strict=True)
            person.id = uuid.uuid1().urn
            person.patient = FHIR.Resources.reference_to(patient)

            # Set the relationship
            code = CodeableConcept()
            code.text = relationship
            person.relationship = code

            # Set the name
            human_name = HumanName()
            human_name.text = name
            person.name = [human_name]

            return person

        @staticmethod
        def consent(
            patient: Patient, date: datetime, exceptions: list[str] = None, related_person: RelatedPerson = None
        ) -> Consent:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient: The Patient that completed the Consent
            :type patient: Patient
            :param date: The date of completion
            :type date: datetime
            :param exceptions: A list of exception codes, defaults to None
            :type exceptions: list[str], optional
            :param related_person: A person who assisted in consent completion,
            defaults to None
            :type related_person: RelatedPerson, optional
            :return: The FHIR resource
            :rtype: Consent
            """

            # Make it
            consent = Consent()
            consent.status = "proposed"
            consent.id = uuid.uuid1().urn
            consent.dateTime = FHIRDateTime(date.isoformat())
            consent.patient = FHIR.Resources.reference_to(patient)

            # Policy
            policy = ConsentPolicy()
            policy.authority = "HMS-DBMI"
            policy.uri = "https://hms.harvard.edu"
            consent.policy = [policy]

            # Category
            category_codeable_concept = CodeableConcept()
            category_codeable_concept.coding = [
                FHIR.Resources.coding("http://hl7.org/fhir/v3/ActReason", "HRESCH", "healthcare research")
            ]
            consent.category = [category_codeable_concept]

            # Scope
            scope_codeable_concept = CodeableConcept()
            scope_codeable_concept.coding = [
                FHIR.Resources.coding("http://terminology.hl7.org/CodeSystem/consentscope", "research", "Research")
            ]
            consent.scope = scope_codeable_concept

            # Add exceptions as an extension
            if exceptions:
                if consent.extension:
                    consent.extension.extend(exceptions)
                else:
                    consent.extension = [exceptions]

            return consent

        @staticmethod
        def contract(
            patient: Patient,
            date: datetime,
            patient_name: str,
            patient_signature: str,
            questionnaire_response: QuestionnaireResponse = None,
        ) -> Contract:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient: The Patient that completed the contract
            :type patient: Patient
            :param date: The date of completion
            :type date: datetime
            :param patient_name: The name as input by the patient
            :type patient_name: str
            :param patient_signature: The signature as input by the patient
            :type patient_signature: str
            :param questionnaire_response: A response to a related
            questionnaire, defaults to None
            :type questionnaire_response: QuestionnaireResponse, optional
            :return: The FHIR resource
            :rtype: Contract
            """

            # Build it
            contract = Contract(strict=True)
            contract.status = "executed"
            contract.issued = FHIRDateTime(date.isoformat())
            contract.id = uuid.uuid1().urn
            contract.subject = [FHIR.Resources.reference_to(patient)]

            # Signer
            signer = ContractSigner()
            signer.type = FHIR.Resources.coding(
                "http://hl7.org/fhir/ValueSet/contract-signer-type", "CONSENTER", "Consenter"
            )
            signer.party = FHIR.Resources.reference_to(patient)

            # Signature
            signature = Signature()
            signature.type = [
                FHIR.Resources.coding(
                    "http://hl7.org/fhir/ValueSet/signature-type", "1.2.840.10065.1.12.1.7", "Consent Signature"
                )
            ]
            signature.when = FHIRInstant(date.isoformat())
            signature.sigFormat = "text/plain"
            signature.data = FHIR.Resources.blob(patient_signature)
            signature.who = FHIR.Resources.reference_to(patient)
            signature.who.display = patient_name

            # Add references
            signer.signature = [signature]
            contract.signer = [signer]

            # Add questionnaire if passed
            if questionnaire_response:
                contract.legallyBindingReference = FHIR.Resources.reference_to(questionnaire_response)

            return contract

        @staticmethod
        def related_contract(
            patient: Patient,
            date: datetime,
            patient_name: str,
            related_person: RelatedPerson,
            related_person_name: str,
            related_person_signature: str,
            questionnaire_response: QuestionnaireResponse,
        ) -> Contract:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient: The Patient for which the Contract was completed
            :type patient: Patient
            :param date: The date of completion
            :type date: datetime
            :param patient_name: The name of the Patient
            :type patient_name: str
            :param related_person: The person who assisted the patient with
            the contract
            :type related_person: RelatedPerson
            :param related_person_name: The name of the related person
            :type related_person_name: str
            :param related_person_signature: The signature of the related
            person
            :type related_person_signature: str
            :param questionnaire_response: The questionnaire response that
            is associated with completion of the contract
            :type questionnaire_response: QuestionnaireResponse
            :return: The FHIR resource
            :rtype: Contract
            """

            # Build it
            contract = Contract()
            contract.status = "executed"
            contract.issued = FHIRDateTime(date.isoformat())
            contract.id = uuid.uuid1().urn

            # Signer
            contract_signer = ContractSigner()
            contract_signer.type = FHIR.Resources.coding(
                "http://hl7.org/fhir/ValueSet/contract-signer-type", "CONSENTER", "Consenter"
            )
            contract_signer.party = FHIR.Resources.reference_to(related_person)

            # Signature
            signature = Signature()
            signature.type = [
                FHIR.Resources.coding(
                    "http://hl7.org/fhir/ValueSet/signature-type", "1.2.840.10065.1.12.1.7", "Consent Signature"
                )
            ]
            signature.when = FHIRInstant(date.isoformat())
            signature.sigFormat = "text/plain"
            signature.data = FHIR.Resources.blob(related_person_signature)
            signature.who = FHIR.Resources.reference_to(related_person)
            signature.who.display = related_person_name

            # Refer to the patient
            patient_reference = FHIRReference(
                {"reference": "{}/{}".format(patient.resource_type, patient.id), "display": patient_name}
            )
            signature.onBehalfOf = patient_reference

            # Add references
            contract_signer.signature = [signature]
            contract.signer = [contract_signer]
            contract.legallyBindingReference = FHIR.Resources.reference_to(questionnaire_response)

            return contract

        @staticmethod
        def composition(
            patient: Patient, date: datetime, text: str, study: PPM.Study | str, resources: list[DomainResource] = []
        ) -> Composition:
            """
            Creates and returns a FHIR resource of the given type for
            the passed arguments. All PPM codings and identifiers are handled
            automatically with the exception of instances where they are
            set depending on the use of the resource.

            :param patient: The Patient the Composition and related resources
            belong to
            :type patient: Patient
            :param date: The date the Composition was created
            :type date: datetime
            :param text: The text to set for the Composition
            :type text: str
            :param study: The study for which this resource applies
            :type study: PPM.Study | str
            :param resources: A list of resources related to the composition,
            defaults to []
            :type resources: list[DomainResource], optional
            :return: The FHIR resource
            :rtype: Composition
            """

            # Build it
            composition = Composition()
            composition.id = uuid.uuid1().urn
            composition.status = "final"
            composition.subject = FHIR.Resources.reference_to(patient)
            composition.date = FHIRDateTime(date.isoformat())
            composition.title = "Signature"
            composition.author = [FHIRReference({"reference": "Device/hms-dbmi-ppm-consent"})]

            # Composition type
            coding = Coding()
            coding.system = "http://loinc.org"
            coding.code = "83930-8"
            coding.display = "Research Consent"

            # Convoluted code property
            code = CodeableConcept()
            code.coding = [coding]

            # Combine
            composition.type = code

            # Add sections
            composition.section = []

            # Add text
            narrative = Narrative()
            narrative.div = text
            narrative.status = "additional"
            text_section = CompositionSection()
            text_section.text = narrative
            composition.section.append(text_section)

            # Add related section resources
            for resource in resources:

                # Add consent
                consent_section = CompositionSection()
                consent_section.entry = [FHIR.Resources.reference_to(resource)]
                composition.section.append(consent_section)

            # Add study reference
            study_section = CompositionSection()
            study_section.entry = [FHIRReference({"reference": f"ResearchStudy/{PPM.Study.fhir_id(study)}"})]
            composition.section.append(study_section)

            return composition

        @staticmethod
        def code(system: str, code: str, display: str) -> CodeableConcept:
            """
            Creates and returns a FHIR codeable concept element.

            :param system: The system of the concept
            :type system: str
            :param code: The code of the concept
            :type code: str
            :param display: The display text for the concept
            :type display: str
            :return: The FHIR element
            :rtype: CodeableConcept
            """

            # Build it
            coding = Coding()
            coding.system = system
            coding.code = code
            coding.display = display

            # Convoluted code property
            codeable = CodeableConcept()
            codeable.coding = [coding]

            return codeable

        @staticmethod
        def coding(system: str, code: str, display: str = None) -> Coding:
            """
            Creates and returns a FHIR coding element.

            :param system: The system of the concept
            :type system: str
            :param code: The code of the concept
            :type code: str
            :param display: The display text for the concept
            :type display: str
            :return: The FHIR element
            :rtype: Coding
            """

            # Build it
            coding = Coding()
            coding.system = system
            coding.code = code
            coding.display = display

            return coding

        @staticmethod
        def blob(value: str) -> str:
            """
            Creates and returns a string that is base64 encoded.

            :param value: The source string
            :type value: str
            :return: The base64 encoded string
            :rtype: str
            """
            # Base64 encode it
            return base64.b64encode(str(value).encode("utf-8")).decode("utf-8")

        @staticmethod
        def bundle(
            resources: list[DomainResource], bundle_type: Literal["batch", "transaction"] = "transaction"
        ) -> Bundle:
            """
            Creates and returns a FHIR Bundle with the given resources
            as entries with method set to POST. This is for creating a set
            of resources concurrently.

            :param resources: The list of resources to include in the bundle
            :type resources: list[DomainResource]
            :param bundle_type: The type of the bundle, defaults to "transaction"
            :type bundle_type: Literal["batch", "transaction"], optional
            :raises ValueError: If bundle type "batch" is passed with temporary
            resource IDs
            :return: The FHIR resource
            :rtype: Bundle
            """

            # Build the bundle
            bundle = Bundle()
            bundle.type = bundle_type
            bundle.entry = []

            for resource in resources:

                # Build the entry request
                bundle_entry_request = BundleEntryRequest()
                bundle_entry_request.method = "POST"
                bundle_entry_request.url = resource.resource_type

                # Drop the ID if it's a temporary ID
                resource_id = resource.id
                if resource_id and resource_id.startswith("urn:"):
                    if bundle_type != "transaction":
                        raise ValueError(f"Cannot use temporary IDs with bundle type '{bundle_type}'")
                    resource.id = None

                elif resource_id:
                    # Make it a PUT since we are specifying the ID at creation
                    bundle_entry_request.method = "PUT"
                    bundle_entry_request.url = f"{resource.resource_type}/{resource_id}"

                # Add it to the entry
                bundle_entry = BundleEntry()
                bundle_entry.resource = resource
                bundle_entry.request = bundle_entry_request

                # Set resource ID as URL if specified
                if resource_id:
                    bundle_entry.fullUrl = resource_id

                # Add it
                bundle.entry.append(bundle_entry)

            return bundle

    class Operations(object):
        """
        This class manages updates to be performed on the PPM FHIR DB. Each
        method prefixed with `_op_` is run in sequence and each should perform
        operations on the FHIR DB to make fixes, tweaks, or modifications to
        existing resources. Each operation is required to be idempotent and
        will be run repeatedly with every iteration of updates.
        """

        PREFIX = "_op_"

        def __init__(self):
            pass

        def get_operations(self):
            """
            Builds a list of operations to run, sorted by date in method name.
            Returns the list of method objects to be called by caller.
            """
            obj = FHIR.Operations()

            # Collect operation methods
            ops = [m for m in dir(obj) if m.startswith(FHIR.Operations.PREFIX)]

            # Ensure each method has a valid name
            for op in ops:
                try:
                    # Ensure we can parse date in order to sort
                    datetime.strptime(op.rsplit("_", 1)[1], "%Y%m%d")

                except Exception:
                    raise ValueError(f"Operation '{op}' has invalid name")

            # Sort by date
            ops.sort(key=lambda date: datetime.strptime(date.rsplit("_", 1)[1], "%Y%m%d"))

            return [getattr(self, op) for op in ops]

        def run(self, *args, **kwargs):
            """
            Runs the operations in order by the date in the method name `ddmmyyyy`
            """
            # Execute
            for op in self.get_operations():
                logger.info("----- FHIR/Ops: Starting '{}' -----".format(op.__name__))
                success, message = op(*args, **kwargs)
                if success:
                    logger.info("----- FHIR/Ops: Completed '{}' ----".format(op.__name__))
                else:
                    logger.error("----- FHIR/Ops: Failed '{}' ----".format(op.__name__))
                    logger.error("----- FHIR/Ops: '{}' Message: ----\n{}\n".format(op.__name__, message))
                    logger.info("----- FHIR/Ops: Operation failed, halting operations ----")
                    break
