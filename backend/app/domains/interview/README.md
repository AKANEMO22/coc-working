# Interview domain services

Interview-specific logic is grouped here so data selection and interviewer
behavior have a single home:

- `catalog.py` owns framework lookup/guidance and reference questions. CV/job
  samples are requested as sanitized metadata through the candidate facade;
  candidate repositories and profile cache are not read directly here.
- `questions.py` generates opening/follow-up questions from framework criteria,
  real CV/JD evidence, previous answers/evaluation, and the controller action.
  The source example bank is only used locally to reject copied output, never
  as a live question queue or provider-failure fallback.
- `dialogue.py` creates closing/compatibility dialogue. No model means an
  explicit generation error, not reciting a framework example.
- `guidance.py` projects competency/stage/rubric fields (not example questions)
  into the prompt and checks generated output for source/history copying.

Model failure keeps session context and a pending generation request. Retry
does not re-score the previous answer. Reconnect replays a cached generated
question. No automatic web search/crawl is part of the interview flow.

Cross-domain callers use `facade.py`; candidate records/profile cache are owned
by the candidate facade. Legacy shims and web crawler scripts are retained only
under root `tools/manual/legacy`, never imported by the production app.

API/router composition stays in `app/main.py`; this is one backend, not an
independently deployed microservice. See `../README.md` for boundary rules.
