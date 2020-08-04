from __future__ import absolute_import, unicode_literals

import os
import warnings
import logging

from django.conf import settings
from django.test.signals import setting_changed

from ppmutils import environment as env

# Always import this module as follows:
# from ppm_client import settings [as ppm_settings]

# Don't import directly CONFIG or PANELs, or you will miss changes performed
# with override_settings in tests.

# Set service URLs based on environment
PPM_ENVIRONMENTS = {
    "prod": {
        "API_URL": "https://api.ppm.aws.dbmi.hms.harvard.edu",
        "ADMIN_URL": "https://p2m2a.dbmi.hms.harvard.edu",
        "QUESTIONNAIRE_URL": "https://questionnaire.ppm.dbmi.hms.harvard.edu/questionnaire",
        "DATA_URL": "https://data.ppm.dbmi.hms.harvard.edu",
        "FHIR_URL": "https://fhir.ppm.aws.dbmi.hms.harvard.edu",
        "FILESERVICE_URL": "https://files.ppm.aws.dbmi.hms.harvard.edu",
        "DASHBOARD_URL": {
            "neer": "https://neer.ppm.aws.dbmi.hms.harvard.edu",
            "autism": "https://autism.ppm.aws.dbmi.hms.harvard.edu",
            "example": "https://example.ppm.aws.dbmi.hms.harvard.edu",
            "rant": "https://rant.ppm.aws.dbmi.hms.harvard.edu",
        },
    },
    "dev": {
        "API_URL": "https://api.ppm.aws.dbmi-dev.hms.harvard.edu",
        "ADMIN_URL": "https://p2m2a.aws.dbmi-dev.hms.harvard.edu",
        "QUESTIONNAIRE_URL": "https://questionnaire.ppm.aws.dbmi-dev.hms.harvard.edu/questionnaire",
        "DATA_URL": "https://data.ppm.aws.dbmi-dev.hms.harvard.edu",
        "FHIR_URL": "https://fhir.ppm.aws.dbmi-dev.hms.harvard.edu",
        "FILESERVICE_URL": "https://files.ppm.aws.dbmi-dev.hms.harvard.edu",
        "DASHBOARD_URL": {
            "neer": "https://neer.ppm.aws.dbmi-dev.hms.harvard.edu",
            "autism": "https://autism.ppm.aws.dbmi-dev.hms.harvard.edu",
            "example": "https://example.ppm.aws.dbmi-dev.hms.harvard.edu",
            "rant": "https://rant.ppm.aws.dbmi-dev.hms.harvard.edu",
        },
    },
    "local": {
        "API_URL": "https://api.ppm.aws.dbmi-loc.hms.harvard.edu",
        "ADMIN_URL": "https://p2m2a.aws.dbmi-loc.hms.harvard.edu",
        "QUESTIONNAIRE_URL": "https://questionnaire.ppm.aws.dbmi-loc.hms.harvard.edu/questionnaire",
        "DATA_URL": "https://data.ppm.aws.dbmi-loc.hms.harvard.edu",
        "FHIR_URL": "https://fhir.ppm.aws.dbmi-loc.hms.harvard.edu",
        "FILESERVICE_URL": "https://files.ppm.aws.dbmi-loc.hms.harvard.edu",
        "DASHBOARD_URL": {
            "neer": "https://neer.ppm.aws.dbmi-loc.hms.harvard.edu",
            "autism": "https://autism.ppm.aws.dbmi-loc.hms.harvard.edu",
            "example": "https://example.ppm.aws.dbmi-loc.hms.harvard.edu",
            "rant": "https://rant.ppm.aws.dbmi-loc.hms.harvard.edu",
        },
    },
}

CONFIG_DEFAULTS = {
    # The identifier for this service and/or project
    "STUDY": None,
    # Client options, assume production environment
    "ENVIRONMENT": "prod",
    # Set prod URLs
    "API_URL": None,
    "ADMIN_URL": None,
    "QUESTIONNAIRE_URL": None,
    "DATA_URL": None,
    "FHIR_URL": None,
    "FILESERVICE_URL": None,
    # Optionally disable logging
    "LOGGER_NAME": "ppmutils",
    "ENABLE_LOGGING": True,
    "LOG_LEVEL": logging.WARNING,
    # Configure email settings
    "EMAIL_ENABLED": False,
    "EMAIL_DEFAULT_FROM": "ppm-no-reply@dbmi.hms.harvard.edu",
    "EMAIL_TEST_ACCOUNTS": [r"tester[\d]?@peoplepoweredmedicine.org:admin@peoplepoweredmedicine.org"],
    "EMAIL_SIGNATURE": {
        "name": "Jane Smith",
        "email": "jane_smith@peoplepoweredmedicine.org",
        "title": "Manager, People-Powered Medicine",
        "phone": "617-555-5555",
    },
}

# List of settings that cannot be defaulted and must be user-defined
REQUIRED_SETTINGS = ("FHIR_URL",)

# List of settings that have been removed
REMOVED_SETTINGS = ()

# List of service URLs
SERVICE_URLS = (
    "API_URL",
    "FHIR_URL",
    "ADMIN_URL",
    "QUESTIONNAIRE_URL",
    "DATA_URL",
    "FILESERVICE_URL",
)

# List of needed email settings if enabled
EMAIL_SETTINGS = (
    "EMAIL_BACKEND",
    "EMAIL_HOST",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_PORT",
    "EMAIL_USE_SSL",
)


class PPMSettings(object):
    """
    A settings object, that allows PPMUtils Client settings to be accessed as properties.
    For example:
        from ppmutils.settings import ppm_settings
        print(ppm_settings.STUDY)
    Any setting with string import paths will be automatically resolved
    and return the class, rather than the string literal.
    """

    def __init__(self, defaults=None):
        self.defaults = defaults or CONFIG_DEFAULTS
        self._cached_attrs = set()

    @property
    def user_settings(self):

        # Check to see if user configs have been loaded or not
        if not hasattr(self, "_user_settings"):

            try:
                # Load user-specified configurations
                user_settings = getattr(settings, "PPM_CONFIG", {})

                # Update the client config with pre-defined environment URLs, etc
                if user_settings.get("ENVIRONMENT") in PPM_ENVIRONMENTS:
                    env_settings = PPM_ENVIRONMENTS[user_settings.get("ENVIRONMENT")]
                    user_settings.update({k: v for k, v in env_settings.items() if k not in user_settings})

                else:
                    # Check for them in environment
                    for key in PPM_ENVIRONMENTS["prod"].keys():
                        if os.environ.get("PPM_{}".format(key.upper())):
                            user_settings[key] = env.get_str("PPM_{}".format(key.upper()))

                # Check them
                self._user_settings = self.__check_user_settings(user_settings)

            except Exception as e:
                raise SystemError("PPMUtils settings are invalid: {}".format(e))

        return self._user_settings

    def dashboard_url(self, study):
        """
        Returns the defined dashboard for the passed study
        :param study: The study we want the dashboard URL for
        :type study: str
        :return: The dashboard URL
        :rtype: str
        """
        try:
            # Get environments
            return PPM_ENVIRONMENTS[self.ENVIRONMENT]["DASHBOARD_URL"][study]

        except (ValueError, IndexError):
            warnings.warn(f'No defined PPM dashboard URL for "{self.ENVIRONMENT}/{study}"')

        return None

    def __getattr__(self, attr):

        # Any attribute must be in either required settings or defaults
        if attr not in REQUIRED_SETTINGS and attr not in self.defaults:
            raise AttributeError("Invalid PPM setting: '%s'" % attr)

        try:
            # Check if present in user settings
            val = self.user_settings[attr]
        except KeyError:

            # Fall back to defaults
            val = self.defaults[attr]

        # Cache the result
        self._cached_attrs.add(attr)
        setattr(self, attr, val)

        return val

    def __check_user_settings(self, user_settings):
        SETTINGS_DOC = "https://github.com/hms-dbmi/ppmutils"

        for setting in REMOVED_SETTINGS:
            if setting in user_settings:
                raise RuntimeError(
                    "The '%s' setting has been removed. Please refer to '%s' for available settings."
                    % (setting, SETTINGS_DOC)
                )

        # Ensure environment is set and if not prod or dev, ensure service URLs are provided
        if (
            "ENVIRONMENT" in user_settings
            and user_settings["ENVIRONMENT"].lower() != "prod"
            and user_settings["ENVIRONMENT"].lower() != "dev"
        ):
            warnings.warn("ENVIRONMENT is not set to production, this should be a test environment", ResourceWarning)

            # Check URLs
            self._url_settings(user_settings)

        # Check email settings
        self._email_settings(user_settings)

        return user_settings

    def _url_settings(self, user_settings):
        """
        Checks the host settings for properly configured URLs and adds the correct
        configurations if needed.
        """
        # Iterate service URLs and ensure they're defined, error out on required ones
        missing_urls = []
        for url in SERVICE_URLS:

            # Check if not added
            if url not in user_settings:

                # Check environment
                if os.environ.get(f"PPM_{url}"):
                    user_settings[url] = os.environ.get(f"PPM_{url}")
                elif url in REQUIRED_SETTINGS:
                    missing_urls.append(url)
                else:
                    warnings.warn(f'PPM URLs: Env "{url}"/"PPM_{url}" is missing but not required')

        # Error out if needed
        if missing_urls:
            raise AttributeError("{} configuration(s) must be set".format(missing_urls))

    def _email_settings(self, user_settings):
        """
        Checks the host settings for properly configured email backends and adds the correct
        configurations if needed.
        """
        if user_settings.get("EMAIL_ENABLED"):

            # Check and remap remaining settings
            missing_settings = []
            for email_setting in EMAIL_SETTINGS:

                # Ensure settings has these defined
                if getattr(settings, email_setting) is None:
                    missing_settings.append(email_setting)

            if missing_settings:
                raise AttributeError("PPM Email: Required email settings are missing: {}".format(missing_settings))

    def reload(self):
        for attr in self._cached_attrs:
            delattr(self, attr)
        self._cached_attrs.clear()
        if hasattr(self, "_user_settings"):
            delattr(self, "_user_settings")

    def __dir__(self):

        # Return defaults and user configs patched over
        attrs = dict()
        attrs.update(self.defaults)
        attrs.update(self.user_settings)

        return attrs.keys()

    def get_logger(self):
        """
        Returns the logger and manages whether logs propogate or not depending on user configs
        :return: logger
        """
        logger = logging.getLogger(__name__)

        # Check if disabled
        if not self.ENABLE_LOGGING:
            logger.propagate = False

        return logger


# Create the instance by which the settings should be accessed
ppm_settings = PPMSettings(CONFIG_DEFAULTS)

# Configure logging
logger = logging.getLogger(ppm_settings.LOGGER_NAME)
logger.disabled = not ppm_settings.ENABLE_LOGGING
logger.setLevel(ppm_settings.LOG_LEVEL)


def reload_ppm_settings(*args, **kwargs):
    setting = kwargs["setting"]
    if setting == "PPM_CONFIG":
        ppm_settings.reload()


setting_changed.connect(reload_ppm_settings)
