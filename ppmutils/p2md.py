from ppmutils.ppm import PPM

import logging
logger = logging.getLogger(__name__)


class P2MD(PPM.Service):

    service = 'P2MD'

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
        response = cls.head(request, '/smart/{}/auths'.format(ppm_id), raw=True)

        return response.ok

    @classmethod
    def get_smart_authorizations(cls, request, ppm_id):
        """
        Make a request to P2MD to get a list of SMART providers authorized by the participant.
        """
        # Make the request
        data = cls.head(request, '/smart/{}/auths'.format(ppm_id))

        # Return auths
        auths = data.get("smart_authorizations", [])

        return auths

    @classmethod
    def get_operations(cls, request, ppm_id):
        """
        Make a request to P2MD to get a full history of all data operations conducted
        for the participant.
        """
        return cls.get(request, '/api/ppm/{}'.format(ppm_id))

    @classmethod
    def get_twitter_data(cls, request, ppm_id, handle):
        """
        Make a request to P2MD to fetch Twitter data and store it in PPM.
        """
        response = cls.post(request, '/api/twitter/{}'.format(ppm_id), {'handle': handle}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_fitbit_data(cls, request, ppm_id):
        """
        Make a request to P2MD to fetch Fitbit data and store it in PPM.
        """
        response = cls.post(request, '/api/fitbit/{}'.format(ppm_id), data={}, raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_gencove_data(cls, request, ppm_id, gencove_id):
        """
        Make a request to P2MD to fetch Gencove data and store it in PPM.
        """
        response = cls.post(request, '/api/gencove/{}'.format(ppm_id), raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_facebook_data(cls, request, ppm_id):
        """
        Make a request to P2MD to fetch Facebook data and store it in PPM.
        """
        response = cls.post(request, '/api/facebook/{}'.format(ppm_id), raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_smart_data(cls, request, ppm_id, provider):
        """
        Make a request to P2MD to fetch SMART on FHIR EHR data and store it in PPM.
        """
        response = cls.post(request, '/api/smart/{}/{}'.format(provider, ppm_id), raw=True)

        # Return True if no errors
        return response.ok

    @classmethod
    def get_files(cls, request, ppm_id):
        """
        Queries P2MD for all uploaded files related to this participant.
        """
        return cls.get(request, '/api/file/{}'.format(ppm_id))

    @classmethod
    def create_file(cls, request, ppm_id, document_type, filename, metadata={}, tags=[]):
        """
        Make a request to P2MD to create a file upload
        """
        # Set data
        data = {'type': document_type, 'filename': filename, 'metadata': metadata, 'tags': tags}

        # Get the file data
        upload = cls.post(request, '/api/file/{}'.format(ppm_id), data)

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
        return cls.patch(request, '/api/file/{}'.format(ppm_id), data)

    @classmethod
    def get_smart_endpoints(cls, request):
        """
        Return a list of all registered SMART endpoints
        :param request: The current HttpRequest
        :return: list
        """
        return cls.get(request, '/smart')
