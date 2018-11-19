from ppmutils.ppm import PPM

import logging
logger = logging.getLogger(__name__)


class P2M2(PPM.Service):

    service = 'P2M2'

    @classmethod
    def get_user(cls, request, email):
        return cls.post(request, 'user', {'email': email})

    @classmethod
    def get_participant(cls, request, email):
        return cls.post(request, 'participant', {'email': email})

    @classmethod
    def get_participants(cls, request, emails):
        return cls.post(request, 'participants', {'emails': emails})

    @classmethod
    def get_application(cls, request, email):
        return cls.post(request, 'application', {'email': email})

    @classmethod
    def get_applications(cls, request, emails):
        return cls.post(request, 'applications', {'emails': emails})

    @classmethod
    def get_authorization(cls, request, email):
        return cls.post(request, 'authorization', {'email': email})

    @classmethod
    def get_authorizations(cls, request, emails):
        return cls.post(request, 'authorizations', {'emails': emails})

    @classmethod
    def update_participant(cls, request, email, project):
        return cls.patch(request, email, 'participant', {'project': project})

    @classmethod
    def delete_user(cls, request, email):
        return cls.delete(request, 'user', email)
