import mock
import responses
import random
import unittest
import uuid
import re
import json
from datetime import datetime, timezone

from ppmutils.ppm import PPM
from ppmutils.fhir import FHIR


class TestFHIR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):

        # Set the FHIR URL
        cls.fhir_url = "https://fhir.ppm.aws.dbmi-test.hms.harvard.edu"
        cls.fhir_url_pattern = r"{}/.*".format(cls.fhir_url)

        # Patch PPM FHIR URL
        cls.ppm_fhir_url_patcher = mock.patch("ppmutils.ppm.PPM.fhir_url")
        cls.mock_ppm_fhir_url = cls.ppm_fhir_url_patcher.start()
        cls.mock_ppm_fhir_url.return_value = cls.fhir_url

    @classmethod
    def tearDownClass(cls):

        # Disable patcher
        cls.ppm_fhir_url_patcher.stop()

    @responses.activate
    def test_query_patient(self):

        # Set patient email
        email = "patient@email.org"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            email,
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )
        study = FHIRData.research_study(PPM.Study.NEER)
        subject = FHIRData.research_subject("Patient/{}".format(patient["id"]), PPM.Study.NEER)
        enrollment = FHIRData.enrollment_flag("Patient/{}".format(patient["id"]), PPM.Study.NEER)

        # Put them in a bundle
        bundle = FHIRData.create_bundle([patient, study, subject, enrollment], self.fhir_url)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=bundle,
            status=200,
        )

        # Do the query
        queried_patient = FHIR.get_patient(email, flatten_return=True)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertEqual(queried_patient["email"], email)

    @responses.activate
    def test_query_patient_id(self):

        # Set patient email
        email = "patient@email.org"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            email,
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )

        # Put them in a bundle
        bundle = FHIRData.create_bundle([patient], self.fhir_url)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=bundle,
            status=200,
        )

        # Do the query
        ppm_id = FHIR.query_patient_id(email)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertEqual(ppm_id, patient["id"])

    @responses.activate
    def test_query_participant(self):

        # Set patient email
        email = "patient@email.org"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            email,
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )
        study = FHIRData.research_study(PPM.Study.NEER)
        subject = FHIRData.research_subject("Patient/{}".format(patient["id"]), PPM.Study.NEER)
        enrollment = FHIRData.enrollment_flag("Patient/{}".format(patient["id"]), PPM.Study.NEER)

        # Put them in a bundle
        bundle = FHIRData.create_bundle([patient, study, subject, enrollment], self.fhir_url)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=bundle,
            status=200,
        )

        # Do the query
        queried_patient = FHIR.get_participant(email, PPM.Study.NEER.value, flatten_return=True)
        print(queried_patient)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertEqual(queried_patient["email"], email)
        self.assertEqual(queried_patient["study"], PPM.Study.NEER.value)
        self.assertEqual(queried_patient["enrollment"], PPM.Enrollment.Registered.value)

    @responses.activate
    def test_query_enrollment_status(self):

        # Set patient email
        email = "patient@email.org"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            email,
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )
        study = FHIRData.research_study(PPM.Study.NEER)
        subject = FHIRData.research_subject("Patient/{}".format(patient["id"]), PPM.Study.NEER)
        enrollment = FHIRData.enrollment_flag(
            "Patient/{}".format(patient["id"]), PPM.Study.NEER, PPM.Enrollment.Proposed.value
        )

        # Put them in a bundle
        bundle = FHIRData.create_bundle([patient, study, subject, enrollment], self.fhir_url)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=bundle,
            status=200,
        )

        # Do the query
        resources = FHIR.query_enrollment_flags(email, study=PPM.Study.NEER.value)

        # Get the flag's status
        flag = next(r for r in resources if r["resourceType"] == "Flag")
        queried_enrollment = flag["code"]["coding"][0]["code"]

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(queried_enrollment == PPM.Enrollment.Proposed.value)

    @responses.activate
    def test_query_participants(self):

        # Start a data set
        data = FHIRData(self.fhir_url, participants=3)

        # Separate bundle since we do this in two queries
        research_subject_bundle = dict(data.bundle)
        research_subject_bundle["entry"] = [
            e
            for e in research_subject_bundle["entry"]
            if e["resource"]["resourceType"] in ["Patient", "ResearchSubject"]
        ]

        flag_bundle = dict(data.bundle)
        flag_bundle["entry"] = [e for e in flag_bundle["entry"] if e["resource"]["resourceType"] in ["Flag"]]

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=research_subject_bundle,
            status=200,
        )
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=flag_bundle,
            status=200,
        )

        # Do the query
        participants = FHIR.query_participants(testing=True)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertEqual(len(participants), 3)

        # Check some properties
        self.assertTrue(PPM.Study.enum(participants[2]["study"]) in PPM.Study)
        self.assertTrue(participants[1]["email"] is not None)
        self.assertTrue(PPM.Enrollment.enum(participants[2]["enrollment"]) in PPM.Enrollment)

    @responses.activate
    def test_query_study_participants(self):

        # Start a data set
        data = FHIRData(self.fhir_url, participants=100)

        # Separate bundle since we do this in two queries
        research_subject_bundle = dict(data.bundle)
        research_subject_bundle["entry"] = [
            e
            for e in research_subject_bundle["entry"]
            if e["resource"]["resourceType"] in ["Patient", "ResearchSubject"]
        ]

        flag_bundle = dict(data.bundle)
        flag_bundle["entry"] = [e for e in flag_bundle["entry"] if e["resource"]["resourceType"] in ["Flag"]]

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=research_subject_bundle,
            status=200,
        )
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=flag_bundle,
            status=200,
        )

        # Do the query
        participants = FHIR.query_participants(studies=[PPM.Study.NEER], testing=True)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)

        # Ensure non-NEER participants are fitered out
        self.assertLess(len(participants), 100)

        # Check some properties
        self.assertTrue(PPM.Study.enum(participants[2]["study"]) is PPM.Study.NEER)
        self.assertTrue(participants[1]["email"] is not None)
        self.assertTrue(PPM.Enrollment.enum(participants[2]["enrollment"]) in PPM.Enrollment)

    @responses.activate
    def test_query_enrollment_participants(self):

        # Start a data set
        data = FHIRData(self.fhir_url, participants=100)

        # Separate bundle since we do this in two queries
        research_subject_bundle = dict(data.bundle)
        research_subject_bundle["entry"] = [
            e
            for e in research_subject_bundle["entry"]
            if e["resource"]["resourceType"] in ["Patient", "ResearchSubject"]
        ]

        flag_bundle = dict(data.bundle)
        flag_bundle["entry"] = [e for e in flag_bundle["entry"] if e["resource"]["resourceType"] in ["Flag"]]

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=research_subject_bundle,
            status=200,
        )
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=flag_bundle,
            status=200,
        )

        # Do the query
        participants = FHIR.query_participants(enrollments=[PPM.Enrollment.Accepted], testing=True)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)

        # Ensure non-Accepted participants are fitered out
        self.assertLess(len(participants), 100)

        # Check some properties
        self.assertTrue(
            PPM.Enrollment.enum(participants[random.randint(0, len(participants) - 1)]["enrollment"])
            is PPM.Enrollment.Accepted
        )
        self.assertTrue(participants[1]["email"] is not None)

    @responses.activate
    def test_query_study_enrollment_participants(self):

        # Set total number of participants
        total_participants = 1000

        # Start a data set
        data = FHIRData(self.fhir_url, participants=total_participants)

        # Separate bundle since we do this in two queries
        research_subject_bundle = dict(data.bundle)
        research_subject_bundle["entry"] = [
            e
            for e in research_subject_bundle["entry"]
            if e["resource"]["resourceType"] in ["Patient", "ResearchSubject"]
        ]

        flag_bundle = dict(data.bundle)
        flag_bundle["entry"] = [e for e in flag_bundle["entry"] if e["resource"]["resourceType"] in ["Flag"]]

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=research_subject_bundle,
            status=200,
        )
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=flag_bundle,
            status=200,
        )

        # Do the query
        participants = FHIR.query_participants(
            studies=[PPM.Study.RANT], enrollments=[PPM.Enrollment.Consented], testing=True
        )

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)

        # Ensure participants are fitered out
        self.assertLess(len(participants), total_participants)

        # Check some properties
        self.assertTrue(
            PPM.Enrollment.enum(participants[random.randint(0, len(participants) - 1)]["enrollment"])
            is PPM.Enrollment.Consented
        )
        self.assertTrue(
            PPM.Study.enum(participants[random.randint(0, len(participants) - 1)]["study"]) is PPM.Study.RANT
        )
        self.assertTrue(participants[1]["email"] is not None)

    @responses.activate
    def test_patient_update_lastname(self):

        # Build a patient with a lastname
        patient = FHIRData.patient("patient@email.org", firstname="User", lastname="Patient")

        # Set an example form
        form = {"firstname": "Newer", "lastname": None}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertTrue(payload["name"][0].get("family", False))

    @responses.activate
    def test_patient_update_add_address2(self):

        # Build a patient with a lastname
        patient = FHIRData.patient("patient@email.org", firstname="User", lastname="Patient")

        # Set an example form
        form = {"street_address1": "3100 Some Address", "street_address2": "Unit 401"}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertTrue(len(payload["address"][0]["line"]) > 1)

    @responses.activate
    def test_patient_update_remove_address2(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
        )

        # Set an example form
        form = {"street_address1": "3100 Some Address", "street_address2": None}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertTrue(len(payload["address"][0]["line"]) == 1)

    @responses.activate
    def test_patient_update_add_contact_email(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
        )

        # Set an example form
        form = {"contact_email": "user@email.org"}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertTrue(
            next(
                (telecom for telecom in payload["telecom"] if telecom["system"] == "email"),
                False,
            )
        )

    @responses.activate
    def test_patient_update_contact_email(self):

        # Set the new email
        contact_email = "somenewemail@email.com"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
        )

        # Set an example form
        form = {"contact_email": contact_email}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertEqual(
            next(telecom for telecom in payload["telecom"] if telecom["system"] == "email")["value"],
            contact_email,
        )

    @responses.activate
    def test_patient_update_remove_contact_email(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )

        # Set an example form
        form = {"contact_email": None}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertFalse(
            next(
                (telecom for telecom in payload["telecom"] if telecom["system"] == "email"),
                False,
            )
        )

    @responses.activate
    def test_patient_update_add_referral(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
        )

        # Set an example form
        form = {"how_did_you_hear_about_us": "I was referred by John Smith"}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertTrue(
            next(
                (e for e in payload["extension"] if e["url"] == FHIR.referral_extension_url),
                False,
            )
        )

    @responses.activate
    def test_patient_update_referral(self):

        # Set new value
        referral = "new_referral"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
        )
        patient.setdefault("extension", []).append({"url": FHIR.referral_extension_url, "valueString": "old_referral"})

        # Set an example form
        form = {"how_did_you_hear_about_us": referral}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertEqual(
            next(
                (e for e in payload["extension"] if e["url"] == FHIR.referral_extension_url),
                False,
            )["valueString"],
            referral,
        )

    @responses.activate
    def test_patient_update_remove_referral(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )

        # Set an example form
        form = {"how_did_you_hear_about_us": None}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure last name was removed
        self.assertFalse(
            next(
                (e for e in payload["extension"] if e["url"] == FHIR.referral_extension_url),
                False,
            )
        )

    @responses.activate
    def test_patient_update_requirements(self):

        # Build a patient with a lastname
        patient = FHIRData.patient(
            "patient@email.org",
            firstname="User",
            lastname="Patient",
            street2="Unit 500",
            contact_email="user@email.org",
        )

        # Set an example form
        form = {"firstname": None, "email": None, "city": None, "phone": None}

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient/.*"),
            json=patient,
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient/.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient(patient["id"], form=form)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertTrue(len(payload["name"][0]["given"]) > 0)
        self.assertTrue(
            next(
                (id["value"] for id in payload["identifier"] if id["system"] == "http://schema.org/email"),
                False,
            )
        )
        self.assertTrue(payload["address"][0].get("city", False))
        self.assertTrue(
            next(
                (telecom["value"] for telecom in payload["telecom"] if telecom["system"] == "phone"),
                False,
            )
        )

    @responses.activate
    def test_update_patient_deceased_1(self):

        # Set the deceased date
        deceased = datetime.now(timezone.utc)

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_deceased(patient["id"], deceased)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "replace")
        self.assertEqual(payload[0]["value"], deceased.isoformat())

    @responses.activate
    def test_update_patient_deceased_2(self):

        # Set the deceased date
        deceased = None

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_deceased(patient["id"], deceased)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "remove")

    @responses.activate
    def test_update_patient_deceased_3(self):

        # Set the deceased date
        deceased = datetime.now(timezone.utc)

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_deceased(patient["id"], deceased, active=False)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "replace")
        self.assertEqual(payload[0]["path"], "/deceasedDateTime")
        self.assertEqual(payload[0]["value"], deceased.isoformat())
        self.assertEqual(payload[1]["op"], "replace")
        self.assertEqual(payload[1]["path"], "/active")
        self.assertEqual(payload[1]["value"], False)

    @responses.activate
    def test_update_patient_deceased_4(self):

        # Set the deceased date
        deceased = None

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_deceased(patient["id"], deceased, active=True)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "remove")
        self.assertEqual(payload[0]["path"], "/deceasedDateTime")
        self.assertEqual(payload[1]["op"], "replace")
        self.assertEqual(payload[1]["path"], "/active")
        self.assertEqual(payload[1]["value"], True)

    @responses.activate
    def test_update_patient_twitter_1(self):

        # Set the the handle
        handle = "sometwitterhandle"
        uses_twitter = None

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_twitter(patient["id"], handle, uses_twitter)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get telecom
        telecom = next(t for t in payload["telecom"] if t["system"] == FHIR.patient_twitter_telecom_system)
        self.assertEqual(telecom["value"], "https://twitter.com/" + handle)

        # Get extension
        extension = next(e for e in payload["extension"] if e["url"] == FHIR.twitter_extension_url)
        self.assertEqual(extension["valueBoolean"], True)

    @responses.activate
    def test_update_patient_twitter_2(self):

        # Set the the handle
        handle = None
        uses_twitter = None

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_twitter(patient["id"], handle, uses_twitter)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get telecom
        telecom = next(
            (t for t in payload["telecom"] if t["system"] == FHIR.patient_twitter_telecom_system),
            None,
        )
        self.assertIsNone(telecom)

        # Get extension
        extension = next(
            (e for e in payload["extension"] if e["url"] == FHIR.twitter_extension_url),
            None,
        )
        self.assertIsNone(extension)

    @responses.activate
    def test_update_patient_twitter_3(self):

        # Set the the handle
        handle = None
        uses_twitter = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_twitter(patient["id"], handle, uses_twitter)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get telecom
        telecom = next(
            (t for t in payload["telecom"] if t["system"] == FHIR.patient_twitter_telecom_system),
            None,
        )
        self.assertIsNone(telecom)

        # Get extension
        extension = next(
            (e for e in payload["extension"] if e["url"] == FHIR.twitter_extension_url),
            None,
        )
        self.assertEqual(extension["valueBoolean"], uses_twitter)

    @responses.activate
    def test_update_patient_twitter_4(self):

        # Set the the handle
        handle = None
        uses_twitter = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set an initial handle and extension
        patient["telecom"].append(
            {
                "system": FHIR.patient_twitter_telecom_system,
                "value": "https://twitter.com/somehandle",
            }
        )
        patient["extension"].append({"url": FHIR.twitter_extension_url, "valueBoolean": True})

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        responses.add(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            json={"operation": "Patient resource updated!"},
            status=200,
        )

        # Do the update
        updated = FHIR.update_twitter(patient["id"], handle, uses_twitter)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        # Check request
        payload = json.loads(responses.calls[1].request.body)

        # Get telecom
        telecom = next(
            (t for t in payload["telecom"] if t["system"] == FHIR.patient_twitter_telecom_system),
            None,
        )
        self.assertIsNone(telecom)

        # Get extension
        extension = next(
            (e for e in payload["extension"] if e["url"] == FHIR.twitter_extension_url),
            None,
        )
        self.assertEqual(extension["valueBoolean"], uses_twitter)

    @responses.activate
    def test_update_patient_extension_1(self):

        # Set the the extension details
        url = FHIR.facebook_extension_url
        value = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_extension(patient["id"], url, value)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get extension
        extension = next((e for e in payload["extension"] if e["url"] == url), None)
        self.assertEqual(extension["valueBoolean"], value)

    @responses.activate
    def test_update_patient_extension_2(self):

        # Set the the extension details
        url = FHIR.facebook_extension_url
        value = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set an initial handle and extension
        patient["extension"].append({"url": url, "valueBoolean": not value})

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_extension(patient["id"], url, value)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get extension
        extension = next((e for e in payload["extension"] if e["url"] == url), None)
        self.assertEqual(extension["valueBoolean"], value)

    @responses.activate
    def test_update_patient_extension_3(self):

        # Set the the extension details
        url = FHIR.facebook_extension_url
        value = "somestring"

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set an initial handle and extension
        patient["extension"].append({"url": url, "valueString": "someotherstring"})

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_extension(patient["id"], url, value)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get extension
        extension = next((e for e in payload["extension"] if e["url"] == url), None)
        self.assertEqual(extension["valueString"], value)

    @responses.activate
    def test_update_patient_picnichealth_1(self):

        # Set the the extension details
        url = FHIR.picnichealth_extension_url
        value = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_picnichealth(patient["id"], value)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get extension
        extension = next((e for e in payload["extension"] if e["url"] == url), None)
        self.assertEqual(extension["valueBoolean"], value)

    @responses.activate
    def test_update_patient_picnichealth_2(self):

        # Set the the extension details
        url = FHIR.picnichealth_extension_url
        value = True

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set an initial handle and extension
        patient["extension"].append({"url": url, "valueBoolean": not value})

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Patient resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Patient.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_picnichealth(patient["id"], value)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Get extension
        extension = next((e for e in payload["extension"] if e["url"] == url), None)
        self.assertEqual(extension["valueBoolean"], value)

    @responses.activate
    def test_update_enrollment_1(self):

        # Set the enrollment value we are setting
        enrollment = PPM.Enrollment.Consented.value

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Flag.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_enrollment(patient["id"], status=enrollment)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload["subject"]["reference"], "Patient/{}".format(patient["id"]))
        self.assertEqual(payload["code"]["coding"][0]["code"], enrollment)
        self.assertEqual(payload["code"]["text"], PPM.Enrollment.title(enrollment))
        self.assertEqual(payload["status"], "inactive")
        self.assertIsNone(payload["period"].get("end"))

    @responses.activate
    def test_update_enrollment_2(self):

        # Set the enrollment value we are setting
        enrollment = PPM.Enrollment.Proposed.value

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Flag.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_enrollment(patient["id"], status=enrollment)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload["subject"]["reference"], "Patient/{}".format(patient["id"]))
        self.assertEqual(payload["code"]["coding"][0]["code"], enrollment)
        self.assertEqual(payload["code"]["text"], PPM.Enrollment.title(enrollment))
        self.assertNotEqual(payload["status"], "active")
        self.assertIsNone(payload["period"].get("end"))

    @responses.activate
    def test_update_enrollment_3(self):

        # Set the enrollment value we are setting
        enrollment = PPM.Enrollment.Accepted.value

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Flag.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_enrollment(patient["id"], status=enrollment)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload["subject"]["reference"], "Patient/{}".format(patient["id"]))
        self.assertEqual(payload["code"]["coding"][0]["code"], enrollment)
        self.assertEqual(payload["code"]["text"], PPM.Enrollment.title(enrollment))
        self.assertEqual(payload["status"], "active")
        self.assertIsNotNone(payload["period"].get("start"))
        self.assertIsNone(payload["period"].get("end"))

    @responses.activate
    def test_update_enrollment_4(self):

        # Set the enrollment value we are setting
        enrollment = PPM.Enrollment.Terminated.value

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Flag.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_enrollment(patient["id"], status=enrollment)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload["subject"]["reference"], "Patient/{}".format(patient["id"]))
        self.assertEqual(payload["code"]["coding"][0]["code"], enrollment)
        self.assertEqual(payload["code"]["text"], PPM.Enrollment.title(enrollment))
        self.assertEqual(payload["status"], "inactive")
        self.assertIsNotNone(payload["period"].get("start"))
        self.assertIsNotNone(payload["period"].get("end"))

    @responses.activate
    def test_update_enrollment_5(self):

        # Set the enrollment value we are setting
        enrollment = PPM.Enrollment.Completed.value

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Flag.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PUT,
            re.compile(self.fhir_url + r"/Flag.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_patient_enrollment(patient["id"], status=enrollment)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload["subject"]["reference"], "Patient/{}".format(patient["id"]))
        self.assertEqual(payload["code"]["coding"][0]["code"], enrollment)
        self.assertEqual(payload["code"]["text"], PPM.Enrollment.title(enrollment))
        self.assertEqual(payload["status"], "inactive")
        self.assertIsNotNone(payload["period"].get("start"))
        self.assertIsNotNone(payload["period"].get("end"))

    @responses.activate
    def test_update_research_subject_1(self):

        # Set the dates
        end = datetime.now(timezone.utc)

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "ResearchSubject resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_research_subject(research_subject["id"], end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "add")
        self.assertEqual(payload[0]["value"], end.isoformat())

    @responses.activate
    def test_update_research_subject_2(self):

        # Set the dates
        end = None

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_research_subject(research_subject["id"], end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload, [])

    @responses.activate
    def test_update_research_subject_3(self):

        # Set the dates
        end = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set a date on research subject otherwise it won't be deleted
        research_subject["period"] = {
            "start": datetime.now(timezone.utc).isoformat(),
            "end": datetime.now(timezone.utc).isoformat(),
        }

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_research_subject(research_subject["id"], end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[0].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "remove")

    @responses.activate
    def test_update_ppm_research_subject_1(self):

        # Set the dates
        end = datetime.now(timezone.utc)

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_ppm_research_subject(patient["id"], PPM.Study.NEER.value, end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload[0]["op"], "add")
        self.assertEqual(payload[0]["value"], end.isoformat())

    @responses.activate
    def test_update_ppm_research_subject_2(self):

        # Set the dates
        end = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=FHIRData.create_bundle([flag], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Flag resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_ppm_research_subject(patient["id"], PPM.Study.NEER.value, end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        self.assertEqual(payload, [])

    @responses.activate
    def test_update_ppm_research_subject_3(self):

        # Set the dates
        end = False

        # Start a data set
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Set a date on research subject otherwise it won't be deleted
        research_subject["period"] = {
            "start": datetime.now(timezone.utc).isoformat(),
            "end": datetime.now(timezone.utc).isoformat(),
        }

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            json=FHIRData.create_bundle([research_subject], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "ResearchSubject resource updated!"})

        responses.add_callback(
            responses.PATCH,
            re.compile(self.fhir_url + r"/ResearchSubject.*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        updated = FHIR.update_ppm_research_subject(patient["id"], PPM.Study.NEER.value, end=end)

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)
        self.assertTrue(updated)

        payload = json.loads(responses.calls[1].request.body)

        # Ensure properties still exist
        print(payload)
        self.assertEqual(payload[0]["op"], "remove")

    @responses.activate
    def test_delete_participant(self):

        # Create our participant to be deleted
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        # Collect IDs
        resource_ids = [
            "Patient/" + patient["id"],
            "Flag/" + flag["id"],
            "ResearchSubject/" + research_subject["id"],
        ]

        # Build the response handler
        responses.add(
            responses.GET,
            re.compile(self.fhir_url + r"/Patient.*"),
            json=FHIRData.create_bundle([patient, flag, research_subject, research_study], self.fhir_url),
            status=200,
        )

        def update_callback(request):

            return 200, {}, json.dumps({"operation": "Resources were deleted!"})

        responses.add_callback(
            responses.POST,
            re.compile(self.fhir_url + r".*"),
            callback=update_callback,
            content_type="application/json",
        )

        # Do the update
        FHIR.delete_participant(patient["id"], research_study["id"])

        # Check it
        self.assertGreaterEqual(len(responses.calls), 2)

        # Check each transaction request
        payload = json.loads(responses.calls[1].request.body)
        for request in [e["request"] for e in payload["entry"]]:

            # Ensure it only relates to our single participant
            self.assertIn(request["url"], resource_ids)
            self.assertEqual(request["method"], "DELETE")

            # Ensure the PPM ResearchStudy was unharmed
            self.assertNotEqual(request["url"], "ResearchStudy/" + research_study["id"])

    @responses.activate
    def test_delete_patient(self):

        # Create our participant to be deleted
        research_study, patient, flag, research_subject = FHIRData.participant(PPM.Study.NEER)

        def delete_callback(request):

            return 200, {}, json.dumps({"operation": "Resource was deleted!"})

        responses.add_callback(
            responses.DELETE,
            re.compile(self.fhir_url + r".*"),
            callback=delete_callback,
            content_type="application/json",
        )

        # Do the update
        FHIR.fhir_delete_resource("Patient", patient["id"])

        # Check it
        self.assertGreaterEqual(len(responses.calls), 1)

        # Check each transaction request
        self.assertIn("Patient/" + patient["id"], responses.calls[0].request.url)


class FHIRData(object):
    """This class is used to manage the emulated data set from which to test
    PPM FHIR methods"""

    bundle = None
    fhir_url = None

    def __init__(self, fhir_url, participants=1, study=None, enrollment=None):

        # Retain
        self.fhir_url = fhir_url

        # Create participants and create our bundle
        for _ in range(0, participants):

            # If not study, randomize it
            if not study:
                _study = PPM.Study(
                    list(dict(PPM.Study.choices()).keys())[random.randint(1, len(PPM.Study.choices())) - 1]
                )
            else:
                _study = study

            # If not enrollment, randomize it
            if not enrollment:
                _enrollment = PPM.Enrollment(
                    list(dict(PPM.Enrollment.choices()).keys())[random.randint(1, len(PPM.Enrollment.choices())) - 1]
                )
                print(_enrollment.value)
            else:
                _enrollment = enrollment

            # Create the resources
            (
                research_study,
                patient,
                flag,
                research_subject,
            ) = FHIRData.participant(study=_study, enrollment=_enrollment)

            # Add the study if not already there
            if not self.bundle:

                # Start it
                self.bundle = FHIRData.create_bundle([research_study], fhir_url)

            elif not next((r for r in self.bundle["entry"] if r["resource"]["id"] == research_study["id"]), None):

                # Add it
                self.bundle["entry"].extend(FHIRData.create_bundle([research_study], fhir_url)["entry"])

            # Add remaining resources
            self.bundle["entry"].extend(FHIRData.create_bundle([patient, flag, research_subject], fhir_url)["entry"])

    def add_participant(self, patient, enrollment, research_subject, research_study):
        """
        Adds the participant comprised of the needed resources to the Bundle resource.
        :param patient: The Patient
        :param enrollment: The enrollment Flag
        :param research_subject: The ResearchSubject
        :param research_study: The ResearchStudy
        :return: None
        """
        # Add the study if not already there
        if not self.bundle:

            # Start it
            self.bundle = FHIRData.create_bundle([research_study], self.fhir_url)

        elif not next(
            (r for r in self.bundle["entry"] if r["resource"]["id"] == research_study["id"]),
            None,
        ):

            # Add it
            self.bundle["entry"].extend(FHIRData.create_bundle([research_study], self.fhir_url)["entry"])

        # Add remaining resources
        self.bundle["entry"].extend(
            FHIRData.create_bundle([patient, enrollment, research_subject], self.fhir_url)["entry"]
        )

    @staticmethod
    def participant(study, enrollment=PPM.Enrollment.Registered):
        """
        Builds and returns a bundle comprised of n participant resource sets.
        This includes Patient, Flag, ResearchSubject and ResearchStudy and others,
        if requested.
        :param study: The study the participant should belong to
        :param enrollment: The enrollment status they should be set to
        :return: A tuple of FHIR resource dicts
        """
        # Make a random ID
        ppm_id = f"{random.randint(1000, 99999)}"

        # Set patient email
        email = f"patient-{ppm_id}-{PPM.Study.enum(study).value}@email.org"

        # Build a patient with a lastname
        patient = FHIRData.patient(
            email,
            firstname=f"User {ppm_id}",
            lastname="Patient",
            street1=f"{random.randint(1000, 9999)} Main St.",
            street2="Unit 500",
            city="Boston",
            state="Massachusetts",
            zip=f"{random.randint(2000, 20000)}",
            contact_email=f"patient-{ppm_id}-{PPM.Study.enum(study).value}@email.org",
        )
        research_study = FHIRData.research_study(study)
        research_subject = FHIRData.research_subject("Patient/{}".format(patient["id"]), study)
        enrollment_flag = FHIRData.enrollment_flag("Patient/{}".format(patient["id"]), study, enrollment.value)

        return research_study, patient, enrollment_flag, research_subject

    @staticmethod
    def create_bundle(resources, fhir_url):
        """
        Builds and returns a JSON Bundle resource containing the passed JSON
        FHIR resources
        :param resources: A list of FHIR resource dicts
        :return: dict
        """
        return {
            "resourceType": "Bundle",
            "id": f"{uuid.uuid4()}",
            "meta": {"lastUpdated": datetime.now(timezone.utc).isoformat()},
            "type": "searchset",
            "total": len(resources),
            "link": [{"relation": "self", "url": fhir_url}],
            "entry": [
                {
                    "resource": resource,
                    "fullUrl": f'{fhir_url}/{resource["resourceType"]}/' f'{resource["id"]}',
                }
                for resource in resources
            ],
        }

    @staticmethod
    def patient(
        email,
        firstname,
        lastname=None,
        street1="49 West New Drive",
        street2=None,
        city="Boston",
        state="MA",
        zip="02445",
        phone="+1 (353) 233-2708",
        contact_email="user@email.org",
        twitter=None,
        identifier=str(uuid.uuid4()),
    ):
        """
        Initializes and returns a test Patient resource using the passed parameters.
        Required items not passed are randomly generated, non-required items are
        left blank.
        :return: The Patient FHIR resource as a dict
        :rtype: dict
        """
        # Convert to form
        form = {
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "street_address1": street1,
            "street_address2": street2,
            "city": city,
            "state": state,
            "zip": zip,
            "phone": phone,
            "contact_email": contact_email,
            "how_did_you_hear_about_us": "Example of how they heard about PPM",
            "twitter_handle": twitter,
        }

        # Get from FHIR.Resource
        data = FHIR.Resources.patient(
            email=form["email"],
            first_name=form["firstname"],
            last_name=form["lastname"],
            addresses=[form["street_address1"], form["street_address2"]],
            city=form["city"],
            state=form["state"],
            zip=form["zip"],
            phone=form["phone"],
            contact_email=form["contact_email"],
            how_heard_about_ppm=form["how_did_you_hear_about_us"],
        )

        # Replace/set some additional data
        data["id"] = f"{random.randint(1000, 99999)}"
        data["identifier"].append(
            {
                "system": "https://peoplepoweredmedicine.org/fhir/patient",
                "value": identifier,
            }
        )

        # Toggle Twitter usage
        data["extension"].append(
            {
                "url": "https://p2m2.dbmi.hms.harvard.edu/fhir/" "StructureDefinition/uses-twitter",
                "valueBoolean": twitter is not None,
            }
        )

        return data

    @staticmethod
    def research_study(study):
        """
        Initializes and returns a test ResearchSubject resource using the passed
        parameters. Required items not passed are randomly generated, non-required
        items are left blank.
        :return: The ResearchSubject FHIR resource as a dict
        :rtype: dict
        """
        # Ensure we pass a study value
        study = PPM.Study.enum(study).value

        # Build initial object
        data = FHIR.Resources.research_study(
            title=PPM.Study.title(study),
            ppm_study=study,
        )

        return data

    @staticmethod
    def research_subject(patient, study, start=None, end=None):
        """
        Initializes and returns a test ResearchSubject resource using the passed
        parameters. Required items not passed are randomly generated,
        non-required items are left blank.
        :return: The ResearchSubject FHIR resource as a dict
        :rtype: dict
        """
        # Ensure we pass a study value
        study = PPM.Study.enum(study).value

        # Build initial object
        data = FHIR.Resources.research_subject(patient, f"ResearchStudy/{PPM.Study.fhir_id(study)}")

        # Set random id
        data["id"] = f"{random.randint(1000, 99999)}"

        # Check dates
        if start:
            data["period"]["start"] = start

        if end:
            data["period"]["end"] = end

        return data

    @staticmethod
    def enrollment_flag(
        patient,
        study,
        enrollment=PPM.Enrollment.Registered.value,
        start=datetime.now(timezone.utc),
        end=None,
    ):
        """
        Initializes and returns a test ResearchSubject resource using the
        passed parameters. Required items not passed are randomly generated,
        non-required items are left blank.
        :return: The ResearchSubject FHIR resource as a dict
        :rtype: dict
        """
        # Build initial object
        data = FHIR.Resources.enrollment_flag(
            patient, PPM.Study.fhir_id(study), status=enrollment, start=start, end=end
        )

        # Set random id
        data["id"] = f"{random.randint(1000, 99999)}"

        return data
