# Deliverable capture guide

## Recording sequence

1. Show the TalentFlow login and use the recruiter account. Do not show passwords or tokens.
2. Show custom recognizer status TRAINED and the evaluation metadata, identifying synthetic training data honestly.
3. Create a Cloud Engineer job, upload the sample JD, and show parsing state. Pause the recording during long AWS processing; label elapsed-time cuts.
4. Review the JD requirements and freeze the rubric.
5. Upload the experienced PDF, graduate DOCX, and career-change DOCX. Explain the PDF Textract branch and DOCX text branch.
6. Show a completed Textract job/output for the PDF and actual custom Comprehend output for all three resumes.
7. Show the candidate list, extracted tags, review flags, and score breakdown. Explain the 50/30/20 formula. Uncertain extraction is not scored as lack of skill.
8. Open original resume and evidence. Verify candidate information. For the graduate, deliberately confirm zero professional experience if supported; it should not be silently inferred from a missing section.
9. Replace example.test email with a verified inbox you control. Save review, enter scheduling details/timezone/reason, confirm sending, and shortlist.
10. Show invitation state SENT and the received SES email. SENT means accepted by SES, not an assertion of inbox delivery by itself.
11. Download and open the shortlist CSV.
12. Demonstrate a failed input/retry and show the failed_jobs record if needed for reliability evidence.

## Three extraction outputs

Use document IDs displayed in database/source records with `scripts/capture_evidence.py`. Each downloaded JSON contains built-in entities, custom entities, confidence/offset information, structured fields, and source version. The three resume categories are experienced technical, fresh graduate, and career change. If the model misses a skill, retain that true output and explain it; do not edit it to pretend the model was perfect.

## Submission bundle

- Repository source and README.
- Recorded journey (or a link you publish yourself).
- Three actual extraction JSON files with sensitive details redacted where necessary.
- Dashboard screenshots showing tags, scores, review flags, and decisions.
- Matching explanation (`matching-logic.md`) and enhancement ideas.
- Schema, test results, and a live-validation checklist.

This project uses event-driven states rather than Step Functions; do not claim a Step Functions execution screenshot for this implementation. Capture Textract/Comprehend job history, queue processing, and document-state evidence instead.
