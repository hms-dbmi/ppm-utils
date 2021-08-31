from datetime import datetime
from dateutil.parser import parse
import hashlib
import json
import re
import sys
import collections
import warnings
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
                    "PPM/Questionnaire: Unhandled survey question" f" type {survey_id}/{question_id}: {question_type}"
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
        cls, study, ppm_id, questionnaire_id, survey_id, response_id, survey=None, response=None
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
        :param survey: The Qualtrics survey object
        :type survey: dict, defaults to None
        :param response: The Qualtrics survey response object
        :type response: dict, defaults to None
        :return: The QuestionnaireResponse resource
        :rtype: dict
        """
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
            data["item"] = list(cls.questionnaire_response_item_generator(survey, response, blocks))

            # Set dates if specified.
            if response.get("endDate"):
                data["authored"] = response["endDate"]

        return data

    @classmethod
    def questionnaire_response_item_generator(cls, survey, response, blocks):
        """
        Accepts the survey, response objects as well as the list of blocks add their
        respective questions and yields a set of QuestionnareResponseItem
        resources to be set for the QuestionnaireResponse.

        :param survey: The Qualtrics survey object
        :type survey: object
        :param response: The Qualtrics survey response item
        :type response: object
        :param blocks: The dictionary of blocks comprising the survey
        :type blocks: dict
        :param blocks: The ID of the specific block to process
        :type blocks: str
        :raises Exception: Raises exception if value is an unhandled type
        :returns A generator of QuestionnaireResponseItem resources
        :rtype generator
        """
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
                    # Filter values to those for this block/group
                    values = {
                        k: v
                        for k, v in response["values"].items()
                        if re.match(rf"^({'|'.join(question_ids)}[^\d]?)", k)
                    }
                    if not values:
                        logger.warning(f"PPM/FHIR/Qualtrics: Cannot find values for '{block_id}/{question_ids}'")
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
                    f"PPM/FHIR: Error processing block {block_id}: {e}",
                    exc_info=True,
                    extra={
                        "survey_id": survey["id"],
                        "block_id": block_id,
                    },
                )
                raise e

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
                        f"PPM/Questionnaire: Unhandled singular hot spot Qualtrics " f"answer item: {key} = {value}"
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
                            f"PPM/Questionnaire: Unhandled drill down Qualtrics " f"answer item: {key} = {value}"
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
                    f"PPM/Questionnaire: Unhandled Qualtrics "
                    f"answer item: {key} = {value} ({q_id}/"
                    f"{q_subid}/{q_type})"
                )

        except (IndexError, ValueError, KeyError, TypeError) as e:
            logger.exception(
                f"PPM/Questionnaire: Unhandled Qualtrics " f"answer item: {key}: {e}",
                exc_info=True,
            )

        # Check
        if not link_id or not answer:
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
            logger.debug(f"API/Qualtrics: Questionnaire already exists for survey version {version}")
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
        logger.debug("Response: {}".format(response.status_code))
        response.raise_for_status()

        return response.json()

    @classmethod
    def ppm_qualtrics_survey_questionnaire(cls, study, questionnaire_id, survey_id, survey):
        """
        Returns QuestionnaireResponse resource for a survey taken through
        Qualtrics. This method requires that Qualtrics question names are
        matched to the FHIR Questionnaire linkIds.

        :param study: The study for which the questionnaire was given
        :type study: PPM.Study
        :param questionnaire_id: The ID for the related FHIR Questionnaire
        :type questionnaire_id: str
        :param survey_id: The ID of the Qualtrics survey
        :type survey_id: str
        :param survey: The survey object from Qualtrics
        :type survey: dict
        :return: The QuestionnaireResponse resource
        :rtype: dict
        """
        warnings.warn(f"This method should not be used. Instead use Qualtrics.questionnaire()", DeprecationWarning)

        # Hash the questions of the survey to track version of the survey
        version = hashlib.md5(json.dumps(survey["questions"], sort_keys=True).encode()).hexdigest()

        # Build a dictionary describing block and question order
        blocks = {
            f["id"]: [
                e["questionId"] for e in survey["blocks"][f["id"]].get("elements", []) if e.get("type") == "Question"
            ]
            for f in survey["flow"]
            if f.get("type") == "Block"
        }

        # Build list of items
        items = []
        for _, question_ids in blocks.items():

            # Create them
            items.extend(
                [
                    cls.ppm_qualtrics_survey_questionnaire_item(survey, qid, survey["questions"][qid])
                    for qid in question_ids
                ]
            )

        # Build the resource
        data = {
            "id": questionnaire_id,
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
            ],
            "version": version,
            "name": survey_id,
            "title": survey["name"],
            "status": "active" if survey["isActive"] else "draft",
            "approvalDate": survey["creationDate"],
            "date": survey["lastModifiedDate"],
            "extension": [
                {
                    "url": FHIR.qualtrics_survey_extension_url,
                    "valueString": survey_id,
                }
            ],
            "item": items,
        }

        # If expiration, add it
        if survey.get("expiration", {}).get("startDate"):

            data["effectivePeriod"] = {
                "start": survey["expiration"]["startDate"],
                "end": survey["expiration"]["endDate"],
            }

            # If after expiration, set status
            if survey["expiration"].get("endDate"):
                if parse(survey["expiration"]["endDate"]) < datetime.now():
                    data["status"] = "retired"

        return data

    @classmethod
    def ppm_qualtrics_survey_questionnaire_items(cls, survey, blocks):
        """
        Accepts the survey object as well as the list of blocks and their
        respective questions and yields a set of QuestionnareItem
        resources to be set for the Questionnaire.

        :param survey: The Qualtrics survey object
        :type survey: object
        :param blocks: The dictionary of blocks comprising the survey
        :type blocks: dict
        :raises Exception: Raises exception if value is an unhandled type
        :returns A generator of QuestionnaireItem resources
        :rtype generator
        """
        warnings.warn(
            f"This method should not be used. Instead use Qualtrics.questionnaire_item_generator()", DeprecationWarning
        )
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

                    # Create this
                    pass

                else:

                    # Process each question
                    for question_id in question_ids:

                        # Set root link ID
                        link_id = cls._qid_to_linkid(question_id)

                        # Fetch the question
                        question = survey["questions"][question_id]

                        # Strip text of HTML and other characters
                        text = (
                            re.sub("<[^<]+?>", "", question["QuestionText"]).strip().replace("\n", "").replace("\r", "")
                        )
                        text = text.replace("&nbsp;", " ")

                        # Determine if required
                        required = question["validation"].get("doesForceResponse", False)

                        # Get question text
                        item = {
                            "linkId": link_id,
                            "text": text,
                            "required": required,
                        }

                        yield item

            except Exception as e:
                logger.exception(
                    f"PPM/FHIR: Error processing block {block_id}: {e}",
                    exc_info=True,
                    extra={
                        "survey_id": survey["id"],
                        "block_id": block_id,
                    },
                )
                raise e

    @classmethod
    def ppm_qualtrics_survey_questionnaire_item(cls, survey, qid, question):
        """
        Returns a FHIR resource for a QuestionnaireItem parsed from
        the Qualtrics survey's question

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
        warnings.warn(
            f"This method should not be used. Instead use Qualtrics.questionnaire_item()",
            DeprecationWarning,
        )
        # Get common survey info
        survey_id = survey["id"]

        # Set root link ID
        link_id = cls._qid_to_linkid(qid)

        # Strip text of HTML and other characters
        text = re.sub("<[^<]+?>", "", question["questionText"]).strip().replace("\n", "").replace("\r", "")

        # Remove nbsp;'s
        text.replace("&nbsp;", "")

        # Get question text
        item = {"linkId": link_id, "text": text, "required": question["validation"].get("doesForceResponse", False)}

        # Check for conditional enabling
        if question.get("DisplayLogic", False):

            # Intialize enableWhen item
            enable_whens = []

            # We are only processing BooleanExpressions
            if question["DisplayLogic"]["Type"] != "BooleanExpression":
                logger.error(
                    f"PPM/Questionnaire: Unhandled DisplayLogic " f"type {survey_id}/{qid}: {question['DisplayLogic']}"
                )
                raise ValueError(f"Failed to process survey {survey['id']}")

            # Iterate conditions for display of this question
            # INFO: Currently only selected choice conditions are supported
            for k, expression in question["DisplayLogic"].items():

                # Check type
                if expression["Type"] == "If":

                    # Iterate statements
                    for j, statement in expression.items():

                        # Fetch the value of the answer
                        components = furl(statement["LeftOperand"]).path.segments

                        # Check type
                        if components[0] == "SelectableChoice":

                            # Get answer index and value
                            index = components[1]

                            # Find question
                            conditional_question = next(
                                e for e in survey["SurveyElements"] if e["PrimaryAttribute"] == qid
                            )

                            # Get answer value
                            conditional_value = next(
                                c["Display"] for i, c in conditional_question["Payload"]["Choices"] if i == index
                            )

                            # Add it
                            enable_whens.append(
                                {
                                    "question": cls._qid_to_linkid(qid),
                                    "answerString": conditional_value,
                                }
                            )

                        else:
                            logger.error(
                                f"PPM/Questionnaire: Unhandled DisplayLogic expression"
                                f"type {survey_id}/{qid}: {expression}"
                            )
                            raise ValueError(f"Failed to process survey {survey['id']}")

                else:
                    logger.error(f"PPM/Questionnaire: Unhandled DisplayLogic " f"type {survey_id}/{qid}: {expression}")
                    raise ValueError(f"Failed to process survey {survey['id']}")

            # Add enableWhen's if we've got them
            if enable_whens:
                item["enableWhen"] = enable_whens

        # Check type
        question_type = question["questionType"]

        try:
            # Text (single line)
            if question_type["type"] == "TE" and question_type["selector"] == "SL":

                # Set type
                item["type"] = "string"

            # Text (multiple line)
            elif question_type["type"] == "TE" and question_type["selector"] == "ESTB":

                # Set type
                item["type"] = "text"

            # Text (multiple line)
            elif question_type["type"] == "TE" and question_type["selector"] == "ML":

                # Set type
                item["type"] = "text"

            # Multiple choice (single answer)
            elif question_type["type"] == "MC" and question_type["selector"] == "SAVR":

                # Set type
                item["type"] = "choice"

                # Set choices
                item["option"] = [{"valueString": c["choiceText"]} for k, c in question["choices"].items()]

            # Multiple choice (multiple answer)
            elif question_type["type"] == "MC" and question_type["selector"] == "MAVR":

                # Set type
                item["type"] = "choice"
                item["repeats"] = True

                # Set choices
                item["option"] = [{"valueString": c["choiceText"]} for k, c in question["choices"].items()]

            # Matrix (single answer)
            elif (
                question_type["type"] == "Matrix"
                and question_type["selector"] == "Likert"
                and question_type["subSelector"] == "SingleAnswer"
            ):

                # Add this as a grouped set of multiple choice, single answer questions
                item["type"] = "group"

                # Preselect choices
                choices = [{"valueString": c["choiceText"]} for k, c in question["choices"].items()]

                # Set subitems
                item["item"] = [
                    {
                        "linkId": f"{link_id}-{k}",
                        "text": s["choiceText"],
                        "type": "choice",
                        "option": choices,
                        "required": question["validation"].get("doesForceResponse", False),
                    }
                    for k, s in question["subQuestions"].items()
                ]

            # Matrix (multiple answer)
            elif (
                question_type["type"] == "Matrix"
                and question_type["selector"] == "Likert"
                and question_type["subSelector"] == "MultipleAnswer"
            ):

                # Add this as a grouped set of multiple choice, single answer questions
                item["type"] = "group"
                item["repeats"] = True

                # Preselect choices
                choices = [{"valueString": c["choiceText"]} for k, c in question["choices"].items()]

                # Set subitems
                item["item"] = [
                    {
                        "linkId": f"{link_id}-{k}",
                        "text": s["choiceText"],
                        "type": "choice",
                        "option": choices,
                        "required": question["validation"].get("doesForceResponse", False),
                    }
                    for k, s in question["subQuestions"].items()
                ]

            # Multiple Matrix (multiple answer)
            elif question_type["type"] == "SBS" and question_type["selector"] == "SBSMatrix":

                item["type"] = "group"
                item["text"] = question["questionText"]
                item["item"] = []

                # Get choices
                questions = {k: c["choiceText"] for k, c in question["subQuestions"].items()}

                # Add this as multiple grouped sets of multiple choice, single answer questions
                for k, additional_question in question["columns"].items():

                    # Add another display for the subquestion
                    sub_item = {
                        "linkId": f"{link_id}-{k}",
                        "type": "group",
                        "text": additional_question["questionText"],
                        "item": [],
                    }

                    # Preselect choices
                    answers = [{"valueString": c["choiceText"]} for k, c in additional_question["choices"].items()]

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
                                "required": question["validation"].get("doesForceResponse", False),
                            }
                        )

                    # Add it
                    item["item"].append(sub_item)

            # Slider (integer answer)
            elif question_type["type"] == "Slider" and question_type["selector"] == "HBAR":

                # Set type
                item["type"] = "integer"

            # Slider (integer answer)
            elif question_type["type"] == "Slider" and question_type["selector"] == "HSLIDER":

                # Set type
                item["type"] = "decimal"

            # Hot spot (multiple choice, multiple answer)
            elif question_type["type"] == "HotSpot" and question_type["selector"] == "OnOff":

                # Set type
                item["type"] = "choice"
                item["repeats"] = True

                # Set choices
                item["option"] = [{"valueString": c["choiceText"]} for k, c in question["subQuestions"].items()]

            # Drill down
            elif question_type["type"] == "DD" and question_type["selector"] == "DL":

                # Set type
                item["type"] = "choice"
                item["repeats"] = False

                # Set choices
                item["option"] = [{"valueString": c["Display"]} for k, c in question["Answers"].items()]

            # Descriptive text
            elif question_type["type"] == "DB":

                # Set type
                item["type"] = "display"

            # Descriptive graphics
            elif question_type["type"] == "GB":

                # Set type
                item["type"] = "display"

            else:
                logger.error("PPM/Questionnaire: Unhandled survey question" f" type {survey_id}/{qid}: {question_type}")
                raise ValueError(f"Failed to process survey {survey['id']}")
        except Exception as e:
            logger.exception(
                f"PPM/FHIR: Error processing question" f" {survey_id}/{qid}: {e}",
                exc_info=True,
                extra={
                    "survey_id": survey["id"],
                    "qid": qid,
                    "question": question,
                },
            )
            raise e

        return item
