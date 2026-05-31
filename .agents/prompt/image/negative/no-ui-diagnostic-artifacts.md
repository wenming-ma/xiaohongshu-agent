# No UI Diagnostic Artifacts

## Use When
Use as a negative guard whenever upstream research, browser automation, login,
provider diagnostics, or tooling messages might leak into image prompts.

## Constraints
- Never depict browser windows, login dialogs, QR codes, form fields, error
  cards, API dashboards, session messages, or workflow diagrams unless the user
  explicitly asks for that exact subject.
- Reject any image concept based on internal logs, model errors, research
  limitations, tool traces, or prompt scaffolding.
- Keep the image about the current user-facing content topic only.

## Prompt Template
Negative guard for `{subject}`: do not include app UI, browser screenshots,
login windows, QR codes, warning icons, arrows around phones, workflow diagrams,
research limitation cards, session text, API errors, or any internal tool
artifact. The final image must depict only the intended content subject.
