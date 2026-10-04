# Reliability and edge-case report

## Processing model

S3 uploads reach a Standard SQS parsing queue. Intake pins the accepted object version and starts async OCR for PDF, or extracts DOCX text. Scheduled Poll advances durable document states, starts custom entity jobs, reads results, and queues scoring. Scoring creates a candidate item conditionally. Queue workers return partial-batch failure identifiers, and failed messages reach a DLQ after four receives. A DLQ consumer writes FailedJobs and marks the document failed; async service failures are written directly by Poll.

Transitions compare the state they observed to avoid stale workers reopening completed documents. Textract and custom-job client tokens incorporate document/version or model/attempt information. Duplicates can cause repeated reads/inference calls in crash windows; conditional candidate insertion preserves existing recruiter decisions. Every failed stage must be repaired before retrying; the dashboard retry reparses the pinned source with a new attempt number. It can incur new OCR/ML charges. Failure records remain as history even after a successful retry.

## Cases and expected behavior

| Case | Expected behavior |
|---|---|
| Missing custom model | Upload blocked with configuration message; no keyword fallback |
| PDF signature mismatch | Queue retry then failed-job record |
| Encrypted/unsupported PDF | Textract failure -> FailedJobs, no fake candidate score |
| DOCX zip expansion too large or unsafe XML declaration | Validation rejects |
| Image-only DOCX | No text -> failure; convert to PDF for OCR |
| Repeated upload event | Accepted S3 version remains pinned; transitions are conditional |
| Interrupted upload | Resume upload with a renewed form for the same document |
| Resume completes before JD review | PARSED_RESUME waits until the job is READY |
| Unknown experience dates | No total score for nonzero experience requirement; human review required |
| Low-confidence skill/title | Excluded from entity list; missing extraction gets a warning |
| Overlapping employment dates | Union of month intervals, not a sum of overlapping jobs |
| Concurrent/repeated final decisions | Conditional transaction; one invitation intent |
| Repeated scoring message after decision | Existing candidate decision/corrections preserved |
| Missing recipient or unconfirmed send | Shortlist action blocked |
| SES failure | Outbox remains PENDING with error; later send attempts retry |
| Send succeeds, then worker crashes before marking SENT | Duplicate email possible; not exactly-once delivery |
| Custom async job does not finish | Error recorded after 24-hour app timeout; inspect AWS job before retry |
| CSV formula payload | Dangerous leading formula characters prefixed as text |
| Unauthenticated API call | Cognito authorizer rejects; preflight OPTIONS is the deliberate browser exception |

## Boundaries

All authorized recruiters see the same workspace. Non-final creation/review audit writes are separate operations from their record updates; a crash can leave a missing non-final audit event. Final decision and invitation intent are transactional with the final decision audit. This is not a tamper-proof compliance archive. Add a durable event/audit stream and controlled retention for that requirement.

Email sending is retried every minute while PENDING, with visible errors and an alarm. Resolve a persistent SES failure promptly or disable the Mailer schedule during investigation; there is no bounded email retry UI in this starter. Do not remove the outbox item to conceal the failure. The polling design is intended for small batches and needs pagination/fair scheduling changes before a large multi-tenant deployment.

No antivirus is included. Use synthetic resumes for the demo and add file scanning/quarantine and retention/deletion controls before real applicant use.
