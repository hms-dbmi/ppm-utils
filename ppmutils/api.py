from ppmutils.ppm import PPM
from ppmutils.settings import ppm_settings

# Get the app logger
import logging

logger = logging.getLogger(ppm_settings.LOGGER_NAME)


class API(PPM.Service):

    service = "ppm"
    proxied = True

    @classmethod
    def studies(cls, as_choices=False):
        """
        Queries the API for the dashboard for the given study
        :param study: The study code
        :param as_choices: Return the items as a tuple of tuples
        :return: dict
        """
        # Make the request
        items = cls.get(request=None, path=f"/study/")

        # Return dashboard
        return items if not as_choices else ((i["code"], i["title"]) for i in items)

    @classmethod
    def dashboard(cls, study=None):
        """
        Queries the API for the dashboard for the given study
        :param study: The study code
        :return: dict
        """
        # Make the request
        if not study:
            items = cls.get(request=None, path=f"/step/")
        else:
            # Get the study proper
            study = PPM.Study.get(study)

            items = cls.get(request=None, path=f"/study/{study.value}/")["dashboard"]

        return items

    @classmethod
    def enrollments(cls, as_choices=False):
        """
        Queries the API for the dashboard for the given study
        :param as_choices: Return the items as a tuple of tuples
        :return: dict
        """
        # Make the request
        items = cls.get(request=None, path=f"/enrollment/")

        # Return dashboard
        return items if not as_choices else ((i["code"], i["title"]) for i in items)

    @classmethod
    def samples(cls, study=None, as_choices=False):
        """
        Queries the API for PPM samples
        :param study: Filter samples for the given study
        :param as_choices: Return the items as a tuple of tuples
        :return: dict
        """
        # Make the request
        if not study:
            items = cls.get(request=None, path=f"/sample/")
        else:
            # Get the study proper
            study = PPM.Study.get(study)

            items = cls.get(request=None, path=f"/study/{study.value}/")["samples"]

        # Return dashboard
        return items if not as_choices else ((i["code"], i["title"]) for i in items)
