# PPM-Utils

PPM-Utils is a library containing common functionality amongst the various
services and applications making up the People-Powered Medicine
infrastructure. In general, functionality is split into three primary
groups: FHIR, P2MD and PPM.

### FHIR

The FHIR module is a collection of methods designed for facilitating
access to and the management of data in FHIR. From methods that
create/read/update/destroy resources to methods that process and
simplify FHIR resources for easier management.

### P2MD
These are merely methods that wrap the various requests that can be
made to the P2MD API. Checking source auths, fetching data retrieval
operations, and fetching data itself are a couple examples of the
methods found here.

### PPM
The PPM class is more a source of metadata for the PPM project. It
provides the studies, enrollment statuses, devices and any other
data that is needed amongst all services and is set by study
protocol/design.

##### PPM.Service
This is a class designed to be subclassed for the building of an API
set wrapper. It has built-in methods for making any RESTful request
and handles error reporting and logging for convenience. It also
manages building authentication/authorization headers as most PPM
services follow a common JWT and/or Token auth practice.