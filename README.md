# Community Waste Reporting App

<img width="1531" height="748" alt="image" src="https://github.com/user-attachments/assets/0a6f71a3-e2d2-46fa-a233-21927e971825" />

<img width="1441" height="644" alt="architecture" src="https://github.com/user-attachments/assets/5198923f-3124-417e-963e-fd82e2d2f113" />



A serverless app where residents report illegal dumping, overflowing bins and missed collections, with a
public dashboard and an admin-only way to mark reports in progress or resolved. This was started with an AWS Architecture Advisor’s starter kit and then extended

**Stack:** S3 + CloudFront (website) · API Gateway HTTP API + 2 Lambda functions (arm64, Python 3.13) ·
DynamoDB on-demand with two indexes and TTL · CloudFormation (everything as code) · optional Route 53 + ACM custom domain.


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





- Anyone can submit reports, so a determined person could spam them. API throttling caps the damage; add a CAPTCHA or Cognito for real use.
- The admin key is a shared secret held in a Lambda environment variable. Cognito (or at least Secrets Manager) is the proper upgrade.
- CORS allows any origin. Restrict it to your site's address once you have a final domain.
