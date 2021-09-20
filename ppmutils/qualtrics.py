from datetime import datetime
from dateutil.parser import parse
import hashlib
import json
import re
import sys
import collections
from furl import furl
import requests
from fhirclient.models.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhirclient.models.questionnaire import Questionnaire

from ppmutils.fhir import FHIR
from ppmutils.ppm import PPM

import logging

logger = logging.getLogger(__name__)


class Qualtrics:
    class ConversionError(Exception):
        pass

    @classmethod
    def is_survey_export(cls, survey):
        """
        Inspects a survey export object and confirms that's what it is.
        Qualtrics surveys can be described by three separate formats:
        survey object from API, survey definition from API, and survey
        export from GUI.

        :param survey: The survey object in questions
        :type survey: dict
        :returns: Whether the passed survey object is an export or not
        :rtype: boolean
        """
        return survey.get("SurveyElements") is not None

    @classmethod
    def is_survey_definition(cls, survey):
        """
        Inspects a survey definition object and confirms that's what it is.
        Qualtrics surveys can be described by three separate formats:
        survey object from API, survey definition from API, and survey
        export from GUI.

        :param survey: The survey object in questions
        :type survey: dict
        :returns: Whether the passed survey object is an definition or not
        :rtype: boolean
        """
        return survey.get("SurveyOptions") is not None and survey.get("Questions") is not None

    @classmethod
    def is_survey_object(cls, survey):
        """
        Inspects a survey object and confirms that's what it is.
        Qualtrics surveys can be described by three separate formats:
        survey object from API, survey definition from API, and survey
        export from GUI.

        :param survey: The survey object in questions
        :type survey: dict
        :returns: Whether the passed survey object is an object or not
        :rtype: boolean
        """
        return survey.get("name") is not None and survey.get("questions") is not None

    @classmethod
    def get_survey_response_metadata(cls, response):
        """
        Given a Qualtrics survey response object from the API, this returns
        a dictionary of metadata for the response relating to the study
        and the participant who created the response.

        :param response: A Qualtrics API response object
        :type response: dict
        :return: A dictionary of metadata
        :rtype: dict
        """
        # Set basic details
        metadata = {"response_id": response.get("responseId")}

        # Get values dictionary
        values = response.get("values")
        if values:

            # Set data
            metadata.update(
                {
                    "study": values.get("ppm_study", ""),
                    "ppm_id": values.get("ppm_id", values.get("externalDataReference", "")),
                    "survey_id": values.get("SurveyID", ""),
                }
            )

        return metadata

    @classmethod
    def questionnaire(cls, survey, survey_id, questionnaire_id=None):
        """
        Accepts a Qualtrics survey definition (QSF) and creates a FHIR
        Questionnaire resource from it. Does not support all of Qualtrics
        functionality and will fail where question-types or other unsupported
        features are encountered.add()

        :param survey: The Qualtrics survey object
        :type survey: dict
        :param survey_id: The ID of the survey in Qualtrics (may differ from ID on QSF)
        :type survey_id: str
        :param questionnaire_id: The ID to assign to the Questionnaire, defaults to None
        :type questionnaire_id: str, optional
        """
        try:
            # Extract the items
            items = [i for i in cls.questionnaire_item_generator(survey_id, survey)]

            # Hash the questions and flow of the survey to track version of the survey
            version = hashlib.md5(json.dumps(items).encode()).hexdigest()

            # Build the resource
            data = {
                "resourceType": "Questionnaire",
                "meta": {"lastUpdated": datetime.now().isoformat()},
                "identifier": [
                    {
                        "system": FHIR.qualtrics_survey_identifier_system,
                        "value": survey_id,
                    },
                    {
                        "system": FHIR.qualtrics_survey_version_identifier_system,
                        "value": version,
                    },
                    {
                        "system": FHIR.qualtrics_survey_questionnaire_identifier_system,
                        "value": questionnaire_id,
                    },
                ],
                "version": version,
                "name": survey_id,
                "title": survey["SurveyEntry"]["SurveyName"],
                "status": "active" if survey["SurveyEntry"]["SurveyStatus"] == "Active" else "draft",
                "approvalDate": parse(survey["SurveyEntry"]["SurveyCreationDate"]).isoformat(),
                "date": parse(survey["SurveyEntry"]["LastModified"]).isoformat(),
                "extension": [
                    {
                        "url": "https://p2m2.dbmi.hms.harvard.edu/fhir/StructureDefinition/qualtrics-survey",
                        "valueString": survey_id,
                    }
                ],
                "item": items,
            }

            # If survey start date, add it
            if (
                survey["SurveyEntry"].get("SurveyStartDate")
                and survey["SurveyEntry"]["SurveyStartDate"] != "0000-00-00 00:00:00"
            ):

                data["effectivePeriod"] = {"start": parse(survey["SurveyEntry"]["SurveyStartDate"]).isoformat()}

            # If expiration, add it
            if (
                survey["SurveyEntry"].get("SurveyExpirationDate")
                and survey["SurveyEntry"]["SurveyStartDate"] != "0000-00-00 00:00:00"
            ):

                data["effectivePeriod"]["end"] = parse(survey["SurveyEntry"]["SurveyExpirationDate"]).isoformat()

                # If after expiration, set status
                if parse(survey["SurveyEntry"]["SurveyExpirationDate"]) < datetime.now():
                    data["status"] = "retired"

            return data

        except Exception as e:
            logger.debug(f"PPM/Qualtrics: Error {e}", exc_info=True)
            raise Qualtrics.ConversionError

    @classmethod
    def questionnaire_item_generator(cls, survey_id, survey):
        """
        Returns a generator of QuestionnaireItem resources
        to be added to the Questionnaire. This will determine
        the type of QuestionnaireItem needed and yield it
        accordingly for inclusion into the Questionnaire.

        :param survey_id: The Qualtrics survey identifier
        :type survey_id: str
        :param survey: The Qualtrics survey object
        :type survey: dict
        :raises Exception: Raises exception if block is an unhandled type
        :return: The FHIR QuestionnaireItem generator
        :rtype: generator
        """
        # Flow sets order of blocks, blocks set order of questions
        flows = [
            f["ID"]
            for f in next(e["Payload"]["Flow"] for e in survey["SurveyElements"] if e.get("Element") == "FL")
            if f["Type"] in ["Block", "Standard"]
        ]
        # Check which type of block spec (list or dict)
        _blocks = next(e["Payload"] for e in survey["SurveyElements"] if e.get("Element") == "BL")
        if type(_blocks) is list:
            blocks = {
                f: next(b for b in _blocks if b["Type"] in ["Default", "Standard"] and b["ID"] == f) for f in flows
            }
        elif type(_blocks) is dict:
            blocks = {
                f: next(b for b in _blocks.values() if b["Type"] in ["Default", "Standard"] and b["ID"] == f)
                for f in flows
            }
        else:
            logger.error(f"PPM/Qualtrics: Invalid Qualtrics block spec")

        questions = {f: [e["QuestionID"] for e in blocks[f]["BlockElements"] if e["Type"] == "Question"] for f in flows}

        # Walk through elements
        for block_id, block in blocks.items():

            # Check if we need this grouped
            if block.get("Options", {}).get("Looping", False):

                # Build the group
                group = cls.questionnaire_group(survey_id, survey, block_id, block)

                yield group

            else:
                # Yield each question individually
                for question_id in questions[block_id]:

                    # Look up the question
                    question = next(
                        e["Payload"] for e in survey["SurveyElements"] if e["PrimaryAttribute"] == question_id
                    )

                    # Create it
                    item = cls.questionnaire_item(survey_id, survey, question_id, question)

                    yield item

    @classmethod
    def questionnaire_group(cls, survey_id, survey, block_id, block):
        """
        Returns a FHIR resource for a QuestionnaireItem parsed from
        a block of Qualtrics survey's questions. This should be used
        when a set of questions should be grouped for the purpose of
        conditional showing, repeating/looping.

        :param survey_id: The Qualtrics survey identifier
        :type survey_id: str
        :param survey: The Qualtrics survey object
        :type survey: dict
        :param block_id: The Qualtrics survey block identifier
        :type block_id: str
        :param block: The Qualtrics survey block object
        :type block: dict
        :raises Exception: Raises exception if block is an unhandled type
        :return: The FHIR QuestionnaireItem resource
        :rtype: dict
        """
        try:
            # Set root link ID
            link_id = f"group-{block_id.replace('BL_', '')}"

            # Get all questions in this block
            question_ids = [b["QuestionID"] for b in block["BlockElements"]]

            # Prepare group item
            item = {
                "linkId": link_id,
                "type": "group",
                "repeats": True if block.get("Options", {}).get("Looping", False) else False,
                "item": [
                    cls.questionnaire_item(
                        survey_id,
                        survey,
                        question_id,
                        next(e["Payload"] for e in survey["SurveyElements"] if e["PrimaryAttribute"] == question_id),
                    )
                    for question_id in question_ids
                ],
            }

            return item

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Error processing block {block_id}: {e}",
                exc_info=True,
                extra={
                    "survey_id": survey_id,
                    "block_id": block_id,
                    "block": block,
                },
            )
            raise e

    @classmethod
    def _qid_to_linkid(cls, qid):
        """
        This is a utility method to convert a Qualtrics QID question ID
        to a FHIR Questionnaire/QuestionnaireResponse Link ID.

        :param qid: The Qualtrics QID to convert
        :type qid: str
        :return: The FHIR Link ID
        :rtype: str
        """
        return f'question-{qid.replace("QID", "").replace("S", "-")}'

    @classmethod
    def questionnaire_item(cls, survey_id, survey, question_id, question):
        """
        Returns a FHIR resource for a QuestionnaireItem parsed from
        the Qualtrics survey's question

        :param survey_id: The Qualtrics survey identifier
        :type survey_id: str
        :param survey: The Qualtrics survey object
        :type survey: dict
        :param qid: The Qualtrics survey question identifier
        :type qid: str
        :param question: The Qualtrics survey question object
        :type question: dict
        :raises Exception: Raises exception if question is an unhandled type
        :return: The FHIR QuestionnaireItem resource
        :rtype: dict
        """
        # Set root link ID
        link_id = cls._qid_to_linkid(question_id)

        # Strip text of HTML and other characters
        text = re.sub("<[^<]+?>", "", question["QuestionText"]).strip().replace("\n", "").replace("\r", "")

        # Determine if required
        required = question["Validation"].get("Settings", {}).get("ForceResponse", False) == "ON"

        # Get question text
        item = {
            "linkId": link_id,
            "text": text,
            "required": required,
        }

        try:
            # Check for conditional enabling
            if question.get("DisplayLogic", False):

                # Intialize enableWhen item
                enable_whens = []

                # We are only processing BooleanExpressions
                if question["DisplayLogic"]["Type"] != "BooleanExpression":
                    logger.error(
                        f"PPM/Questionnaire: Unhandled DisplayLogic "
                        f"type {survey_id}/{question_id}: {question['DisplayLogic']}"
                    )
                    raise ValueError(f"Failed to process survey {survey['id']}")

                # Iterate conditions for display of this question
                # INFO: Currently only selected choice conditions are supported
                statement = question["DisplayLogic"]["0"]["0"]

                # Get the question ID it depends on
                conditional_qid = statement["QuestionID"]

                # Fetch the value of the answer
                components = furl(statement["LeftOperand"]).path.segments

                # Check type
                if components[0] == "SelectableChoice":

                    # Get answer index and value
                    index = components[1]

                    # Find question
                    conditional_question = next(
                        e for e in survey["SurveyElements"] if e["PrimaryAttribute"] == conditional_qid
                    )

                    # Get answer value
                    conditional_value = next(
                        c["Display"] for i, c in conditional_question["Payload"]["Choices"].items() if i == index
                    )

                    # Add it
                    enable_whens.append(
                        {
                            "question": cls._qid_to_linkid(conditional_qid),
                            "answerString": conditional_value,
                        }
                    )

                else:
                    logger.error(
                        f"PPM/Questionnaire: Unhandled DisplayLogic expression"
                        f"type {survey_id}/{question_id}: {components}"
                    )
                    raise ValueError(f"Failed to process survey {survey['id']}")

                # Add enableWhen's if we've got them
                if enable_whens:
                    item["enableWhen"] = enable_whens

        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Error processing display logic: {e}",
                exc_info=True,
                extra={
                    "survey_id": survey_id,
                    "question_id": question_id,
                },
            )
            raise e

        # Check type
        question_type = question["QuestionType"]
        selector = question["Selector"]
        sub_selector = question.get("SubSelector")

        try:
            # Text (single line)
            if question_type == "TE" and selector == "SL":

                # Set type
                item["type"] = "string"

            # Text (multiple line)
            elif question_type == "TE" and selector == "ESTB":

                # Set type
                item["type"] = "text"

            # Text (multiple line)
            elif question_type == "TE" and selector == "ML":

                # Set type
                item["type"] = "text"

            # Multiple choice (single answer)
            elif question_type == "MC" and selector == "SAVR":

                # Set type
                item["type"] = "choice"

                # Set choices
                item["option"] = [{"valueString": c["Display"]} for k, c in question["Choices"].items()]

            # Multiple choice (multiple answer)
            elif question_type == "MC" and selector == "MAVR":

                # Set type
                item["type"] = "choice"
                item["repeats"] = True

                # Set choices
                item["option"] = [{"valueString": c["Display"]} for k, c in question["Choices"].items()]

            # Matrix (single answer)
            elif question_type == "Matrix" and selector == "Likert" and sub_selector == "SingleAnswer":

                # Add this as a grouped set of multiple choice, single answer questions
                item["type"] = "group"

                # Preselect choices
                choices = [{"valueString": c["Display"]} for k, c in question["Answers"].items()]

                # Set subitems
                item["item"] = [
                    {
                        "linkId": f"{link_id}-{k}",
                        "text": s["Display"],
                        "type": "choice",
                        "option": choices,
                        "required": required,
                    }
                    for k, s in question["Choices"].items()
                ]

            # Matrix (multiple answer)
            elif question_type == "Matrix" and selector == "Likert" and sub_selector == "MultipleAnswer":

                # Add this as a grouped set of multiple choice, single answer questions
                item["type"] = "group"
                item["repeats"] = True

                # Preselect choices
                choices = [{"valueString": c["Display"]} for k, c in question["Answers"].items()]

                # Set subitems
                item["item"] = [
                    {
                        "linkId": f"{link_id}-{k}",
                        "text": s["Display"],
                        "type": "choice",
                        "option": choices,
                        "required": required,
                    }
                    for k, s in question["Choices"].items()
                ]

            # Slider (integer answer)
            elif question_type == "Slider" and selector == "HBAR":

                # Set type
                item["type"] = "integer"

            # Slider (integer answer)
            elif question_type == "Slider" and selector == "HSLIDER":

                # Set type
                item["type"] = "decimal"

            # Hot spot (multiple choice, multiple answer)
            elif question_type == "HotSpot" and selector == "OnOff":

                # Set type
                item["type"] = "choice"
                item["repeats"] = True

                # Set choices
                item["option"] = [{"valueString": c["Display"]} for k, c in question["Choices"].items()]

            # Drill down
            elif question_type == "DD" and selector == "DL":

                # Set type
                item["type"] = "choice"
                item["repeats"] = False

                # Set choices
                item["option"] = [{"valueString": c["Display"]} for k, c in question["Answers"].items()]

            # Descriptive text
            elif question_type == "DB":

                # Set type
                item["type"] = "display"

            # Descriptive graphics
            elif question_type == "GB":

                # Set type
                item["type"] = "display"

            # Multiple, matrix-style questions
            elif question_type == "SBS":

                # Put them in a group
                item["type"] = "group"
                item["text"] = question["QuestionText"]
                item["item"] = []

                # Add this as multiple grouped sets of multiple choice, single answer questions
                for k, additional_question in question["AdditionalQuestions"].items():

                    # Add another display for the subquestion
                    sub_item = {
                        "linkId": f"{link_id}-{k}",
                        "type": "group",
                        "text": additional_question["QuestionText"],
                        "item": [],
                    }

                    # Get choices
                    questions = {k: c["Display"] for k, c in additional_question["Choices"].items()}

                    # Preselect choices
                    answers = [{"valueString": c["Display"]} for k, c in additional_question["Answers"].items()]

                    # Add a question per choice
                    for sub_k, sub_question in questions.items():

                        # Remove prefixes, if set
                        sub_question = re.sub(r"^[\d]{1,4}\.\s", "", sub_question)

                        # Set subitems
                        sub_item["item"].append(
                            {
                                "linkId": f"{link_id}-{k}-{sub_k}",
                                "text": sub_question,
                                "type": "choice",
                                "option": answers,
                                "required": required,
                            }
                        )

                    item["item"].append(sub_item)

            else:
                logger.error(
                    "PPM/Questionnaire: Unhandled survey question type {survey_id}/{question_id}: {question_type}"
                )
                raise ValueError(f"Failed to process survey {survey_id}")
        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Error processing questionnaire item: {e}",
                exc_info=True,
                extra={
                    "survey_id": survey_id,
                    "question_id": question_id,
                    "question": question,
                },
            )
            raise e

        return item

    @classmethod
    def questionnaire_response(
        cls, study, ppm_id, questionnaire_id, survey_id, response_id, survey_definition=None, survey=None, response=None
    ):
        """
        Returns QuestionnaireResponse resource for a survey taken through
        Qualtrics. This method requires that Qualtrics question names are
        matched to the FHIR Questionnaire linkIds. If the response data is not
        available, an empty QuestionnaireResponse is created to be updated
        at a later time.

        :param study: The study for which the questionnaire was given
        :type study: PPM.Study
        :param ppm_id: The PPM ID for the participant who took the survey
        :type ppm_id: str
        :param questionnaire_id: The ID for the related FHIR Questionnaire
        :type questionnaire_id: str
        :param survey_id: The ID of the Qualtrics survey
        :type survey_id: str
        :param response_id: The ID of the Qualtrics survey response
        :type response_id: str
        :param survey_definition: The Qualtrics survey definition object
        :type survey_definition: dict, defaults to None
        :param survey: The Qualtrics survey object
        :type survey: dict, defaults to None
        :param response: The Qualtrics survey response object
        :type response: dict, defaults to None
        :return: The QuestionnaireResponse resource
        :rtype: dict
        """
        # Run checks
        if survey and not Qualtrics.is_survey_object(survey):
            raise ValueError(f"PPM/Qualtrics: survey is not a valid Qualtrics API survey object")

        if survey_definition and not Qualtrics.is_survey_definition(survey_definition):
            raise ValueError(f"PPM/Qualtrics: survey_definition is not a valid Qualtrics API survey definition object")

        # Prepare resource properties
        data = {
            "resourceType": "QuestionnaireResponse",
            "meta": {"lastUpdated": datetime.now().isoformat()},
            "identifier": {
                "system": FHIR.qualtrics_response_identifier_system,
                "value": response_id,
            },
            "questionnaire": {"reference": "Questionnaire/{}".format(questionnaire_id)},
            "subject": {"reference": "ResearchStudy/{}".format(PPM.Study.fhir_id(study))},
            "status": "completed",
            "author": {"reference": f"Patient/{ppm_id}"},
            "source": {"reference": f"Patient/{ppm_id}"},
            "authored": datetime.now().isoformat(),
            "extension": [
                {
                    "url": FHIR.qualtrics_survey_extension_url,
                    "valueString": survey_id,
                }
            ],
        }

        # If response, parse answers
        if response and survey:

            # Build a dictionary describing block and question order
            blocks = {
                f["id"]: [
                    e["questionId"]
                    for e in survey["blocks"][f["id"]].get("elements", [])
                    if e.get("type") == "Question"
                ]
                for f in survey["flow"]
                if f.get("type") == "Block"
            }

            # Build response groups and add it to the questionnair response
            data["item"] = list(cls.questionnaire_response_item_generator(survey_definition, survey, response, blocks))

            # Set dates if specified.
            if response.get("endDate"):
                data["authored"] = response["endDate"]

        return data

    @classmethod
    def questionnaire_response_item_generator(cls, survey_definition, survey, response, blocks):
        """
        Accepts the survey, response objects as well as the list of blocks add their
        respective questions and yields a set of QuestionnareResponseItem
        resources to be set for the QuestionnaireResponse.

        :param survey_definition: The Qualtrics survey definition object
        :type survey_definition: dict, defaults to None
        :param survey: The Qualtrics survey object
        :type survey: object
        :param response: The Qualtrics survey response item
        :type response: object
        :param blocks: The dictionary of blocks comprising the survey
        :type blocks: dict
        :raises Exception: Raises exception if value is an unhandled type
        :returns A generator of QuestionnaireResponseItem resources
        :rtype generator
        """
        question_id = None
        for block_id, question_ids in blocks.items():
            try:
                # Get the block
                block = survey["blocks"][block_id]

                # Set root link ID
                link_id = f"group-{block_id.replace('BL_', '')}"

                # Get all questions in this block
                question_ids = [e["questionId"] for e in block["elements"] if e["type"] == "Question"]

                # Check if repeating
                if survey.get("loopAndMerge").get(block_id, None):

                    # Loop each block and build a set of answers
                    answers = []
                    for loop_index in range(1, sys.maxsize):

                        # Check for values
                        values = {k: v for k, v in response["values"].items() if k.startswith(f"{loop_index}_QID")}
                        if not values:
                            break

                        # Get items
                        items = [
                            cls.questionnaire_response_item(survey, response, key, loop_index) for key in values.keys()
                        ]

                        # Weed out duplicates
                        filtered_items = [i for n, i in enumerate(items) if i not in items[n + 1 :] and i is not None]

                        # Prepare group item
                        answers.append(
                            {
                                "valueInteger": loop_index,
                                "item": filtered_items,
                            }
                        )

                    # Prepare group item
                    if answers:
                        yield {
                            "linkId": link_id,
                            "answer": answers,
                        }

                else:
                    # Iterate questions
                    for question_id in question_ids:

                        # Filter values to those for this block/group
                        pattern = rf"^({question_id})(?![S\d])"
                        values = {k: v for k, v in response["values"].items() if re.match(pattern, k)}
                        if not values:

                            # Check each question
                            if Qualtrics.survey_response_is_required(
                                survey_definition=survey_definition, survey=survey, response=response, key=question_id
                            ):
                                logger.error(
                                    f'PPM/Qualtrics: No value(s) for required "{question_id}"',
                                    extra={
                                        **Qualtrics.get_survey_response_metadata(response),
                                        "block_id": block_id,
                                        "question_id": question_id,
                                    },
                                )

                            # Nothing else to do
                            continue

                        # Get items
                        items = [cls.questionnaire_response_item(survey, response, key) for key in values.keys()]

                        # Weed out duplicates
                        filtered_items = [i for n, i in enumerate(items) if i not in items[n + 1 :] and i is not None]

                        # We don't want to group un-repeated items, so just return them
                        for item in filtered_items:
                            yield item

            except Exception as e:
                logger.exception(
                    f"PPM/Qualtrics: Error processing block/question {block_id}/{question_id}: {e}",
                    exc_info=True,
                    extra={
                        **Qualtrics.get_survey_response_metadata(response),
                        "block_id": block_id,
                        "question_id": question_id,
                    },
                )
                raise e

    @classmethod
    def survey_response_is_required(cls, survey_definition, survey, response, key):
        """
        Returns whether a response to the question is required or not according
        to the Qualtrics survey object. This inspects not only properties of
        the question but also ensures it's enabled via conditional logic. If
        not enabled, will not be returned as required.

        :param survey_definition: The Qualtrics survey definition object
        :type survey_definition: dict, defaults to None
        :param survey: The Qualtrics survey object
        :type survey: object
        :param response: The response object
        :type response: dict
        :param key: The Qualtrics question ID to process
        :type key: str
        :raises Exception: Raises exception if value is an unhandled type
        :return: Whether the question is required or not
        :rtype: boolean
        """
        try:
            # Get ID
            survey_id = survey["id"]

            # Get questions
            question = survey["questions"].get(key)
            if not question:
                logger.error(
                    f"PPM/Qualtrics/{key}: Question not found",
                    extra={
                        "key": key,
                    },
                )

            question_definition = survey_definition["Questions"].get(key)
            if not question:
                logger.error(
                    f"PPM/Qualtrics/{key}: Question definition not found",
                    extra={
                        "key": key,
                    },
                )

            # Check if required
            if not question.get("validation", {}).get("doesForceResponse", False):
                return False

            # It's required, but check if it is conditionally enabled
            display_logic = question_definition.get("DisplayLogic", False)
            enabled = False
            if display_logic:
                logger.debug(f"PPM/Qualtrics/{survey_id}/{key}: Is required but also conditionally enabled")

                # We are only processing BooleanExpressions
                if display_logic["Type"] != "BooleanExpression":
                    logger.error(
                        f"PPM/Qualtrics/{survey_id}/{key}: Unhandled DisplayLogic type: {display_logic.get('Type')}",
                        extra={
                            "survey_id": survey_id,
                            "qid": key,
                            "question": question,
                            "question_definition": question_definition,
                            "display_logic": display_logic,
                        },
                    )
                    return False

                # Iterate conditions for display of this question
                # INFO: Currently only selected choice conditions are supported
                for expression in [v for k, v in display_logic.items() if type(v) is dict]:

                    # Check type
                    if expression["Type"] == "If":

                        # TODO: Not implemented to handle multiple logical statements
                        if len([v for k, v in expression.items() if type(v) is dict]) > 1:
                            logger.error(
                                f"PPM/Qualtrics/{survey_id}/{key}: Multiple DisplayLogic statements found",
                                extra={
                                    "survey_id": survey_id,
                                    "qid": key,
                                    "question": question,
                                    "question_definition": question_definition,
                                    "display_logic": display_logic,
                                },
                            )

                        # Iterate statements
                        for statement in [v for k, v in expression.items() if type(v) is dict]:

                            # Fetch the value of the answer
                            components = furl(statement["LeftOperand"]).path.segments

                            # Check type
                            if components[0] == "SelectableChoice":

                                # Get answer index and value
                                index = components[1]

                                # Find question
                                condition_qid = statement["QuestionID"]
                                conditional_question = survey_definition["Questions"][condition_qid]

                                # Get answer value
                                conditional_value = next(
                                    c["Display"] for i, c in conditional_question["Choices"].items() if i == index
                                )
                                logger.debug(
                                    f"PPM/Qualtrics/{survey_id}/{key}: Depends on {condition_qid} = "
                                    f"{conditional_value}"
                                )

                                # Get the actual response
                                responded_answer_items = Qualtrics.get_survey_response_values(
                                    survey=survey, response=response, qid=condition_qid
                                )
                                responded_values = [v for a in responded_answer_items for k, v in a.items()]

                                # Check if matches
                                if responded_values and conditional_value in responded_values:
                                    logger.debug(
                                        f"PPM/Qualtrics/{survey_id}/{key}: Condition {condition_qid} = "
                                        f"{responded_values} is satisfied"
                                    )

                                    # Set enabled
                                    enabled = True
                                else:
                                    logger.debug(
                                        f"PPM/Qualtrics/{survey_id}/{key}: Condition {condition_qid} = "
                                        f"{responded_values} is NOT satisfied"
                                    )

                                    # Set disabled
                                    enabled = False

            logger.debug(f"PPM/Qualtrics/{survey_id}/{key}: Conditional question is {'' if enabled else 'NOT '}enabled")
            return enabled

        except Exception as e:
            logger.exception(
                f"PPM/Qualtrics: Error checking requirement: {e}",
                exc_info=True,
                extra={
                    "survey_id": survey.get("id"),
                    "response_id": response.get("responseId"),
                    "question_id": key,
                },
            )

        # Assume required
        return True

    @classmethod
    def get_survey_response_values(cls, survey, response, qid):
        """
        This method parses a survey response and returns the value of the
        response for the given question, if any at all.

        :param survey: The survey object the response was for
        :type survey: dict
        :param response: The response object
        :type response: dict
        :param qid: The question ID to get the response value for
        :type qid: str
        :return: The response value(s), if any
        :rtype: list, defaults to None
        """
        # Filter values to those for this block/group
        pattern = rf"^({qid})(?![S\d])"
        values = {k: v for k, v in response["values"].items() if re.match(pattern, k)}
        if not values:
            return None

        # Get items
        items = [cls.questionnaire_response_item(survey, response, key) for key in values.keys()]

        # Get the first valid item
        item = next((i for i in items if i and i.get("answer")), None)
        if not item:
            return None

        return item.get("answer")

    @classmethod
    def questionnaire_response_item(cls, survey, response, key, loop=None):
        """
        Returns a FHIR QuestionnaireResponse.Item resource for the passed
        Qualtrics survey question response key and loop (if applicable).

        :param survey: The Qualtrics survey object
        :type survey: object
        :param response: The Qualtrics survey response item
        :type response: object
        :type survey: object
        :param key: The Qualtrics question ID to process
        :type key: str
        :param loop: The Qualtrics loop ID to process
        :type loop: str
        :raises Exception: Raises exception if value is an unhandled type
        :return: A FHIR QuestionnaireResponse.Item resource
        :rtype: dict
        """
        # Set regex for matching answer keys
        key_regex = re.compile(
            r"((?P<loop>[\d]{1,})_)?(?P<id>QID[\d]{1,}(S(?P<subqid>[\d]+))?)"
            r"(#(?P<columnid>[\d]+))?(_(?P<subid>[\d]+))?"
            r"(_(?P<type>[a-zA-Z]+))?"
        )

        # Ensure we've got an actual question's answer
        matches = re.match(key_regex, key)
        if not matches:
            return None

        # Set placeholders
        link_id = answer = None
        try:
            # Group matches
            matches = matches.groupdict()

            # Get ID and type
            q_loop = matches["loop"]
            q_id = matches["id"]
            q_columnid = matches["columnid"]
            q_subid = matches["subid"]
            q_type = matches["type"]

            # Get the value
            value = response["values"][key]

            # If in a loop, we only care about that loop's values
            if loop and str(loop) != q_loop:
                return None

            # Get question object
            question = survey["questions"].get(q_id)

            # Get linkID
            link_id = cls._qid_to_linkid(q_id)

            # Parse value depending on question/answer type
            question_type = question["questionType"]["type"]
            question_selector = question["questionType"]["selector"]

            # Check type

            # This describes options for the question's answer
            if q_type and q_type == "DO":

                # This is the list of options
                return None

            # Slider answer
            elif question_type == "Slider" and type(value) in [int, float]:

                # Set answer
                answer = value

            elif question_type == "HotSpot" and type(value) is str:

                # Skip if off
                if value.lower() == "off":
                    return None

                # Ensure we've got subquestions
                if q_subid:

                    # Find all values for this hot spot
                    pattern = rf"^({q_loop}_)?{q_id}_" if q_loop else rf"^{q_id}_"
                    _responses = {
                        k: v
                        for k, v in response["values"].items()
                        if re.match(pattern, k) and type(v) is str and v.lower() == "on"
                    }
                    if _responses:

                        # Sort them
                        _responses = collections.OrderedDict(sorted(_responses.items()))

                        # Join them together
                        answer = []
                        for k in [k for k, v in _responses.items()]:
                            _q_id = key_regex.match(k).groupdict()["id"]
                            _q_subid = key_regex.match(k).groupdict()["subid"]

                            # Add the label
                            answer.append(survey["questions"][_q_id]["subQuestions"][_q_subid]["choiceText"])

                else:
                    logger.error(
                        f"PPM/QuestionnaireResponse/{key}: Unhandled "
                        f"singular hot spot Qualtrics answer item: {value}"
                    )
                    return None

            # This is a matrix, single answer question
            elif question_type == "Matrix" and type(value) is int:

                # Just set label
                link_id = link_id + "-" + q_subid
                answer = response["labels"][key]

            elif question_type == "DD" and question_selector == "DL":

                # Check for single
                if not q_subid:
                    # Set it
                    answer = response["labels"][key]

                else:
                    # NOTE: This is a special case where for the time being,
                    # we just append values for each part of the drill down
                    # to a string

                    # Find all values for this drill down
                    pattern = rf"^({q_loop}_)?{q_id}_[\d]+" if q_loop else rf"^{q_id}_[\d]+"
                    _responses = {k: v for k, v in response["values"].items() if re.match(pattern, k)}
                    if _responses:

                        # Sort them
                        _responses = collections.OrderedDict(sorted(_responses.items()))

                        # Join them together
                        answer = " ".join([response["labels"][k] for k, v in _responses.items()])

                    else:
                        logger.error(
                            f"PPM/QuestionnaireResponse/{key}: Unhandled drill down Qualtrics answer item: {value}"
                        )
                        return None

            # This is a multiple-choice, single answer question (radio)
            elif question_type == "MC" and type(value) is int:

                # Add it
                answer = response["labels"][key]

            # This is a multiple matrix question answer
            elif question_type == "SBS" and question_selector == "SBSMatrix" and type(value) is int:

                # Add it
                answer = response["labels"][key]

                # Set link ID for sub question
                if q_subid:
                    link_id = f"{link_id}-{q_columnid}-{q_subid}"

            # This is a multiple-choice scale, multiple answer question (matrix)
            elif question_type == "MC" and type(value) is list:

                # If the answer is empty but this is a forced response, it's likely that this question has
                # a "None of the above" option and that's what was selected. Qualtrics just returns an empty
                # response in this instance.
                none_of_the_above = next(
                    (v["choiceText"] for k, v in question["choices"].items() if v.get("analyze") is False), None
                )
                if len(value) == 0 and question.get("validation", {}).get("doesForceResponse") and none_of_the_above:

                    # Use that answer
                    value_list = [none_of_the_above]

                else:
                    # Index to a list of options
                    value_list = response["labels"].get(key)

                # Set link ID for sub question
                if q_subid:
                    link_id = link_id + "-" + q_subid

                # Set the answer
                answer = value_list

            # Text answer
            elif q_type and q_type == "TEXT":

                # Easy
                answer = value

            # This is a multiple-choice, multiple answer question (checkbox)
            elif not q_type and type(value) is list:

                # Index to a list of options
                value_list = response["labels"].get(key)

                # Add it
                answer = value_list

            else:
                logger.error(
                    f"PPM/QuestionnaireResponse/{key}: Unhandled Qualtrics "
                    f"answer item: {value} ({q_id}/"
                    f"{q_subid}/{q_type})"
                )

        except (IndexError, ValueError, KeyError, TypeError) as e:
            logger.exception(
                f"PPM/QuestionnaireResponse/{key}: Unhandled  Qualtrics answer item: {key}: {e}",
                exc_info=True,
            )

        # Check
        if not link_id:
            logger.debug(
                f"PPM/Qualtrics/QuestionnaireResponse/{key}:Ignoring Qualtrics response answer item due to no link ID"
            )
            return None

        # Check answer
        if answer is None:
            logger.debug(
                f"PPM/Qualtrics/QuestionnaireResponse/{key}:"
                f"Ignoring Qualtrics response due to no answer: "
                f"{value} = {answer}"
            )
            return None

        # Return response after formatting answer
        return {"linkId": link_id, "answer": FHIR.Resources._questionnaire_response_answer(answer)}

    @classmethod
    def questionnaire_transaction(cls, questionnaire, questionnaire_id=None):
        """
        Accepts a Questionnaire object and builds the transaction to be used
        to perform the needed operation in FHIR. Operations can be POST or PUT,
        depending on if an ID is passed. If the object does not need to be created
        or updated, the operation will return as a success with an empty response
        object.

        :param questionnaire: The Questionnaire object to be persisted
        :type questionnaire: dict
        :param questionnaire_id: The ID to use for new Questionnaire, defaults to None
        :type questionnaire_id: str, optional
        :return: The response if the resource was created, None if no operation needed
        :rtype: dict
        """
        # Check for a version matching the created one
        version = questionnaire["version"]
        query = {"identifier": f"{FHIR.qualtrics_survey_version_identifier_system}|{version}"}
        if questionnaire_id:
            query["_id"] = questionnaire_id

        questionnaires = FHIR._query_resources("Questionnaire", query)
        if questionnaires:

            # No need to recreate it
            logger.debug(f"PPM/Qualtrics: Questionnaire already exists for survey version {version}")
            return None

        # Use the FHIR client lib to validate our resource.
        questionnaire = Questionnaire(questionnaire)
        questionnaire_request = BundleEntryRequest(
            {
                "url": f"Questionnaire/{questionnaire_id}" if questionnaire_id else "Questionnaire",
                "method": "PUT" if questionnaire_id else "POST",
            }
        )
        questionnaire_entry = BundleEntry()
        questionnaire_entry.resource = questionnaire
        questionnaire_entry.request = questionnaire_request

        # Validate it.
        bundle = Bundle()
        bundle.entry = [questionnaire_entry]
        bundle.type = "transaction"

        # Create the organization
        response = requests.post(PPM.fhir_url(), json=bundle.as_json())
        logger.debug("PPM/Qualtrics: FHIR Response: {}".format(response.status_code))
        response.raise_for_status()

        return response.json()
