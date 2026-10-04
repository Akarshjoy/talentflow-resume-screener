# Validation record

## Checks completed before packaging

- 35 automated tests passed using pytest and Moto mocks (5.81 seconds).
- Generated CloudFormation/SAM template passed cfn-lint.
- Frontend JavaScript passed Node syntax checking.
- Synthetic training annotations were checked against their source spans; train/test documents are disjoint.
- Tests cover scoring, uncertain extraction, experience interval union, DOCX validation, authentication group checks, immutable reviewed job requirements, idempotent candidate scoring, reviewed final decisions and outbox creation, failed-job recording, stale-state protection, pinned upload versions, mocked asynchronous NLP hand-off, partial OCR rejection, and retry safety.

These are local checks, not evidence of a live AWS deployment, real model accuracy, load testing, or email delivery. Moto simulates AWS behavior and cannot prove IAM permissions or service integration in your account.

## Checks still required in your AWS account

1. Deploy the stack; confirm runtime and deployment permissions.
2. Train the custom recognizer, review its evaluation, and activate it for the synthetic demo.
3. Publish the frontend and sign in as a recruiter.
4. Process the sample JD and all three resumes. Verify actual Textract PDF output and custom Comprehend entity output.
5. Review requirements, candidate source documents, extraction, and scores.
6. Shortlist a reviewed test candidate; verify SES acceptance and actual inbox receipt separately.
7. Verify CSV export and inspect a deliberately failed upload and its FailedJobs entry.
8. Record the demo and export real extraction evidence with the supplied script.

A visual browser check could not be completed in the build environment because the browser installation failed. Check the portal layout, uploads, login/password challenge, document links, review dialog, and CSV download in your browser after publishing.
