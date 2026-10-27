# Beginner's Guide: Community Waste Reporting App

This guide assumes you are new to AWS. Work through it in order. Every command is meant to be copied and
run from the project's top folder (the one containing `README.md`).

**Contents**

1. [What you're building](#1-what-youre-building)
2. [What changed from the Advisor's starter kit](#2-what-changed-from-the-advisors-starter-kit)
3. [One-time setup](#3-one-time-setup)
4. [Check the code locally](#4-check-the-code-locally)
5. [Deploy](#5-deploy)
6. [Test it](#6-test-it)
7. [How the code works (and exercises)](#7-how-the-code-works-and-exercises)
8. [Security: what is and isn't protected](#8-security-what-is-and-isnt-protected)
9. [Optional: a custom domain with Route 53](#9-optional-a-custom-domain-with-route-53)
10. [Sustainability talking points](#10-sustainability-talking-points)
11. [Clean up and costs](#11-clean-up-and-costs)
12. [Troubleshooting](#12-troubleshooting)
13. [Turning this into a portfolio piece](#13-turning-this-into-a-portfolio-piece)

---

## 1. What you're building

```
 Browser ──► CloudFront ──► S3 bucket (private)           the website (index.html)
    │
    └──────► API Gateway (HTTP API)
                 ├─ POST  /reports                    ──► SubmitReport Lambda ──┐
                 ├─ PATCH /reports/{id}/status (admin) ─► SubmitReport Lambda ──┤  writes
                 ├─ GET   /reports                    ──► GetReports Lambda  ──┤  reads
                 └─ GET   /reports/{id}               ──► GetReports Lambda  ──┘
                                                                  │
                                                         DynamoDB table "reports"
                                                         (2 indexes, auto-delete after 90 days)
```

| Service | Its job here | Why it fits |
|---|---|---|
| **S3** | Stores `index.html` | Cheap file storage, no server |
| **CloudFront** | Serves the website over HTTPS from locations near the visitor, and keeps copies (a cache) | Faster, and fewer trips to S3 |
| **API Gateway** | The public front door for the API; passes each request to the right Lambda | Pay per request, nothing running when idle |
| **Lambda** | Runs your Python code only while a request is being handled | No server to keep switched on |
| **DynamoDB** | Stores the reports | Pay per read/write, scales to zero |
| **CloudFormation** | Describes all of the above in one file, `infrastructure/template.yaml` | Repeatable: deploy and delete in one command |
| **Route 53** *(optional)* | Points your own domain name at the site | See [section 9](#9-optional-a-custom-domain-with-route-53) |

**Two ideas worth understanding early**

- **Infrastructure as code.** You never click buttons to create resources. The template describes them and CloudFormation builds them. If you break something, you redeploy; if you are done, you delete the stack and everything vanishes.
- **A stack** is one deployed copy of a template. Ours is called `community-waste-reporting-ap`.

---

## 2. What changed from the Advisor's starter kit

The kit you downloaded described features it did not fully contain. Here is what was missing and what this version adds:

| Area | Original kit | This version |
|---|---|---|
| DynamoDB | Only a main key; no indexes; no TTL | `AreaIndex` and `StatusIndex` plus TTL on `expiresAt` |
| API routes | Two catch-all routes (`/submit-report-fn/{proxy+}`) | Four explicit routes: `POST /reports`, `GET /reports`, `GET /reports/{reportId}`, `PATCH /reports/{reportId}/status` |
| Validation | None (saved whatever was sent) | Required, non-empty, at most 500 characters, category must be from a list |
| Listing | Not implemented | `Query` on an index, newest first |
| Public delete route | Anyone could delete any report | Removed |
| IAM permissions | Both functions could read, write, delete and scan | `SubmitReport`: `PutItem` and `UpdateItem` only. `GetReports`: `GetItem` and `Query` only |
| Admin status change | Not implemented | Needs a secret `x-admin-key` header |
| Website | None, and deploy never uploaded one | `frontend/index.html`, uploaded by `deploy.sh` |
| Custom domain | Not included | Optional ACM certificate and Route 53 records |
| CDK folder, PowerShell script | Included | Removed (you are using CloudFormation; the PowerShell script was not updated, so use Git Bash on Windows) |

This covers the five tasks from the Advisor's feedback: the frontend (1), validation (2), `GET /reports/{reportId}` (3), the admin `PATCH` (4) and the custom domain (5, optional).

---

## 3. One-time setup

### 3.1 AWS account and a safe way to sign in
1. Create an AWS account if you don't have one.
2. **Do not use the root user for daily work.** In the console, open **IAM Identity Center** (recommended) or **IAM** and create a user with permission to create the resources in this stack. For a personal learning account, the `AdministratorAccess` policy is the simplest; just never share its keys or commit them to Git.
3. Turn on **MFA** for the root user and for your own user.

### 3.2 Set a budget alert (do this before deploying)
Console → **Billing and Cost Management → Budgets → Create budget → Zero spend budget** (or a monthly budget of a few dollars) with your email. This warns you if anything costs money unexpectedly.

### 3.3 Install the tools

| Tool | Check it works | Install |
|---|---|---|
| Python 3.12 or newer | `python3 --version` (on Windows try `python --version`) | python.org |
| AWS CLI v2 | `aws --version` | docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html |
| bash | macOS and Linux already have it. **Windows: install Git for Windows and use "Git Bash"** | git-scm.com |

### 3.4 Connect the CLI to your account
```bash
aws configure          # enter your access key, secret key, default region, and output format "json"
# or, with IAM Identity Center:  aws configure sso   then   aws sso login
aws sts get-caller-identity
```
The last command must print your account ID. If it errors, the CLI isn't connected yet.

### 3.5 Choose a region
The region is where your API, Lambda and database live. `us-east-1` is the default and is **required if you add a custom domain** (section 9). Pick one on purpose and be ready to say why; regions differ in price, in distance from your users, and in the energy mix of the local grid.

### 3.6 If you already deployed the original kit
Delete it first, because DynamoDB only allows one new index per update, so upgrading that table in place would fail:

```bash
bash scripts/destroy.sh     # type the stack name to confirm (the old data was only samples)
```

---

## 4. Check the code locally

```bash
bash scripts/check.sh
```

This creates a private Python environment (`.venv`), installs the tools, and runs: template check (cfn-lint, if installed), lint (ruff), type-check (mypy), 35 unit tests (pytest, using a fake DynamoDB so nothing touches AWS), a security scan (bandit), the build, and a dependency audit. Expect a few minutes the first time. Every step should say `ok`.

To install cfn-lint for the template check: `pip install cfn-lint`.

Run just the tests any time with:
```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
python -m pytest
```

---

## 5. Deploy

```bash
bash scripts/deploy.sh
```

What it does, step by step:

1. Confirms your AWS login and picks the region.
2. Creates `.admin-key` containing a random secret (first run only, then reuses it). **Keep it private; it is git-ignored.**
3. Copies each function into `build/`.
4. Creates a private "deployment bucket" and uploads the function code there (`aws cloudformation package`).
5. Creates or updates the stack (`aws cloudformation deploy`). **The first deployment takes several minutes, mostly waiting for CloudFront.**
6. Uploads `index.html` and a generated `config.js` (which tells the page your API address) to the website bucket, and clears the CloudFront cache for those two files.
7. Prints your website and API addresses.

Watching progress: Console → **CloudFormation → Stacks → community-waste-reporting-ap → Events**. If something fails, the **Status reason** next to the failed row explains why, and the stack rolls back automatically.

---

## 6. Test it

### 6.1 Automatic test
```bash
bash scripts/smoke-test.sh
```
It calls your real API and website and prints one line per check (create a report, reject bad input, list, fetch one, admin refused without the key, admin allowed with it, website reachable, bucket not directly reachable). All should say `ok`.

### 6.2 In the browser
Open the website address printed by `deploy.sh`. Submit a report, then look for it in the table (it can take about a second to appear because indexes update a moment after the write). Open **Admin**, paste the contents of `.admin-key`, and you'll see buttons to change each report's status.

### 6.3 By hand with curl
```bash
API="$(aws cloudformation describe-stacks --stack-name community-waste-reporting-ap \
  --query "Stacks[0].Outputs[?OutputKey=='ReportsApiUrl'].OutputValue | [0]" --output text)"
KEY="$(cat .admin-key)"

# Create a report
curl -s -X POST "$API/reports" -H "content-type: application/json" \
  -d '{"area":"Downtown","category":"overflowing-bin","description":"Bin on Main St is overflowing"}'

# Bad input (no description) gives a 400 and a clear message
curl -s -i -X POST "$API/reports" -H "content-type: application/json" -d '{"area":"x","category":"other"}'

# List newest first
curl -s "$API/reports?area=downtown"
curl -s "$API/reports?status=open"

# One report (paste a reportId from above)
curl -s "$API/reports/PASTE-ID-HERE"

# Admin: change status
curl -s -X PATCH "$API/reports/PASTE-ID-HERE/status" -H "content-type: application/json" \
  -H "x-admin-key: $KEY" -d '{"status":"resolved"}'
```
Try the PATCH without the `x-admin-key` header too and confirm you get `401`.

### 6.4 See the data and the logs
- **DynamoDB console → Tables → Explore items:** your reports, including the `expiresAt` number.
- **CloudWatch → Log groups → `/aws/lambda/...`:** what each function printed. When something returns a 500 error, look here first.

---

## 7. How the code works (and exercises)

### Task 2: validation, in `functions/submit-report-fn/index.py`
`validate_report()` checks that the body is a JSON object and that `area`, `category` and `description` are non-empty strings of at most 500 characters, and that the category is on the allowed list. It returns either clean data or an error message, and `create_report()` turns an error into an HTTP `400`. Validating before saving keeps junk out of the database, which also means less data to store.

The report form includes sustainability-related concerns such as littering, recycling contamination, hazardous waste and electronic waste. New categories must be added to `CATEGORIES`, the `<select>` in `frontend/index.html`, and the corresponding tests.

### Task 3: `GET /reports/{reportId}`, in `functions/get-reports-fn/index.py`
`get_report()` calls `GetItem`, DynamoDB's fastest read (it uses the exact key). The key is `pk = REPORT#<id>`, `sk = REPORT`. Unknown or expired IDs return `404`.

### Listing, also in `get-reports-fn`
`list_reports()` uses `Query` on an **index** instead of `Scan`. A scan reads every item in the table (slow and costly as it grows); a query on an index jumps straight to what you asked for. `AreaIndex` is "all reports for one area, sorted by time"; `StatusIndex` is the same by status. Notice two details in the code:
- `status` is a *reserved word* in DynamoDB, so we write `#s` and map it to the real name.
- DynamoDB may keep an expired item for a while before TTL deletes it, so the code hides expired items itself.

### Task 4: `PATCH /reports/{reportId}/status`, in `submit-report-fn`
`is_admin()` compares the `x-admin-key` header with the secret stored in the function's environment (using `hmac.compare_digest`, a constant-time comparison). `update_status()` then runs `UpdateItem`. The line `ConditionExpression="attribute_exists(pk)"` matters: without it, patching an ID that doesn't exist would silently **create** a new item. When a report is resolved, `expiresAt` is reset to now + 90 days.

### Task 1: the website, `frontend/index.html`
Plain HTML and `fetch()`. Three habits to notice:
- All text from the API is added with `textContent`, **never** `innerHTML`. A report whose description contains `<script>` will display as harmless text. (This is how XSS attacks are prevented.)
- One helper, `api()`, makes every request and turns error responses into readable messages.
- The API address comes from `config.js`, generated at deploy time, so the same page works in any stack.

### The template, `infrastructure/template.yaml`
Read it top to bottom with the comments. The parts worth studying:
- **IAM roles:** each Lambda gets only the actions it needs. `GetReports` can never write, so a bug or an attack there cannot change data.
- **Origin Access Control:** the S3 bucket is fully private; only your CloudFront distribution may read it.
- **TTL:** `TimeToLiveSpecification` makes DynamoDB delete expired reports for free.
- **Throttling:** `DefaultRouteSettings` limits request rates so a flood can't run up a bill.

*Exercise:* change `RetentionDays` of the log groups from 14 to 7, redeploy, and see the change in the CloudFormation **Events** tab. This is how infrastructure changes should always be made.

---

## 8. Security: what is and isn't protected

| Protected | Not (yet) protected |
|---|---|
| Bucket is private; only CloudFront can read it | Anyone can submit reports (spam is possible; throttling limits the damage) |
| HTTPS everywhere (HTTP redirects to HTTPS) | The admin key is a shared secret in a Lambda environment variable. Anyone with console access to the function can read it |
| Admin routes need a key; the check fails closed if no key is configured | CORS allows any website to call the API |
| Least-privilege IAM per function | No audit trail of who changed a status |
| No delete route | No CAPTCHA or per-user identity |
| Reports auto-delete after 90 days | |

**Upgrade path:** Amazon Cognito (user sign-in) with an API Gateway JWT authorizer replaces the admin key, and the `claims` can say who made each change. Secrets Manager or SSM Parameter Store can hold any remaining secrets.

---

## 9. Optional: a custom domain with Route 53

Skip this unless you own a domain (for example `example.com`). Costs: the domain registration itself, plus a small monthly fee for the Route 53 hosted zone.

1. **Create a hosted zone.** Console → **Route 53 → Hosted zones → Create hosted zone**. Enter the name you'll use (`example.com`, or `waste.example.com` if you only want a subdomain). Type: **Public**.
   - If you registered the domain **with Route 53**, a hosted zone already exists; use it.
2. **Delegate the domain.** Open the zone and copy its four **NS** values. At your domain registrar, replace the domain's nameservers with them (for a subdomain, add NS records for the subdomain instead). **Wait until it works**:
   ```bash
   nslookup -type=NS example.com        # should list the four awsdns names
   ```
   This can take from minutes to a few hours. If you deploy before this works, the certificate can't be validated and the stack will fail and roll back.
3. **Copy the hosted zone ID** (looks like `Z0123456789ABCDEFGHIJ`) from the zone's details.
4. **Deploy with the domain** (it must be `us-east-1`, which CloudFront requires for its certificate):
   ```bash
   AWS_REGION=us-east-1 DOMAIN_NAME=waste.example.com HOSTED_ZONE_ID=Z0123456789ABCDEFGHIJ bash scripts/deploy.sh
   ```
   If your stack already exists in another region, run `destroy.sh` first and deploy fresh in `us-east-1`.
5. **Wait**, then open `https://waste.example.com`. Certificate validation and DNS can take several minutes.

What the template adds: an ACM certificate (free) validated through a DNS record it creates for you, the domain as an alias on the CloudFront distribution, and `A` and `AAAA` records in your hosted zone pointing at CloudFront. All of it is skipped when `DOMAIN_NAME` isn't set.

I could not deploy this part from here; the template passes `cfn-lint`, but treat the first real deployment as a test and read CloudFormation's **Events** tab if it fails.

---

## 10. Sustainability talking points

These tie each design choice to the AWS Well-Architected **Sustainability** pillar. Say them in your own words, and only claim what you can explain.

| Design choice | Why it reduces environmental impact |
|---|---|
| Serverless everywhere (Lambda, API Gateway, DynamoDB on-demand) | Nothing runs idle. AWS shares the underlying hardware across many customers, so you use resources only while requests are handled |
| Lambda on **arm64 (Graviton)** | Arm processors generally do the same work for less energy than comparable x86 ones |
| **CloudFront caching** and compression | Fewer requests travel back to the origin and fewer bytes travel over the network |
| **TTL (90-day retention)** | Data you no longer need is deleted automatically instead of being stored forever |
| **Indexes and `Query`** instead of `Scan` | Reads touch only the items needed, so less data is read and processed |
| **Right-sized memory (256 MB)** and short timeouts | Functions can't hold more compute than they need. Measure real usage in CloudWatch and try 128 MB |
| **Log retention of 14 days** | Logs are another form of stored data; keeping them forever has a cost |
| **Validation before saving** | Junk data is never stored or queried later |
| **`PriceClass_100`** CloudFront | Uses a smaller set of edge locations, which suits a small, regional audience |
| **Region choice** | A deliberate region decision (latency vs. cost vs. grid carbon intensity) is itself part of the pillar |
| **Everything as code and deletable** | `destroy.sh` removes all resources, so a finished experiment leaves nothing running |

Be careful with exact numbers (for example "arm uses X% less energy"). Quote AWS documentation or leave them out.

---

## 11. Clean up and costs

```bash
bash scripts/destroy.sh
```
Type the stack name to confirm. It empties the website bucket, deletes the stack (which deletes the table and its data), and deletes the deployment bucket. CloudFront deletion can take a few minutes. If you added a custom domain, delete the Route 53 hosted zone yourself if you created it by hand, because it carries a small monthly charge.

Typical cost for a low-traffic portfolio project is very small (see `ARCHITECTURE.md`), but always keep the budget alert from section 3.2 switched on. The easiest way to avoid surprise bills is to delete the stack when you aren't demoing it.

Point-in-time recovery is switched on for the table as a good-practice backup. It is not free; for a throwaway project you may switch it off by removing the `PointInTimeRecoverySpecification` block.

---

## 12. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `Unable to locate credentials` | Run `aws configure` (or `aws sso login`), then `aws sts get-caller-identity` |
| `deploy.sh: python3 not found` on Windows | Use `python` instead, or install Python and tick "Add to PATH"; run in Git Bash |
| Stack fails with *"Cannot perform more than one GSI creation..."* | You're updating the original kit's table. Run `destroy.sh` first (section 3.6) |
| Stack fails with a name-related error, or you want a second copy | Use a different name: `STACK_NAME=my-waste-app bash scripts/deploy.sh`. Keep it under 30 characters, lowercase |
| Stack stuck on `CREATE_IN_PROGRESS` for ~5-10 minutes | Normal: CloudFront is slow to create |
| Website loads but the table says "The API address is missing" | `config.js` wasn't uploaded; run `deploy.sh` again |
| Website shows old content after a change | Run `deploy.sh` again (it clears the cache for the two files); hard-refresh the browser (Ctrl+Shift+R) |
| Browser console shows a CORS error | Check the API address in `config.js` ends with `amazonaws.com` and that you're using the deployed template (CORS is configured on the API) |
| New report isn't in the list immediately | Normal: indexes update a moment later. Click **Show reports** again |
| `401` on `PATCH` | The `x-admin-key` header is missing or doesn't match `.admin-key` |
| `500 Something went wrong` | Open CloudWatch Logs for the function; the log line starting `Request failed` shows the error |
| `destroy.sh` fails deleting the stack | Check the stack's Events tab. If the website bucket wasn't empty, empty it in the S3 console and rerun |
| Smoke test shows `FAIL` | The line includes the status code it got and the start of the response; use them with the CloudWatch logs |

---

## 13. Turning this into a portfolio piece

- Put this folder in a **GitHub** repository. `.admin-key`, `.venv/` and `build/` are already in `.gitignore`. Double-check that no secret or AWS key is committed.
- In your README, add: a screenshot of the site, the architecture diagram (open `architecture.drawio` at app.diagrams.net and export a PNG), the live link if it's still deployed, and the sustainability table from section 10.
- Be ready to explain **trade-offs** in an interview: why DynamoDB over a relational database, why two indexes, why `Query` not `Scan`, why TTL, why the admin key is only a stopgap and what Cognito would change.
- Extension ideas once everything works: pagination with `LastEvaluatedKey`; photo uploads to S3 using pre-signed URLs; a CloudWatch alarm and dashboard; an SNS email when a new report arrives; GitHub Actions that run `check.sh` on every push; Cognito sign-in for admins.
