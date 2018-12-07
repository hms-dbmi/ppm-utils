from django.conf import settings

from ppmutils.ppm import PPM

import logging
logger = logging.getLogger(__name__)


class Fileservice(PPM.Service):

    # Set the service name
    service = 'Fileservice'

    @classmethod
    def headers(cls, request):

        # Check settings
        prefix = getattr(settings, 'FILESERVICE_AUTH_HEADER_PREFIX', 'Token')

        # Get token
        if not hasattr(settings, 'FILESERVICE_SERVICE_TOKEN') or not hasattr(settings, 'FILESERVICE_TOKEN'):
            raise ValueError('FILESERVICE_SERVICE_TOKEN or FILESERVICE_TOKEN not defined in settings')

        token = getattr(settings, 'FILESERVICE_SERVICE_TOKEN', getattr(settings, 'FILESERVICE_TOKEN'))

        # Use the PPM fileservice token.
        return {
            'Authorization': '{} {}'.format(prefix, token),
            'Content-Type': 'application/json'
        }

    @classmethod
    def check_groups(cls, request, admins):

        # Get current groups.
        groups = cls.get(request, 'groups')
        if groups is None:
            logger.error('Getting groups failed')
            return False

        # Check for the required group.
        for group in groups:
            if cls.group_name('uploaders') == group['name']:
                return True

        # Group was not found, create it.
        data = {
            'name': settings.FILESERVICE_GROUP,
            'users': [{'email': email} for email in admins],
        }

        # Make the request.
        response = cls.post(request, 'groups', data)
        if response is None:
            logger.error('Failed to create groups: {}'.format(response.content))
            return False

        # Get the upload group ID.
        upload_group_id = [group['id'] for group in response if group['name'] == cls.group_name('UPLOADERS')][0]

        # Create the request to add the bucket to the upload group.
        bucket_data = {
            'buckets': [
                {'name': settings.FILESERVICE_AWS_BUCKET}
            ]
        }

        # Make the request.
        response = cls.put(request, '/groups/{}/'.format(upload_group_id), bucket_data)

        return response

    @classmethod
    def create_file(cls, request, filename, metadata, tags=[]):

        # Ensure groups exist.
        if not cls.check_groups(request):
            logger.error('Groups do not exist or failed to create')
            return None

        # Build the request.
        data = {
            'permissions': [
                settings.FILESERVICE_GROUP
            ],
            'metadata': metadata,
            'filename': filename,
            'tags': tags,
        }

        # Make the request.
        file = cls.post(request, '/filemaster/api/file/', data)

        # Get the UUID.
        uuid = file['uuid']

        # Form the request for the file link
        params = {
            'cloud': 'aws',
            'bucket': settings.FILESERVICE_AWS_BUCKET,
            'expires': 100
        }

        # Make the request for an s3 presigned post.
        response = cls.get(request, '/filemaster/api/file/{}/post/'.format(uuid), params)

        return uuid, response

    @classmethod
    def uploaded_file(cls, request, uuid, location_id):

        # Build the request.
        params = {
            'location': location_id
        }

        # Make the request.
        response = cls.get(request, '/filemaster/api/file/{}/uploadcomplete/'.format(uuid), params)

        return response is not None

    @classmethod
    def download_file(cls, request, uuid):

        # Prepare the request.
        response = cls.get(request, '/filemaster/api/file/{}/download/'.format(uuid))

        return response['url']

    @classmethod
    def group_name(cls, permission):

        # Check settings
        if hasattr(settings, 'FILESERVICE_GROUP'):
            return '{}__{}'.format(settings.FILESERVICE_GROUP, permission.upper())

        raise ValueError('FILESERVICE_GROUP not defined in settings')

