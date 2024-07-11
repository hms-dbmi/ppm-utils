## [2.0.4](https://github.com/hms-dbmi/ppm-utils/compare/v2.0.3...v2.0.4) (2024-07-11)


### Bug Fixes

* **fhir:** Fixed setting private hosts on GCP paged URLs ([b338276](https://github.com/hms-dbmi/ppm-utils/commit/b3382761c550de7ff66d61262c58c71939cf8cfa))

## [2.0.3](https://github.com/hms-dbmi/ppm-utils/compare/v2.0.2...v2.0.3) (2024-07-11)


### Bug Fixes

* **fhir:** Resolved issue with GCP not using private URLs when returning paging URLs ([6a02233](https://github.com/hms-dbmi/ppm-utils/commit/6a02233742a867aa9074f00207bcb73404123708))

## [2.0.2](https://github.com/hms-dbmi/ppm-utils/compare/v2.0.1...v2.0.2) (2024-07-11)


### Bug Fixes

* **fhir:** Fixed identifier systems ([6028ad3](https://github.com/hms-dbmi/ppm-utils/commit/6028ad38811334d7009bf518465b93b3430eef9d))

## [2.0.1](https://github.com/hms-dbmi/ppm-utils/compare/v2.0.0...v2.0.1) (2024-06-28)


### Bug Fixes

* **fhir:** Fixed how GCP backend is selected and credentialed ([c14e673](https://github.com/hms-dbmi/ppm-utils/commit/c14e673b1322346203a443a69f3863fcb0f594fc))

# [2.0.0](https://github.com/hms-dbmi/ppm-utils/compare/v1.1.0...v2.0.0) (2024-02-28)


### Bug Fixes

* **fhir:** Fixed FHIR resource ID extraction from responses; allows specifying the FHIR ID for a Patient at creation ([00e53b8](https://github.com/hms-dbmi/ppm-utils/commit/00e53b8fbd91f6b20dcc64b319b4e070fc992fbe))
* **fhir:** Fixed some issues found in tests; fixed tests ([7be74ee](https://github.com/hms-dbmi/ppm-utils/commit/7be74eee703e8faef43498e4d015dcf53e326be2))
* **fhir:** Resolved issue when updating ResearchSubject resources ([f1d834a](https://github.com/hms-dbmi/ppm-utils/commit/f1d834a738c7fec91d1129bffdf6945fd9cb65f0))
* **fhir:** Resolved typing issues ([a12fbef](https://github.com/hms-dbmi/ppm-utils/commit/a12fbef45699e950383c0d2fd12602c8df845d51))
* **qualtrics:** Fixed date handling ([7e129bc](https://github.com/hms-dbmi/ppm-utils/commit/7e129bc120f900e0d4469e1f68fe370ec7b2a0e5))
* **qualtrics:** Set required property 'operator' on Questionnaire items with conditional presentation ([fb702ff](https://github.com/hms-dbmi/ppm-utils/commit/fb702ff5a71292a6794f3c27717e4b47b688b8eb))


### Features

* **fhir/qualtrics:** Updated for FHIR R4 ([a733b7c](https://github.com/hms-dbmi/ppm-utils/commit/a733b7c8ffaa85555c405df2b59088cc4fc725bb))


### BREAKING CHANGES

* **fhir/qualtrics:** FHIR module is incompatible with DSTU3 FHIR backends

# [1.1.0](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.1...v1.1.0) (2023-08-10)


### Features

* **fhir:** Added tracking field to TrackedItem/Device ([d186762](https://github.com/hms-dbmi/ppm-utils/commit/d186762b7e0dd7de7b31e47563fa227f17178762))

## [1.0.1](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0...v1.0.1) (2023-05-02)


### Bug Fixes

* **fhir:** Added check to ensure ID is set on QuestionnaireResponse PUT ([bcc696b](https://github.com/hms-dbmi/ppm-utils/commit/bcc696b7a65c712cada15e82af7bdd8920d91464))
* **fhir:** Fixed method naming for QuestionnaireResponse operations ([716abf1](https://github.com/hms-dbmi/ppm-utils/commit/716abf13d09c544007927582bc64177427caab5f))

# [1.0.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.15.3...v1.0.0) (2023-04-03)


* fix(p2md)!: Added required hash parameter for P2MD file uploads ([557345a](https://github.com/hms-dbmi/ppm-utils/commit/557345a1f55ae931f7891dfdc5346c54e8b10efc))


### BREAKING CHANGES

* 'hash' parameter now required for P2MD file uploads

## [0.15.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.15.2...v0.15.3) (2022-06-17)


### Bug Fixes

* **ppm:** PPM-747 - Re-added stool samples to NEER consent ([c392ac3](https://github.com/hms-dbmi/ppm-utils/commit/c392ac3d1b765adc05c1c6a1d4df569b1864810a))

## [0.15.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.15.1...v0.15.2) (2021-10-29)


### Bug Fixes

* **fhir:** PPM-733 - Added Patient extension for opting out of Procure ([22d79e6](https://github.com/hms-dbmi/ppm-utils/commit/22d79e69c8e5210066fccfa0c28692f4a0769358))

## [0.15.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.15.0...v0.15.1) (2021-10-20)


### Bug Fixes

* **fhir:** PPM-HOTFIX-102021 - Fixed a bug on QuestionnaireResponse handling ([195d53a](https://github.com/hms-dbmi/ppm-utils/commit/195d53a34145ebca7eb26c2953cc64583d4de770))

# [0.15.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.14.1...v0.15.0) (2021-10-18)


### Bug Fixes

* **fhir:** PPM-728 - Fixed updating of PPM devices ([8b3d280](https://github.com/hms-dbmi/ppm-utils/commit/8b3d280da0104271ad027e62d795f471675e25cb))


### Features

* **ppm/fhir:** PPM-728 - Added PPM query for tracked item types; refactored FHIR Device handling specific to PPM tracked items; minor auth fixes ([a9c319b](https://github.com/hms-dbmi/ppm-utils/commit/a9c319b099d3d523375abbe23667c747fe516760))

## [0.14.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.14.0...v0.14.1) (2021-09-23)


### Bug Fixes

* **fhir:** PPM-705 - Fixed incorrect method call ([623a0ad](https://github.com/hms-dbmi/ppm-utils/commit/623a0ad25a76a936e9144dd0013ca7492ab55bcd))
* **fhir:** PPM-705 - Refactored to pass all survey objects to parsing methods to allow handling of Points of Care survey/questionnaires, etc. ([78235db](https://github.com/hms-dbmi/ppm-utils/commit/78235db3c354cd64cba1b07cafd8e3145304a9e0))

# [0.14.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.13.1...v0.14.0) (2021-09-20)


### Bug Fixes

* **fhir:** PPM-722 - Fixed bug where non-required empty answers were reported as errors ([3d468d6](https://github.com/hms-dbmi/ppm-utils/commit/3d468d682ebe774b90aff52ae12e61f766405ac2))
* **qualtrics:** PPM-722 - Toned down logging on empty question responses ([4435e7f](https://github.com/hms-dbmi/ppm-utils/commit/4435e7f2fd6e99d05374c66d7ce8166dc32fb6c3))


### Features

* **qualtrics/fhir:** PPM-722 - Refactored Qualtrics handling; improved error logging; removed deprecated Qualtrics methods from FHIR and Qualtrics modules ([fa3a419](https://github.com/hms-dbmi/ppm-utils/commit/fa3a419dbd5135f7768030330ded402061c676ad))

## [0.13.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.13.0...v0.13.1) (2021-09-17)


### Bug Fixes

* **fhir:** PPM-722 - Removed unecessary processing of old EXAMPLE eligibility questionnaire ([4b3a982](https://github.com/hms-dbmi/ppm-utils/commit/4b3a982aa65f7cddfa33fc963c415dcf3073ca20))
* **qualtrics:** PPM-722 - Fixed multiple-choice answers where "None of the Above" was selected; fixed duplicate answer items being added to the same QuestionnaireResponse ([5cebbd8](https://github.com/hms-dbmi/ppm-utils/commit/5cebbd82619b67951355694cbb3ac65447da3946))
* **qualtrics:** PPM-722 - Removed broken log statements ([c15eec7](https://github.com/hms-dbmi/ppm-utils/commit/c15eec7bc58d6e6cbf7b970158457da454ee7b79))

# [0.13.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.12.1...v0.13.0) (2021-09-10)


### Bug Fixes

* **fhir:** PPM-705 - Fixed bug where empty QuestionnaireResponse resources would fail parsing ([e4c12c4](https://github.com/hms-dbmi/ppm-utils/commit/e4c12c4fab842ab63264f9c7ca165148a4af865c))
* **fhir:** PPM-705 - Pass all questionnaire IDs through to study-specific parsing methods ([3863933](https://github.com/hms-dbmi/ppm-utils/commit/38639337c1c68930d6c54a7cf33df6cc58f23d92))
* **p2md:** PPM-705 - Removed extraneous logging statement ([a777db7](https://github.com/hms-dbmi/ppm-utils/commit/a777db74f9e0b94e01a3e41037a604a836fd42a5))


### Features

* **fhir:** PPM-705 - Refactored how to pass study Survey/Questionnaires into Participant parsing ([32f12e1](https://github.com/hms-dbmi/ppm-utils/commit/32f12e1684670f43aa08ea81f596b1e646c7eaf6))

## [0.12.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.12.0...v0.12.1) (2021-09-02)


### Bug Fixes

* **ppm:** PPM-711 - Fixed EXAMPLE's questionnaire ID ([d2a6cd4](https://github.com/hms-dbmi/ppm-utils/commit/d2a6cd442a1376d973713deb7f74af1678d8616f))

# [0.12.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.11.1...v0.12.0) (2021-09-01)


### Bug Fixes

* **fhir:** PPM-711 - Added a method for updating QuestionnaireResponses ([8e541bb](https://github.com/hms-dbmi/ppm-utils/commit/8e541bb46de14ad400487aa9efa2fe92d005d9c1))
* **fhir:** PPM-711 - Fixed method bug if resource could not be found ([91e740b](https://github.com/hms-dbmi/ppm-utils/commit/91e740b391848d8be03554d3f1adffddb71b32a0))
* **fhir/p2md:** PPM-711 - Set RANT eligibility questionnaire to Qualtrics survey; made QuestionnaireResponse placeholders possible for Qualtrics surveys ([108d295](https://github.com/hms-dbmi/ppm-utils/commit/108d2951895a183f2ccd68f5d46b836f10f81ea9))


### Features

* **fhir:** PPM-711 - Added a generic create method ([b878248](https://github.com/hms-dbmi/ppm-utils/commit/b87824834433c4024062446efab20e36fcf2ec59))

## [0.11.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.11.0...v0.11.1) (2021-08-03)


### Bug Fixes

* **ppm:** PPM-709 - Undo change of RANT registration questionnaire FHIR ID ([9d27ecd](https://github.com/hms-dbmi/ppm-utils/commit/9d27ecdedb5948154fab06a5f4cfa47dfb3b93db))

# [0.11.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.10.2...v0.11.0) (2021-08-03)


### Features

* **ppm/fhir:** PPM-709 - Questionnaire processing is more dynamic; initial efforts to allow a single participant in multiple studies ([5a8b980](https://github.com/hms-dbmi/ppm-utils/commit/5a8b980be8080dd7d65fe425fbc878dd10f8252c))

## [0.10.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.10.1...v0.10.2) (2021-07-16)


### Bug Fixes

* **fhir:** PPM-707 - Improved core resource creation to avoid duplicates; improved logging of FHIR Transaction results ([5be78f2](https://github.com/hms-dbmi/ppm-utils/commit/5be78f2a483fb1df160618164d7c6e0640e1ca15))

# Changelog

<!--next-version-placeholder-->

## [0.10.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.10.0...v0.10.1) (2021-06-29)


### Bug Fixes

* **fhir:** PPM-702 - Fixed FHIR Questionnaire parsing bug ([d1febd1](https://github.com/hms-dbmi/ppm-utils/commit/d1febd18df703ea5121c0b4e48c4b8d1d7dbe79d))


## [0.10.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.13...v0.10.0) (2021-03-15)


### Bug Fixes

* **ppm:** PPM-690 - Fixed Environment queries ([aa47b61](https://github.com/hms-dbmi/ppm-utils/commit/aa47b61b0a89759439ad9583f8a839d581621baa))


### Features

* **fhir/qualtrics:** PPM-697 - Fixed handling of subquestions in Qualtrics; naming tweaks ([361251b](https://github.com/hms-dbmi/ppm-utils/commit/361251b52a707f9eb1774e2fea327d4164f0fa6d))


## [0.9.13](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.12...v0.9.13) (2021-03-03)


### Bug Fixes

* **fhir:** PPM-694 - Fixed Qualtrics survey handling when converting to Questionnaire/QuestionnaireResponse ([b7c75ed](https://github.com/hms-dbmi/ppm-utils/commit/b7c75ed0dc3e2a68b34a11043eb6a575babf1087))


## [0.9.12](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.11...v0.9.12) (2021-02-25)


### Bug Fixes

* **ppm:** Fixed reference to non-existent RANT consent questionnaire ([6edb1a4](https://github.com/hms-dbmi/ppm-utils/commit/6edb1a423613b3ca6132641e9610050259f78c12))


## [0.9.11](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.10...v0.9.11) (2021-02-16)


### Bug Fixes

* **p2md:** PPM-HOTFIX-021621 - Fixed PPM admin query method ([7aca343](https://github.com/hms-dbmi/ppm-utils/commit/7aca3436a3a9bcc056925362efeae9237367116b))


## [1.0.0-beta.6](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0-beta.5...v1.0.0-beta.6) (2021-02-13)


### Bug Fixes

* **auth:** Fixed Auth method for checking study permissions ([ec728e6](https://github.com/hms-dbmi/ppm-utils/commit/ec728e6f50682dd6bfb23245e9b5877e92440294))
* **auth:** Renamed method for clearer purpose and added a secondary method to fetch specific matching item/permission ([baa08ff](https://github.com/hms-dbmi/ppm-utils/commit/baa08ff4f6527234fad3aebf7f0400a7850a53df))
* **fhir:** PPM-638 - Fixed Qualtrics survey response handling ([c8bdc07](https://github.com/hms-dbmi/ppm-utils/commit/c8bdc07b0579ec8b0e51f6ce9c9a6517b7cca64b))
* **fhir:** PPM-671 - Parses RANT Points of Care questionnaire and places list in participant object ([652be55](https://github.com/hms-dbmi/ppm-utils/commit/652be55045ac9fb633a9210410abafb07f16a37c))
* **fhir:** PPM-683 - Fixed FHIR Composition searches ([69f6e41](https://github.com/hms-dbmi/ppm-utils/commit/69f6e41c3470ea4cb808d3e9b3f7949bee27b69a))
* **fhir:** PPM-HOTFIX - Minor Questionnaire sorting issue fixed ([34fbce2](https://github.com/hms-dbmi/ppm-utils/commit/34fbce2c89fe785943241fdf2374fec8aaa70ad0))
* **fhir/auth/ppm:** PPM-532 - Fixed study resource IDs and references; improved permission checks in Auth ([3a54d1b](https://github.com/hms-dbmi/ppm-utils/commit/3a54d1bf080e879f24d93e39be6e4f839df07a8a))
* **p2md:** PPM-686 - Added queries for PPM study state ([f60a565](https://github.com/hms-dbmi/ppm-utils/commit/f60a565dad03910a56c6858569ba022c1803f9da))
* **p2md:** PPM-686 - Fixed some query methods; added a couple more ([ff7f6d0](https://github.com/hms-dbmi/ppm-utils/commit/ff7f6d05abdfacdf74014d340a145d9b87a8d7e9))
* **ppm:** Hotfix for adding upcoming data providers and fixing RANT item specification ([4776cdb](https://github.com/hms-dbmi/ppm-utils/commit/4776cdbe2d2e6b7395877d0cbea66a8e7715e7b9))
* **ppm:** Minor reformat to push release ([39a2180](https://github.com/hms-dbmi/ppm-utils/commit/39a21806354b0405de84643d50842cb486be4f4f))
* **ppm/fhir:** PPM-665 - Fixed Qualtrics survey question ordering; fixed Qualtrics Questionnaire creation to not replace if not necessary ([2d8583c](https://github.com/hms-dbmi/ppm-utils/commit/2d8583c4e4b882c7b37b1245ada2e5104791dbf9))


### Features

* **ppm/fhir/auth:** PPM-532 - RANT Questionnaire handling improvements; added authorization support for apps; minor tweaks and fixes ([f46c7b7](https://github.com/hms-dbmi/ppm-utils/commit/f46c7b7a7ece3e1cc0423f0e08bf3b037749280a))


## [0.9.9](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.8...v0.9.9) (2021-02-10)


### Bug Fixes

* **p2md:** PPM-686 - Added queries for PPM study state ([f60a565](https://github.com/hms-dbmi/ppm-utils/commit/f60a565dad03910a56c6858569ba022c1803f9da))


## [0.9.8](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.7...v0.9.8) (2021-02-09)


### Bug Fixes

* **fhir:** PPM-683 - Fixed FHIR Composition searches ([69f6e41](https://github.com/hms-dbmi/ppm-utils/commit/69f6e41c3470ea4cb808d3e9b3f7949bee27b69a))


## [0.9.7](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.6...v0.9.7) (2021-02-08)


### Bug Fixes

* **fhir:** PPM-638 - Fixed Qualtrics survey response handling ([c8bdc07](https://github.com/hms-dbmi/ppm-utils/commit/c8bdc07b0579ec8b0e51f6ce9c9a6517b7cca64b))


## [0.9.6](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.5...v0.9.6) (2020-11-25)


### Bug Fixes

* **fhir:** PPM-671 - Parses RANT Points of Care questionnaire and places list in participant object ([652be55](https://github.com/hms-dbmi/ppm-utils/commit/652be55045ac9fb633a9210410abafb07f16a37c))
* **fhir:** PPM-HOTFIX - Minor Questionnaire sorting issue fixed ([34fbce2](https://github.com/hms-dbmi/ppm-utils/commit/34fbce2c89fe785943241fdf2374fec8aaa70ad0))


## [0.9.5](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.4...v0.9.5) (2020-11-22)


### Bug Fixes

* **ppm/fhir:** PPM-665 - Fixed Qualtrics survey question ordering; fixed Qualtrics Questionnaire creation to not replace if not necessary ([2d8583c](https://github.com/hms-dbmi/ppm-utils/commit/2d8583c4e4b882c7b37b1245ada2e5104791dbf9))


## [0.9.4](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.3...v0.9.4) (2020-11-19)

### Bug Fixes

* **ppm:** Minor reformat to push release ([39a2180](https://github.com/hms-dbmi/ppm-utils/commit/39a21806354b0405de84643d50842cb486be4f4f))


## [0.9.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.2...v0.9.3) (2020-11-03)


### Bug Fixes

* **auth:** Fixed Auth method for checking study permissions ([ec728e6](https://github.com/hms-dbmi/ppm-utils/commit/ec728e6f50682dd6bfb23245e9b5877e92440294))


## [0.9.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.1...v0.9.2) (2020-11-02)


### Bug Fixes

* **fhir/auth/ppm:** PPM-532 - Fixed study resource IDs and references; improved permission checks in Auth ([3a54d1b](https://github.com/hms-dbmi/ppm-utils/commit/3a54d1bf080e879f24d93e39be6e4f839df07a8a))


## [0.9.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.9.0...v0.9.1) (2020-10-30)


### Bug Fixes

* **auth:** Renamed method for clearer purpose and added a secondary method to fetch specific matching item/permission ([baa08ff](https://github.com/hms-dbmi/ppm-utils/commit/baa08ff4f6527234fad3aebf7f0400a7850a53df))


## [0.9.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.4...v0.9.0) (2020-10-30)


### Features

* **ppm/fhir/auth:** PPM-532 - RANT Questionnaire handling improvements; added authorization support for apps; minor tweaks and fixes ([f46c7b7](https://github.com/hms-dbmi/ppm-utils/commit/f46c7b7a7ece3e1cc0423f0e08bf3b037749280a))


## [1.0.0-beta.5](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0-beta.4...v1.0.0-beta.5) (2020-10-21)


### Bug Fixes

* **cicd:** Test fixing of version updater to use double-quotes ([17c87e6](https://github.com/hms-dbmi/ppm-utils/commit/17c87e6cede9593813acb9c1c8c30707684eb0c4))


## [1.0.0-beta.4](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0-beta.3...v1.0.0-beta.4) (2020-10-21)


### Bug Fixes

* **fhir:** PPM-658 - Fixed broken debug lines ([f87204b](https://github.com/hms-dbmi/ppm-utils/commit/f87204b51b8f65be1d62bd804714a38603639592))
* **fhir:** PPM-658 - Fixed some issues when processing QuestionnaireResponse objects ([199f4c8](https://github.com/hms-dbmi/ppm-utils/commit/199f4c8250306eb89d19842078e02d0aaa2f4fcc))
* **ppm:** Minor refactor of PPM class ([8a2a921](https://github.com/hms-dbmi/ppm-utils/commit/8a2a92160ed2446fde67daa745ad97442d986d13))
* **ppm:** PPM-660 - Removed consent exemptions for RANT ([5623795](https://github.com/hms-dbmi/ppm-utils/commit/56237956d4c97eb4f99a012dd1328e738a9a9aeb))
* **ppm,fhir:** PPM-658 - Fixed date processing in Questionnaire responses ([c44e278](https://github.com/hms-dbmi/ppm-utils/commit/c44e278190e20d1e3e0315d578008ec982003f77))


## [0.8.4](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.3...v0.8.4) (2020-10-21)


### Bug Fixes

* **ppm:** Hotfix for adding upcoming data providers and fixing RANT item specification ([4776cdb](https://github.com/hms-dbmi/ppm-utils/commit/4776cdbe2d2e6b7395877d0cbea66a8e7715e7b9))


## [0.8.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.2...v0.8.3) (2020-10-20)


### Bug Fixes

* **ppm:** PPM-660 - Removed consent exemptions for RANT ([5623795](https://github.com/hms-dbmi/ppm-utils/commit/56237956d4c97eb4f99a012dd1328e738a9a9aeb))


## [0.8.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.1...v0.8.2) (2020-10-01)


### Bug Fixes

* **fhir:** PPM-658 - Fixed broken debug lines ([f87204b](https://github.com/hms-dbmi/ppm-utils/commit/f87204b51b8f65be1d62bd804714a38603639592))
* **fhir:** PPM-658 - Fixed some issues when processing QuestionnaireResponse objects ([199f4c8](https://github.com/hms-dbmi/ppm-utils/commit/199f4c8250306eb89d19842078e02d0aaa2f4fcc))
* **ppm,fhir:** PPM-658 - Fixed date processing in Questionnaire responses ([c44e278](https://github.com/hms-dbmi/ppm-utils/commit/c44e278190e20d1e3e0315d578008ec982003f77))


## [1.0.0-beta.3](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0-beta.2...v1.0.0-beta.3) (2020-09-23)


### Bug Fixes

* **fhir:** Restored FHIR class with authenticated requests ([4bec1d2](https://github.com/hms-dbmi/ppm-utils/commit/4bec1d259b1b7de955c8730765e178cc589b0b2c))


## [1.0.0-beta.2](https://github.com/hms-dbmi/ppm-utils/compare/v1.0.0-beta.1...v1.0.0-beta.2) (2020-09-10)


### Bug Fixes

* **api:** Removed broken stub method on API library; removed unused libraries" ([f012c73](https://github.com/hms-dbmi/ppm-utils/commit/f012c730a95bd02159f5055753d9e63f02484024))
* **P2MD:** PPM-656 - Added method to return P2MD Procure URL ([70c04f7](https://github.com/hms-dbmi/ppm-utils/commit/70c04f75f7dae3846f1b0c9f9d59002cae0a8377))


### Features

* **ppm:** Includes updated PPM architecture functionality\n\nBREAKING CHANGES: Updated PPM architectrure ([f348836](https://github.com/hms-dbmi/ppm-utils/commit/f348836c691552abae4c48ab401a4254f97c33b2))
* **ppm:** PPM-655/656 - Added Procure functionality to PPM and P2MD modules ([829fd6b](https://github.com/hms-dbmi/ppm-utils/commit/829fd6b0e8feb972780baa6c34da4c64d1801366))


## [0.8.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.0...v0.8.1) (2020-09-09)


### Bug Fixes

* **P2MD:** PPM-656 - Added method to return P2MD Procure URL ([70c04f7](https://github.com/hms-dbmi/ppm-utils/commit/70c04f75f7dae3846f1b0c9f9d59002cae0a8377))


## [0.8.1-rc.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.0...v0.8.1-rc.1) (2020-09-09)


### Bug Fixes

* **P2MD:** PPM-656 - Added method to return P2MD Procure URL ([70c04f7](https://github.com/hms-dbmi/ppm-utils/commit/70c04f75f7dae3846f1b0c9f9d59002cae0a8377))


## [0.8.0-rc.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.8.0-rc.1...v0.8.0-rc.2) (2020-09-09)


### Bug Fixes

* **P2MD:** PPM-656 - Added method to return P2MD Procure URL ([4b297ec](https://github.com/hms-dbmi/ppm-utils/commit/4b297ecdce66d4e549fc64310583cfe18efaec88))


## [0.8.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0...v0.8.0) (2020-09-02)


### Features

* **ppm:** PPM-655/656 - Added Procure functionality to PPM and P2MD modules ([829fd6b](https://github.com/hms-dbmi/ppm-utils/commit/829fd6b0e8feb972780baa6c34da4c64d1801366))


## [0.8.0-rc.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0...v0.8.0-rc.1) (2020-08-26)


### Features

* **ppm:** PPM-655/656 - Added Procure functionality to PPM and P2MD modules ([829fd6b](https://github.com/hms-dbmi/ppm-utils/commit/829fd6b0e8feb972780baa6c34da4c64d1801366))


## [0.7.0](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.36...v0.7.0) (2020-08-06)


### Bug Fixes

* **automations:** Fix deployment/versioning issue; ensures correct version is set in Python package before release to Github ([2f83112](https://github.com/hms-dbmi/ppm-utils/commit/2f83112612578d8d5e6e6b96cd5c671e199c11f3))
* **automations:** Removed unecessary install from test workflow ([29a6f30](https://github.com/hms-dbmi/ppm-utils/commit/29a6f30b11c6b913d554caef45fc889b463401f7))
* **fhir:** Added datetime objects to participant objects; added updated property for enrollment updates ([15e4244](https://github.com/hms-dbmi/ppm-utils/commit/15e42449c0304bf4d38fb8f01ee417159ac58551))
* **p2md:** PPM-642 - Removed all localhost patching and set correct P2MD URL in local environments ([bb577f8](https://github.com/hms-dbmi/ppm-utils/commit/bb577f850414cecad64c2222f4e0edcbea646a1a))
* **package:** PPM-HOTFIX-072920 - Set line-length to 120; initial setup for tox; requirements refactor ([503dc84](https://github.com/hms-dbmi/ppm-utils/commit/503dc844db01732d115ae8541f445d91793cf780))
* **ppm:** Fixed recursion issue on PPMEnums; code formatting and pre-commit setup ([bf03387](https://github.com/hms-dbmi/ppm-utils/commit/bf03387f96b81f6125efadf49775c66242ea9919))


### Features

* **ppm:** PPM-647 - Added placeholder RANT specifications ([4cd5aa6](https://github.com/hms-dbmi/ppm-utils/commit/4cd5aa658f18247228d0e9778ad54e120b66565e))
* **ppm:** PPM-647 - Added RANT questionnaire/consent specifications ([d2684e4](https://github.com/hms-dbmi/ppm-utils/commit/d2684e4bd8c94b9a01b64759b4db5c0fdbff8c62))


## [0.7.0-rc.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.36...v0.7.0-rc.1) (2020-08-05)


### Bug Fixes

* **automations:** Fix deployment/versioning issue; ensures correct version is set in Python package before release to Github ([2f83112](https://github.com/hms-dbmi/ppm-utils/commit/2f83112612578d8d5e6e6b96cd5c671e199c11f3))
* **automations:** Removed unecessary install from test workflow ([29a6f30](https://github.com/hms-dbmi/ppm-utils/commit/29a6f30b11c6b913d554caef45fc889b463401f7))
* **fhir:** Added datetime objects to participant objects; added updated property for enrollment updates ([15e4244](https://github.com/hms-dbmi/ppm-utils/commit/15e42449c0304bf4d38fb8f01ee417159ac58551))
* **p2md:** PPM-642 - Removed all localhost patching and set correct P2MD URL in local environments ([bb577f8](https://github.com/hms-dbmi/ppm-utils/commit/bb577f850414cecad64c2222f4e0edcbea646a1a))
* **package:** PPM-HOTFIX-072920 - Set line-length to 120; initial setup for tox; requirements refactor ([503dc84](https://github.com/hms-dbmi/ppm-utils/commit/503dc844db01732d115ae8541f445d91793cf780))
* **ppm:** Fixed recursion issue on PPMEnums; code formatting and pre-commit setup ([bf03387](https://github.com/hms-dbmi/ppm-utils/commit/bf03387f96b81f6125efadf49775c66242ea9919))


### Features

* **ppm:** PPM-647 - Added placeholder RANT specifications ([4cd5aa6](https://github.com/hms-dbmi/ppm-utils/commit/4cd5aa658f18247228d0e9778ad54e120b66565e))
* **ppm:** PPM-647 - Added RANT questionnaire/consent specifications ([d2684e4](https://github.com/hms-dbmi/ppm-utils/commit/d2684e4bd8c94b9a01b64759b4db5c0fdbff8c62))


## [1.0.0-beta.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-beta.3...v1.0.0-beta.1) (2020-08-05)


### Bug Fixes

* **api:** Removed broken stub method on API library; removed unused libraries" ([b09b78a](https://github.com/hms-dbmi/ppm-utils/commit/b09b78acba8d2acc1bdf6aec3fbbe87263f2c94e))


### Features

* **ppm:** Includes updated PPM architecture functionality ([51aac59](https://github.com/hms-dbmi/ppm-utils/commit/51aac59dbfd90f88eab1b7af11dcc1ae502632e0))
* **ppm:** Includes updated PPM architecture functionality\n\nBREAKING CHANGES: Updated PPM architectrure ([d2e357f](https://github.com/hms-dbmi/ppm-utils/commit/d2e357fdc077e7057bb22bf3e53f858cccdbb386))


### BREAKING CHANGES

* **ppm:** PPM architecture update


## [0.7.0-beta.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-beta.2...v0.7.0-beta.3) (2020-07-29)


### Bug Fixes

* **package:** PPM-HOTFIX-072920 - Set line-length to 120; initial setup for tox; requirements refactor ([503dc84](https://github.com/hms-dbmi/ppm-utils/commit/503dc844db01732d115ae8541f445d91793cf780))


## [0.7.0-alpha.4](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-alpha.3...v0.7.0-alpha.4) (2020-07-29)


### Bug Fixes

* **package:** PPM-HOTFIX-072920 - Set line-length to 120; initial setup for tox; requirements refactor ([503dc84](https://github.com/hms-dbmi/ppm-utils/commit/503dc844db01732d115ae8541f445d91793cf780))


## [0.7.0-beta.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-beta.1...v0.7.0-beta.2) (2020-07-24)


### Bug Fixes

* **ppm:** Fixed recursion issue on PPMEnums; code formatting and pre-commit setup ([bf03387](https://github.com/hms-dbmi/ppm-utils/commit/bf03387f96b81f6125efadf49775c66242ea9919))


## [0.7.0-alpha.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-alpha.2...v0.7.0-alpha.3) (2020-07-24)


### Bug Fixes

* **ppm:** Fixed recursion issue on PPMEnums; code formatting and pre-commit setup ([bf03387](https://github.com/hms-dbmi/ppm-utils/commit/bf03387f96b81f6125efadf49775c66242ea9919))


## [0.7.0-beta.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.36...v0.7.0-beta.1) (2020-07-24)


### Bug Fixes

* **automations:** Fix deployment/versioning issue; ensures correct version is set in Python package before release to Github ([2f83112](https://github.com/hms-dbmi/ppm-utils/commit/2f83112612578d8d5e6e6b96cd5c671e199c11f3))
* **automations:** Removed unecessary install from test workflow ([29a6f30](https://github.com/hms-dbmi/ppm-utils/commit/29a6f30b11c6b913d554caef45fc889b463401f7))
* **fhir:** Added datetime objects to participant objects; added updated property for enrollment updates ([15e4244](https://github.com/hms-dbmi/ppm-utils/commit/15e42449c0304bf4d38fb8f01ee417159ac58551))
* **p2md:** PPM-642 - Removed all localhost patching and set correct P2MD URL in local environments ([bb577f8](https://github.com/hms-dbmi/ppm-utils/commit/bb577f850414cecad64c2222f4e0edcbea646a1a))


### Features

* **ppm:** PPM-647 - Added placeholder RANT specifications ([4cd5aa6](https://github.com/hms-dbmi/ppm-utils/commit/4cd5aa658f18247228d0e9778ad54e120b66565e))
* **ppm:** PPM-647 - Added RANT questionnaire/consent specifications ([d2684e4](https://github.com/hms-dbmi/ppm-utils/commit/d2684e4bd8c94b9a01b64759b4db5c0fdbff8c62))


## [0.7.0-alpha.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.7.0-alpha.1...v0.7.0-alpha.2) (2020-07-24)


### Features

* **ppm:** PPM-647 - Added RANT questionnaire/consent specifications ([d2684e4](https://github.com/hms-dbmi/ppm-utils/commit/d2684e4bd8c94b9a01b64759b4db5c0fdbff8c62))


## [0.7.0-alpha.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.37-alpha.3...v0.7.0-alpha.1) (2020-07-22)


### Features

* **ppm:** PPM-647 - Added placeholder RANT specifications ([4cd5aa6](https://github.com/hms-dbmi/ppm-utils/commit/4cd5aa658f18247228d0e9778ad54e120b66565e))


## [0.6.37-alpha.3](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.37-alpha.2...v0.6.37-alpha.3) (2020-07-21)


### Bug Fixes

* **p2md:** PPM-642 - Removed all localhost patching and set correct P2MD URL in local environments ([bb577f8](https://github.com/hms-dbmi/ppm-utils/commit/bb577f850414cecad64c2222f4e0edcbea646a1a))


## [0.6.37-alpha.2](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.37-alpha.1...v0.6.37-alpha.2) (2020-07-15)


### Bug Fixes

* **automations:** Removed unecessary install from test workflow ([29a6f30](https://github.com/hms-dbmi/ppm-utils/commit/29a6f30b11c6b913d554caef45fc889b463401f7))


## [0.6.37-alpha.1](https://github.com/hms-dbmi/ppm-utils/compare/v0.6.36...v0.6.37-alpha.1) (2020-07-15)


### Bug Fixes

* **automations:** Fix deployment/versioning issue; ensures correct version is set in Python package before release to Github ([2f83112](https://github.com/hms-dbmi/ppm-utils/commit/2f83112612578d8d5e6e6b96cd5c671e199c11f3))
* **fhir:** Added datetime objects to participant objects; added updated property for enrollment updates ([15e4244](https://github.com/hms-dbmi/ppm-utils/commit/15e42449c0304bf4d38fb8f01ee417159ac58551))
