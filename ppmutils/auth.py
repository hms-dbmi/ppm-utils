from ppmutils.ppm import PPM

import logging

logger = logging.getLogger(__name__)


class Auth(object):

    ITEM = "ppm"
    ADMIN = "admin"
    VIEW = "view"
    PERMISSIONS = {
        "HEAD": [ADMIN, VIEW],
        "OPTION": [ADMIN, VIEW],
        "GET": [ADMIN, VIEW],
        "POST": [ADMIN],
        "PATCH": [ADMIN],
        "PUT": [ADMIN],
        "DELETE": [ADMIN],
    }

    @classmethod
    def get_permission(cls, method, permissions, study=None):
        """
        Inspects the set of permissions and returns the permission
        valid for the request. If a study is passed, this method
        returns True if permissions are on the specific study or PPM.

        :param method: The requested method to check permissions for
        :type method: str
        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param study: A specific study, defaults to None
        :type study: str, optional
        :returns: Whether the request has permissions or not
        :rtype: bool
        """

        # Map permissions
        map = {a["item"].lower(): a["permission"].lower() for a in permissions}

        # Check for site level permissions first
        if map.get(cls.ITEM) in cls.PERMISSIONS[method]:
            return cls.ITEM, map[cls.ITEM]

        # Check study, if passed
        if study:

            # Set the item string
            item = f"{cls.ITEM}.{PPM.Study.get(study).value}"
            if map.get(item) in cls.PERMISSIONS[method]:
                return item, map[item]

        return None, None

    @classmethod
    def has_permission(cls, method, permissions, study=None):
        """
        Inspects the set of permissions and returns the item
        and permission that are valid for the request. This
        returns the first found permission.

        :param method: The requested method to check permissions for
        :type method: str
        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param study: A specific study, defaults to None
        :type study: str, optional
        :returns: A tuple of item and permission
        :rtype: (str, str)
        """

        # Get permission
        item, permission = Auth.get_permission(method, permissions, study)

        return item is not None and permission is not None
