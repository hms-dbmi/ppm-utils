from ppmutils.ppm import PPM
from ppmutils.fhir import FHIR

import logging

logger = logging.getLogger(__name__)


class Auth(object):

    ITEM = "ppm"
    ADMIN = "admin"
    VIEW = "view"
    PERMISSIONS = [ADMIN, VIEW]
    METHOD_PERMISSIONS = {
        "HEAD": [ADMIN, VIEW],
        "OPTION": [ADMIN, VIEW],
        "GET": [ADMIN, VIEW],
        "POST": [ADMIN],
        "PATCH": [ADMIN],
        "PUT": [ADMIN],
        "DELETE": [ADMIN],
    }

    @classmethod
    def get_permission(cls, permissions, method=None, study=None):
        """
        Inspects the set of permissions and returns the permission
        valid for the request. If a study is passed, this method
        returns True if permissions are on the specific study or PPM.
        If method is passed, the permissioned is checked for that
        operation.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param method: The requested method to check permissions for
        :type method: str
        :param study: A specific study, defaults to None
        :type study: str, optional
        :returns: Whether the request has permissions or not
        :rtype: bool
        """

        # Map permissions
        map = {a["item"].lower(): a["permission"].lower() for a in permissions}

        # Set placeholders for item and permission. We want to return the
        # upper-most item and permission pairing possible.
        _item = _permission = None

        # Check study, if passed
        if study:

            # Set the item string
            item = f"{cls.ITEM}.{PPM.Study.get(study).value}"

            # Check method if necessary
            if method:
                if map.get(item) in cls.METHOD_PERMISSIONS[method]:
                    _item = item
                    _permission = map[item]
            elif map.get(item) in cls.PERMISSIONS:
                _item = item
                _permission = map[item]

        # First check permission on PPM

        # If method passed, check permission for method
        if method:
            if map.get(cls.ITEM) in cls.METHOD_PERMISSIONS[method]:
                _item = cls.ITEM
                _permission = map[cls.ITEM]

        # If no method, check for any permission
        elif map.get(cls.ITEM) in cls.PERMISSIONS:
            _item = cls.ITEM
            _permission = map[cls.ITEM]

        return _item, _permission

    @classmethod
    def has_permission(cls, permissions, method=None, study=None):
        """
        Inspects the set of permissions and returns the item
        and permission that are valid for the request. This
        returns the first found permission.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param method: The requested method to check permissions for
        :type method: str
        :param study: A specific study, defaults to None
        :type study: str, optional
        :returns: A tuple of item and permission
        :rtype: (str, str)
        """

        # Get permission
        item, permission = Auth.get_permission(permissions, method, study)

        return item is not None and permission is not None

    @classmethod
    def has_ppm_permission(cls, permissions, method=None):
        """
        Inspects the set of permissions and returns whether this
        user has absolute permission over all of PPM for the given
        operation.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param method: The requested method to check permissions for
        :type method: str
        :returns: Whether the user has the permissions or not
        :rtype: bool
        """

        # Get permission
        item, permission = Auth.get_permission(permissions, method)

        return item is not None and permission is not None

    @classmethod
    def has_study_permission(cls, permissions, study, method=None):
        """
        Inspects the set of permissions and returns whether this
        user has needed permissions on the particular PPM study
        for the given operation.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param study: A specific study
        :type study: str
        :param method: The requested method to check permissions for
        :type method: str, default None
        :returns: Whether the user has the permissions or not
        :rtype: bool
        """

        # Get permission
        item, permission = Auth.get_permission(permissions, method=method, study=study)

        return item is not None and permission is not None

    @classmethod
    def has_participant_permission(cls, permissions, participant, method=None, studies=None):
        """
        Inspects the set of permissions and returns whether this
        user has needed permissions on the particular PPM participant.
        All of the participant's studies are pulled and the requesting user is
        expected to have at least one valid permission on a study to pass.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param participant: A specific participant (email or PPM ID)
        :type participant: str
        :param method: The requested method to check permissions for
        :type method: str
        :param patient: The participant's studies, if already fetched
        :type patient: list
        :returns: Whether the user has the permissions or not
        :rtype: bool
        """
        if not studies:
            # Get participant details
            patient, studies = FHIR.query_ppm_participant_details(participant)

        # Check for study permissions on at least one
        for study in studies:

            # Run the check
            item, permission = Auth.get_permission(permissions, method, study)
            if item is not None and permission is not None:
                return True

        return False

    @classmethod
    def has_participants_permission(cls, permissions, participant_ids, method=None, participants=None):
        """
        Inspects the set of permissions and returns whether this
        user has needed permissions on the particular PPM participant.
        All of the participant's studies are pulled and the requesting user is
        expected to have at least one valid permission on a study to pass.

        :param permissions: A list of permissions from DBMI-AuthZ
        :type permissions: list
        :param participant_ids: A list of participant PPM IDs
        :type participant_ids: list
        :param method: The requested method to check permissions for
        :type method: str
        :param participants: The participant details list ([(patient, studies)]), if already fetched
        :type participants: [(dict, list)]
        :returns: Whether the user has the permissions or not
        :rtype: bool
        """
        # Get participant details
        if not participants:
            participants = FHIR.query_ppm_participants_details(participant_ids)

        # Iterate each participant
        for participant in participants:

            # Ensure we have at least a permission on a study
            studies = participant[1]
            for study in studies:

                # Run the check
                item, permission = Auth.get_permission(permissions, method, study)
                if item is not None and permission is not None:
                    break
            else:
                # Loop finished without breaking, did not have permissions on
                # at least one study
                break
        else:

            # If we are here, one permission exists on at least one study for
            # every participant in the list!
            return True

        # Participant loop was not broken early, a permission failed
        return False

    @classmethod
    def has_owner_permission(cls, email, participant, method=None, patient=None):
        """
        Inspects the requesting user's details and confirms they are
        making a request on their own data. This check if performed
        by comparing their JWT's verified email address to the stored
        email address for the Patient resource with ID matching
        the PPM/FHIR ID of the target of the request.

        :param email: The verified email address of the requesting user
        :type email: str
        :param participants: The PPM ID of the participant being requested
        :type participants: str
        :param method: The requested method to check permissions for
        :type method: str
        :param patient: The Patient object, if already fetched
        :type patient: dict
        :returns: Whether the user has the permissions or not
        :rtype: bool
        """
        # Get participant details
        if not patient:
            patient, studies = FHIR.query_ppm_participant_details(participant)

        # Compare details
        if email.lower() == patient.get("email").lower() and participant == patient.get("ppm_id"):

            # Ensure method is not DELETE
            return method is None or method != "DELETE"

        return False
