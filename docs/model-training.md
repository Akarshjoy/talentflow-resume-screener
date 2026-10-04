# Custom entity training and evaluation

## Included dataset

`make_training.py` produces 300 train and 100 test documents, all plainly labeled synthetic. Each document contains five SKILL spans and one JOB_TITLE span. Separate text files and annotation CSVs are uploaded. The CSV header is `File,Line,Begin Offset,End Offset,Type`; offsets are zero-based, end-exclusive, and generated from the exact text. Each line is a document (`ONE_DOC_PER_LINE`). Training records are under 5 KB. Tests validate offsets and the nonoverlap of the two corpora.

Train/test use different sentence templates, but vocabulary and synthetic generation are related. Good scores on these artificial examples can seriously overstate real-world generalization. They demonstrate the mechanics of custom training, not production quality. The sample PDF/DOCX resumes are not included in training.

## AWS sequence

1. Deploy infrastructure and get DataBucket / NlpDataRoleArn.
2. Inspect/edit the dataset as needed; retain an independent holdout.
3. `python scripts/train.py --profile my-account --region us-east-1 --stack talentflow start` uploads data and calls CreateEntityRecognizer with explicit training/test annotations.
4. Save the ARN, then use the status subcommand or Comprehend console to follow TRAINING / TRAINED / IN_ERROR status and error messages.
5. Inspect RecognizerMetadata evaluation metrics and per-entity metrics. Do not equate entity confidence with model accuracy.
6. Activate only for the fictional-data demo with `activate --model-arn ARN --accept-demo-model`.
7. Process the 3 independent sample resumes, manually compare actual extraction, and capture evidence with the provided script.

No always-on real-time endpoint is created. Each incoming document uses StartEntitiesDetectionJob with the trained EntityRecognizerArn. Poll reads its real completion output archive and combines it with built-in DetectEntities results. Failure or missing model never switches to pretend ML output.

## Evaluate beyond the demo

Manually annotate at least an independent, diverse review set before assessing real quality. For each entity type report true positives, false positives and false negatives under a stated exact-span or normalized-match policy. Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = harmonic mean. Also test parsing failures, unknown dates, names in references, optional JD skills, and multi-column PDFs. Evaluate the entire extraction-plus-review experience, not only model metrics.

Recruiter corrections should have explicit consent/retention handling before becoming training data. Do not automatically feed private applicant data into future training. Freeze model/rubric versions for reproducible comparisons.

## Authoritative references

- [Custom entity recognition](https://docs.aws.amazon.com/comprehend/latest/dg/custom-entity-recognition.html)
- [Plain-text annotations](https://docs.aws.amazon.com/comprehend/latest/dg/cer-annotation.html)
- [Current custom-model quotas](https://docs.aws.amazon.com/comprehend/latest/dg/guidelines-and-limits.html)
- [Training input configuration](https://docs.aws.amazon.com/comprehend/latest/APIReference/API_EntityRecognizerInputDataConfig.html)
- [Textract async operations](https://docs.aws.amazon.com/textract/latest/dg/api-async.html)
- [Textract document limits](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html)
- [Comprehend entity types](https://docs.aws.amazon.com/comprehend/latest/dg/how-entities.html)
