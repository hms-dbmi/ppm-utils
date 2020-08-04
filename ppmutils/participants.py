from ppmutils.ppm import PPM
from ppmutils.settings import ppm_settings

# Get the app logger
import logging

logger = logging.getLogger(ppm_settings.LOGGER_NAME)


class Participants(PPM.Service):

    service = "participants"
    proxied = True

    @classmethod
    def get_participants(cls, request, study=None, enrollments=None, fhir=None):
        """
        Returns a list of all participants
        """
        # Build query
        query = {}
        if study:
            query["studies"] = study

        if enrollments:
            query["enrollments"] = ",".join(enrollments)

        if fhir is not None:
            query["fhir"] = True

        # Make the request
        return cls.get(request=request, path=f"/", data=query)

    @classmethod
    def get_participant(cls, request, patient_ref, fhir=None):
        """
        Gets a single participant for the passed ID
        """
        query = {}
        if fhir is not None:
            query["fhir"] = True

        # Make the request
        return cls.get(request=request, path=f"/{patient_ref}/", data=query)

    @classmethod
    def create_participant(cls, request, form):
        """
        Deletes the participant and their record
        """
        # Make the request
        return cls.post(request=request, path=f"/", data=form)

    @classmethod
    def update_participant(cls, request, patient_ref, form):
        """
        Performs an update operation on the participant
        """
        # Make the request
        return cls.post(request=request, path=f"/{patient_ref}", data=form)
