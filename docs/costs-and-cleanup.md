# Cost drivers and cleanup

Deployment, model training, OCR, inference, retained storage, and logs can be billable. Do not assume your account's free-tier credits cover the project. Check current prices in us-east-1 and use AWS Pricing Calculator for your expected activity.

- Comprehend: custom recognizer training, custom batch inference, built-in entity detection, and model storage where applicable. This design does not create a continuously provisioned real-time endpoint.
- Textract: pages processed for PDFs, including rejected long documents if validation happens after OCR.
- Lambda/EventBridge: periodic polling/mailer invocations as well as work-triggered invocations.
- S3/DynamoDB: originals, versions, extracted evidence, job outputs, indexes, and backups.
- SQS, API Gateway, CloudFront, Cognito, SES, SNS and CloudWatch: activity, delivery, telemetry and selected features.

Estimate training separately from steady-state use. Count the JD as a document as well as every resume. Retrying failed jobs can add inference cost. Increasing dataset size or starting multiple training jobs can materially change the bill.

Official pricing: https://aws.amazon.com/comprehend/pricing/ and https://aws.amazon.com/textract/pricing/ . Prices vary and are intentionally not hardcoded in the application.

For cleanup, stop active learning jobs, then use SAM delete on **talentflow only**. Retained tables, buckets, user pool and models created by scripts are not automatically deleted with the stack. Review their names and data before deleting them. Delete object versions/delete markers when intentionally emptying the data bucket. Do not touch the earlier DayOne/LeaveFlow stacks. A recreated stack may encounter retained named resources; plan reuse/import or deliberate deletion rather than repeatedly creating replacements.
