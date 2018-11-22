from ppmutils.ppm import PPM

import logging
logger = logging.getLogger(__name__)


class P2M2(PPM.Service):

    service = 'P2M2'

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
        return cls.delete(request, '/api/user', email)
