from furl import furl

from ppmutils.ppm import PPM
from ppmutils.fhir import FHIR

import logging
logger = logging.getLogger(__name__)


class P2MD(PPM.Service):

    service = 'P2MD'

    # This is the system prefix used for coding DocumentReferences created by P2MD
    system = 'https://peoplepoweredmedicine.org/document-type'

    # Set identifier systems
    p2md_identifier_system = 'https://peoplepoweredmedicine.org/fhir/p2md/operation'
    fileservice_identifier_system = 'https://peoplepoweredmedicine.org/fhir/fileservice/file'

    @classmethod
    def get_authorizations(cls, request, ppm_ids):
        """
        Make a request to P2MD to determine what providers all participants have authorized.
        """
        return cls.get(request, 'auths', {'ppm_ids': ','.join(ppm_ids)})

    @classmethod
    def has_smart_authorization(cls, request, ppm_id):
        """
        Make a request to P2MD to determine if a participant has authorized any SMART provider.
        """
        # Return True if no errors
        response = cls.head(request, f'/sources/smart/{ppm_id}/auths', raw=True)

        return response.ok

    @classmethod
    def get_smart_authorizations(cls, request, ppm_id):
        """
        Make a request to P2MD to get a list of SMART providers authorized by the participant.
        """
        # Make the request
        data = cls.head(request, f'/sources/smart/{ppm_id}/auths')

        # Return auths
        auths = data.get("smart_authorizations", [])

        return auths

    @classmethod
    def get_operations(cls, request, ppm_id):
        """
        Make a request to P2MD to get a full history of all data operations conducted
        for the participant.
        """
        return cls.get(request, f'/sources/api/ppm/{ppm_id}')

    @classmethod
    def get_twitter_data(cls, request, ppm_id, handle):
        """
        Make a request to P2MD to fetch Twitter data and store it in PPM.
        """
        response = cls.post(request, f'/sources/api/twitter/{ppm_id}', {'handle': handle}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_fitbit_data(cls, request, ppm_id):
        """
        Make a request to P2MD to fetch Fitbit data and store it in PPM.
        """
        response = cls.post(request, f'/sources/api/fitbit/{ppm_id}', data={}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_gencove_data(cls, request, ppm_id, gencove_id):
        """
        Make a request to P2MD to fetch Gencove data and store it in PPM.
        """
        response = cls.post(request, f'/sources/api/gencove/{ppm_id}', data={'gencove_id': gencove_id}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_facebook_data(cls, request, ppm_id):
        """
        Make a request to P2MD to fetch Facebook data and store it in PPM.
        """
        response = cls.post(request, f'/sources/api/facebook/{ppm_id}', data={}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_smart_data(cls, request, ppm_id, provider):
        """
        Make a request to P2MD to fetch SMART on FHIR EHR data and store it in PPM.
        """
        response = cls.post(request, f'/sources/api/smart/{provider}/{ppm_id}', data={}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_files(cls, request, ppm_id):
        """
        Queries P2MD for all uploaded files related to this participant.
        """
        return cls.get(request, f'/sources/api/file/{ppm_id}')

    @classmethod
    def create_file(cls, request, ppm_id, document_type, filename, metadata=None, tags=None):
        """
        Make a request to P2MD to create a file upload
        """
        # Set data
        data = {'type': document_type, 'filename': filename}

        # Add metadata and tags if passed
        if metadata:
            data['metadata'] = metadata

        if tags:
            data['tags'] = tags

        # Get the file data
        upload = cls.post(request, f'/sources/api/file/{ppm_id}', data)

        # Get the UUID
        uuid = upload.get('uuid')

        # Return True if no errors
        return uuid, upload

    @classmethod
    def uploaded_file(cls, request, ppm_id, document_type, uuid, location):
        """
        Make a request to P2MD to create a file upload
        """
        # Set data
        data = {'uuid': uuid, 'location': location, 'type': document_type}

        # Return True if no errors
        return cls.patch(request, f'/sources/api/file/{ppm_id}', data)

    @classmethod
    def get_smart_endpoints(cls, request):
        """
        Return a list of all registered SMART endpoints
        :param request: The current HttpRequest
        :return: list
        """
        return cls.get(request, '/sources/smart')

    @classmethod
    def get_providers(cls, request):
        """
        Return a list of all registered data providers' codes and titles
        :param request: The current HttpRequest
        :return: list
        """
        return cls.get(request, f'/sources/api/provider')

    @classmethod
    def get_file_types(cls, request):
        """
        Return a list of all registered data providers' codes and titles
        :param request: The current HttpRequest
        :return: list
        """
        return cls.get(request, f'/sources/api/file/type')

    @classmethod
    def get_data_document_references(cls, ppm_id, provider=''):
        """
        Queries the current user's FHIR record for any DocumentReferences related to this type
        :return: A list of DocumentReferences
        :rtype: list
        """
        # Gather data-related DocumentReferences
        query = {'type': f'{P2MD.system}|{provider}'}
        document_references = FHIR.query_document_references(ppm_id, query)

        logger.debug(f'Found {len(document_references)} DocumentReferences for: {ppm_id}')

        # Flatten resources and pick out relevant identifiers
        flats = []
        for document_reference in document_references:

            # Flatten it
            flat = FHIR.flatten_document_reference(document_reference['resource'])

            # Pick out P2MD and Fileservice identifiers
            if P2MD.p2md_identifier_system in flat:
                flat['p2md_id'] = flat[P2MD.p2md_identifier_system]
                del flat[P2MD.p2md_identifier_system]

            if P2MD.fileservice_identifier_system in flat:
                flat['fileservice_id'] = flat[P2MD.fileservice_identifier_system]
                del flat[P2MD.fileservice_identifier_system]

            elif flat.get('url'):
                # To support older documents, try to parse it from URL
                url = furl(flat['url'])
                flat['fileservice_id'] = url.path.segments.pop(3)

            else:
                # Just make it empty
                flat['fileservice_id'] = 'ERROR'

            flats.append(flat)

        return flats
