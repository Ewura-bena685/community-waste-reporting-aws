# Community Waste Reporting App

A serverless app where residents report illegal dumping, overflowing bins and missed collections, with a
public dashboard and an admin-only way to mark reports in progress or resolved.

**Stack:** S3 + CloudFront (website) · API Gateway HTTP API + 2 Lambda functions (arm64, Python 3.13) ·
DynamoDB on-demand with two indexes and TTL · CloudFormation (everything as code) · optional Route 53 + ACM custom domain.

> New to AWS? Start with **[docs/GUIDE.md](docs/GUIDE.md)**. It walks through setup, deployment, testing,
> how the code works, and how to explain the design (including its sustainability benefits) in an interview.

## Quick start

You need Python 3.12+, the AWS CLI v2, AWS credentials (`aws configure` or `aws sso login`) and bash
(on Windows use Git Bash).

```bash
bash scripts/check.sh        # lint, type-check, tests, template check (optional but recommended)
bash scripts/deploy.sh       # build, deploy the stack, upload the website
bash scripts/smoke-test.sh   # call the real API and website to confirm it all works
bash scripts/destroy.sh      # remove everything when you're done
```

`deploy.sh` prints your website and API addresses. Choose a name and region with
`STACK_NAME=my-app AWS_REGION=eu-west-1 bash scripts/deploy.sh` (pass the same values to the other scripts).

## API

| Route | Who | Does |
|---|---|---|
| `POST /reports` | anyone | Validate and save a report (`area`, `category`, `description`; each at most 500 characters) |
| `GET /reports?area=downtown&status=open&limit=50` | anyone | Newest-first list. With `area`: that area (optional `status`). Without: by `status` (default `open`) |
| `GET /reports/{reportId}` | anyone | One report |
| `PATCH /reports/{reportId}/status` | admin | Body `{"status":"in-progress"}` or `{"status":"resolved"}`; needs the `x-admin-key` header |

Categories: `illegal-dumping`, `overflowing-bin`, `missed-collection`, `littering`, `recycling-contamination`, `hazardous-waste`, `e-waste`, `other`. Reports are deleted automatically
90 days after creation (the clock restarts when a report is resolved).

## What's here

| Path | What |
|---|---|
| `frontend/index.html` | The website: report form, dashboard, admin buttons (plain HTML + `fetch()`) |
| `functions/submit-report-fn/` | Lambda for `POST /reports` and the admin `PATCH`, with tests |
| `functions/get-reports-fn/` | Read-only Lambda for the two `GET` routes, with tests |
| `infrastructure/template.yaml` | CloudFormation template: every AWS resource |
| `scripts/` | `check.sh`, `deploy.sh`, `smoke-test.sh`, `destroy.sh`, `build.py` |
| `docs/GUIDE.md` | Beginner's guide |
| `ARCHITECTURE.md`, `architecture.drawio` | The design, its cost estimate, and an editable diagram (open in diagrams.net) |

## Known limits (deliberate, for a starter project)

- Anyone can submit reports, so a determined person could spam them. API throttling caps the damage; add a CAPTCHA or Cognito for real use.
- The admin key is a shared secret held in a Lambda environment variable. Cognito (or at least Secrets Manager) is the proper upgrade.
- CORS allows any origin. Restrict it to your site's address once you have a final domain.
