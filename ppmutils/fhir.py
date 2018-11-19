import collections

from django.utils.safestring import mark_safe
from fhirclient.models.bundle import Bundle

import logging
logger = logging.getLogger(__name__)


class FHIR:

    @staticmethod
    def flatten_questionnaire_response(bundle_dict, questionnaire_id):
        '''
        Picks out the relevant Questionnaire and QuestionnaireResponse resources and
        returns a dict mapping the text of each question to a list of answer texts.
        To handle duplicate question texts, each question is prepended with an index.
        :param bundle_dict: The parsed JSON response from a FHIR query
        :param questionnaire_id: The ID of the Questionnaire to parse for
        :return: dict
        '''

        # Build the bundle
        bundle = Bundle(bundle_dict)

        # Pick out the questionnaire and its response
        questionnaire = next((entry.resource for entry in bundle.entry if entry.resource.id == questionnaire_id), None)
        questionnaire_response = next((entry.resource for entry in bundle.entry if
                                       entry.resource.resource_type == 'QuestionnaireResponse' and
                                       entry.resource.questionnaire.reference ==
                                       'Questionnaire/{}'.format(questionnaire_id)), None)

        # Ensure resources exist
        if not questionnaire or not questionnaire_response:
            logger.debug('Missing resources: {}'.format(questionnaire_id))
            return None

        # Get questions and answers
        questions = FHIR._questions(questionnaire.item)
        answers = FHIR._answers(questionnaire_response.item)

        # Process sub-questions first
        for linkId, condition in {linkId: condition for linkId, condition in questions.items() if type(condition) is dict}.items():

            try:
                # Assume only one condition, fetch the parent question linkId
                parent = next(iter(condition))
                if not parent:
                    logger.warning('FHIR Error: Subquestion not properly specified: {}:{}'.format(linkId, condition),
                                   extra={'questionnaire': questionnaire_id, 'ppm_id': questionnaire_response.source,
                                          'questionnaire_response': questionnaire_response.id})
                    continue

                if len(condition) > 1:
                    logger.warning('FHIR Error: Subquestion has multiple conditions: {}:{}'.format(linkId, condition),
                                   extra={'questionnaire': questionnaire_id, 'ppm_id': questionnaire_response.source,
                                          'questionnaire_response': questionnaire_response.id})

                # Ensure they've answered this one
                if not answers.get(parent) or condition[parent] not in answers.get(parent):
                    continue

                # Get the question and answer item
                answer = answers[parent]
                index = answer.index(condition[parent])

                # Check for commas
                sub_answers = answers[linkId]
                if ',' in next(iter(sub_answers)):

                    # Split it
                    sub_answers = [sub.strip() for sub in next(iter(sub_answers)).split(',')]

                # Format them
                value = '{} <span class="label label-primary">{}</span>'.format(
                    answer[index], '</span>&nbsp;<span class="label label-primary">'.join(sub_answers))

                # Append the value
                answer[index] = mark_safe(value)

            except Exception as e:
                logger.exception('FHIR error: {}'.format(e), exc_info=True,
                                 extra={'questionnaire': questionnaire_id, 'link_id': linkId,
                                        'ppm_id': questionnaire_response.source})

        # Build the response
        response = collections.OrderedDict()

        # Process top-level questions first
        top_questions = collections.OrderedDict(sorted({linkId: question for linkId, question in questions.items() if
                                                        type(question) is str}.items(),
                                                       key=lambda q: int(q[0].split('-')[1])))
        for linkId, question in top_questions.items():

            # Check for the answer
            answer = answers.get(linkId)
            if not answer:
                answer = [mark_safe('<span class="label label-info">N/A</span>')]
                logger.warning(f'FHIR Error: No answer found for {linkId}',
                               extra={'questionnaire': questionnaire_id, 'link_id': linkId,
                                      'ppm_id': questionnaire_response.source})

            # Format the question text
            text = '{}. {}'.format(len(response.keys()) + 1, question)

            # Add the answer
            response[text] = answer

        return response

    @staticmethod
    def _questions(items):

        # Iterate items
        questions = {}
        for item in items:

            # Leave out display or ...
            if item.type == 'display':
                continue

            elif item.type == 'group' and item.item:

                # Get answers
                sub_questions = FHIR._questions(item.item)

                # Add them
                questions.update(sub_questions)

            elif item.enableWhen:

                # This is a sub-question
                questions[item.linkId] = {
                    next(condition.question for condition in item.enableWhen):
                        next(condition.answerString for condition in item.enableWhen)
                }

            else:

                # Ensure it has text
                if item.text:
                    # List them out
                    questions[item.linkId] = item.text

                else:
                    # Indicate a blank question text, presumably a sub-question
                    questions[item.linkId] = '-'

                # Check for subtypes
                if item.item:
                    # Get answers
                    sub_questions = FHIR._questions(item.item)

                    # Add them
                    questions.update(sub_questions)

        return questions

    @staticmethod
    def _answers(items):

        # Iterate items
        responses = {}
        for item in items:

            # List them out
            responses[item.linkId] = []

            # Ensure we've got answers
            if not item.answer:
                logger.error('FHIR questionnaire error: Missing items for question', extra={'link_id': item.linkId})
                responses[item.linkId] = ['------']

            else:

                # Iterate answers
                for answer in item.answer:

                    # Get the value
                    if answer.valueBoolean is not None:
                        responses[item.linkId].append(answer.valueBoolean)
                    elif answer.valueString is not None:
                        responses[item.linkId].append(answer.valueString)
                    elif answer.valueInteger is not None:
                        responses[item.linkId].append(answer.valueInteger)
                    elif answer.valueDate is not None:
                        responses[item.linkId].append(answer.valueDate)
                    elif answer.valueDateTime is not None:
                        responses[item.linkId].append(answer.valueDateTime)
                    elif answer.valueDateTime is not None:
                        responses[item.linkId].append(answer.valueDateTime)

                    else:
                        logger.warning('Unhandled answer value type: {}'.format(answer.as_json()),
                                       extra={'link_id': item.linkId})

            # Check for subtypes
            if item.item:
                # Get answers
                sub_answers = FHIR._answers(item.item)

                # Add them
                responses[item.linkId].extend(sub_answers)

        return responses
