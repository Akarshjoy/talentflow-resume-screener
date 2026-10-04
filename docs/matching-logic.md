# NLP matching logic

## What is ML, and what is a rule?

Textract recognizes text in PDF resumes. Comprehend's built-in named entity recognition finds PERSON, ORGANIZATION and DATE mentions. A separately trained custom recognizer detects SKILL and JOB_TITLE. Built-in TITLE is deliberately not interpreted as a job role. Email detection and experience-range calculation are deterministic application helpers.

Custom extraction is learned named entity recognition, not an enumeration of keywords at inference time. A small alias map normalizes **already extracted** entities (for example AWS to Amazon Web Services); it is not a replacement extractor. The scoring function is an explicit rule over these entities, not a model predicting future job performance.

## Review the job first

The custom model cannot reliably distinguish required from desirable skills just because it recognized both. A recruiter reads the source JD and confirms required_skills, acceptable_titles, minimum_years and threshold. Requirements become immutable for this job; create another job for a revised rubric. The job's title entered on creation is a display label, not automatically a required role.

## Formula

- Skills points = 50 × distinct matched required skills / distinct required skills.
- Title points = 30 if any normalized candidate job title matches an explicitly acceptable title; otherwise 0.
- Experience points = 20 × min(candidate years / required years, 1).
- If required years is zero, the experience component is 20.
- Total = the three components, on a 0–100 scale.

A nonzero experience requirement with unknown candidate experience yields **no total score**, not a fabricated zero. Other extraction warnings make the record unrankable and suppress the recommendation even when component points can be computed. Every candidate remains visible for review. Exactly matching normalized titles is a transparent baseline: it does not claim embedding-based semantic equivalence.

Example: 3 of 4 skills (37.5 points), an accepted title (30), and 2 of the required 4 years (10) produce 77.5. At threshold 70 a complete reviewed/extracted record can be recommended. The recommendation never makes the final shortlist decision.

## Evidence and confidence

Only entities at confidence >= 0.8 populate extracted skill/title lists. Full returned entity JSON with confidence and offsets is retained in S3; original parsed values remain in the candidate record after corrections. Low-confidence OCR, ambiguous names/contact information, and missing skills/titles/experience cause review flags. Confidence is the extraction model's belief about an entity, not the candidate's competence and not a calibrated probability of successful employment.

Organization mentions may be universities, customers, employers, or project sponsors. The recruiter confirms the employers field separately; organization prestige does not influence the score. Date mentions can refer to education or other events. The deterministic experience helper uses only explicit English month/year ranges in a recognized Experience section, merges overlapping intervals, and rejects future ranges. It uses inclusive calendar months and is approximate; unsupported formats remain unknown. Recruiters must verify relevance and years against the actual resume. Years of experience can still create undesirable indirect effects; assess the rubric and keep requirements job-related.

## Auditable decisions

Candidate corrections record actor, timestamp, note, revision, before/after fields and keep the original extraction. A final decision transaction checks the revision/current status and writes the decision audit event; shortlisting also creates one durable email intent. A repeated same decision does not create another intent. Names, email addresses and protected/sensitive characteristics do not enter the score. Human review is required before either shortlist or rejection.

## Three enhancement ideas

1. **Improve and evaluate custom extraction.** Build consented, carefully annotated data across layouts, career stages and job families; evaluate exact-span precision/recall/F1 and group-specific error patterns on a genuinely independent test set. Document gaps and test OCR errors. Synthetic metrics alone are not enough.
2. **Add a reviewed skill/title taxonomy or evaluated semantic matching.** Capture recruiter-approved related skills and roles, show the reason for partial credit, and compare against the current exact-normalization baseline. Retain rubric/model versions and evaluate false matches before enabling it.
3. **Integrate interview scheduling and delivery tracking.** Let recruiters choose real available slots through a calendar integration. Track SES delivery/bounce events, implement a stronger notification recovery process, and provide deletion/retention controls for applicant data.

Cover-letter sentiment is deliberately not used as an employability signal: positive wording does not establish job qualifications and can penalize language/cultural differences.
