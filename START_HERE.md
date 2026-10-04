# Start here — TalentFlow

This is your separate AI resume screening project. Do not replace your DayOne or Smart Leave folders.

1. Extract the ZIP and open the inner `talentflow` folder in VS Code.
2. Open `README.md`. Follow its numbered sections in order, using a PowerShell terminal.
3. Install development dependencies, run the tests, validate and build the template.
4. Prepare the separate deployment permissions and verified SES email identity.
5. Deploy stack `talentflow`, configure/publish the portal, and create a recruiter.
6. Train and activate the included demonstration custom entity recognizer. Training is a separate, billable AWS step; there is no ready-trained model hidden in the ZIP.
7. Follow `docs/demo-guide.md` to process the samples and capture your deliverables.

The application code, AWS template, setup scripts, training data, sample files, tests, and documentation are included. Real AWS execution screenshots and extraction evidence must come from your own deployment.

First commands (from the inner project folder):

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python scripts/build_template.py
sam validate --lint --template-file template.json --profile my-account --region us-east-1
sam build --template-file template.json
```

If Python opens the Microsoft Store, see the PATH fix in README section 1. Stop at any error and keep the full error text for troubleshooting.
