import os

from ppmutils.ppm import PPM

import logging
logger = logging.getLogger(__name__)


class P2M2(PPM.Service):

    service = 'P2M2'

    @classmethod
    def default_url_for_env(cls, environment):
        """
        Give implementing classes an opportunity to list a default set of URLs based on the DBMI_ENV,
        if specified. Otherwise, return nothing
        :param environment: The DBMI_ENV string
        :return: A URL, if any
        """
        if 'local' in environment:
            return 'http://localhost:8010'
        elif 'dev' in environment:
            return 'https://p2m2.aws.dbmi-dev.hms.harvard.edu'
        elif 'prod' in environment:
            return 'https://p2m2.dbmi.hms.harvard.edu'
        else:
            logger.error(f'Could not return a default URL for environment: {environment}')

        return None

    @classmethod
    def get_download_url(cls):
        return cls._build_url('/dashboard/download/')

    @classmethod
    def get_dashboard_url(cls):
        return cls._build_url('/dashboard/dashboard/')

    @classmethod
    def get_user(cls, request, email):
        return cls.post(request, '/api/user', {'email': email})

    @classmethod
    def get_participant(cls, request, email):
        return cls.post(request, '/api/participant', {'email': email})

    @classmethod
    def get_participants(cls, request, emails):
        return cls.post(request, '/api/participants', {'emails': emails})

    @classmethod
    def get_application(cls, request, email):
        return cls.post(request, '/api/application', {'email': email})

    @classmethod
    def get_applications(cls, request, emails):
        return cls.post(request, '/api/applications', {'emails': emails})

    @classmethod
    def get_authorization(cls, request, email):
        return cls.post(request, '/api/authorization', {'email': email})

    @classmethod
    def get_authorizations(cls, request, emails):
        return cls.post(request, '/api/authorizations', {'emails': emails})

    @classmethod
    def update_participant(cls, request, email, project):
        return cls.patch(request, '/api/participant', {'email': email, 'project': project})

    @classmethod
    def delete_user(cls, request, email):
        return cls.delete(request, '/api/user', {'email': email})
