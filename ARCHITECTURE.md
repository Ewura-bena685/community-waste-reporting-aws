# Community Waste Reporting App

Serverless waste reporting system: S3+CloudFront static frontend, HTTP API Gateway routing to ARM64 Lambda functions, DynamoDB on-demand for storage. Scale-to-zero, Free Tier eligible, sustainability-aligned.

**Region:** us-east-1

Diagram: `architecture.drawio` (open it in draw.io or diagrams.net).

## Services

| Id | Name | Service | Purpose | Settings |
|---|---|---|---|---|
| `frontend-bucket` | Frontend Bucket | Amazon S3 | Hosts static HTML/CSS/JS for the reporting dashboard. Private bucket accessed only via CloudFront OAC. | getsPerMonth: 5000, putsPerMonth: 50, storageGb: 0.1 |
| `cdn` | CloudFront Distribution | Amazon CloudFront | Edge-caches the frontend for low latency and serves it over HTTPS via ACM. Reduces S3 origin fetches. | requestsPerMonth: 10000, transferGb: 1 |
| `reports-api` | Reports HTTP API | Amazon API Gateway (HTTP API) | HTTP API (not REST — 70% cheaper) routing POST /reports, GET /reports, GET /reports/{reportId} and PATCH /reports/{reportId}/status to Lambda functions. Built-in CORS support and request throttling. | apiType: http, requestsPerMonth: 10000 |
| `submit-report-fn` | SubmitReport Function | AWS Lambda | Validates input and writes a new waste report to DynamoDB (reportId UUID, createdAt, expiresAt = 90 days). Also handles the admin-only status update, which restarts the 90-day clock on resolution. | architecture: arm64, avgDurationMs: 100, memoryMb: 256, requestsPerMonth: 3000, timeoutSeconds: 10 |
| `get-reports-fn` | GetReports Function | AWS Lambda | Queries DynamoDB by area (GSI) or status (GSI) and returns reports sorted by createdAt descending. | architecture: arm64, avgDurationMs: 80, memoryMb: 256, requestsPerMonth: 7000, timeoutSeconds: 10 |
| `reports-table` | WasteReports Table | Amazon DynamoDB | Stores waste reports. pk=REPORT#<reportId>, sk=REPORT. GSI AreaIndex (area, createdAt) and StatusIndex (status, createdAt). TTL on expiresAt auto-deletes reports after 90 days. | readsPerMonth: 15000, storageGb: 0.1, writesPerMonth: 3000 |

## How they connect

- **CloudFront Distribution** → **Frontend Bucket**: CloudFront fetches static assets from S3 via Origin Access Control (OAC). Bucket stays private.
- **Reports HTTP API** → **SubmitReport Function**: POST /reports routes to SubmitReport Lambda.
- **Reports HTTP API** → **GetReports Function**: GET /reports and GET /reports/{reportId} route to GetReports Lambda (read-only IAM role).
- **SubmitReport Function** → **WasteReports Table**: PutItem to write a new waste report with UUID, timestamp, and TTL.
- **GetReports Function** → **WasteReports Table**: Query by AreaIndex or StatusIndex to return reports sorted newest-first.

## Assumptions

- Under 10,000 API requests/month total (~3K writes, ~7K reads).
- Static frontend is under 100 MB (HTML/CSS/JS, no media uploads).
- Submitting and reading reports is public. Changing a report's status needs the admin key (x-admin-key header); Cognito is the natural next step.
- us-east-1 chosen for lowest cost and renewable energy commitments.
- DynamoDB on-demand mode — no provisioned capacity.
- TTL set to 90 days to auto-delete old reports (sustainability: data patterns).
- CloudWatch Logs retention set to 14 days (automatic with Lambda, no extra resource needed).
- Route 53 hosted zone ($0.50/month) and ACM certificate (free) are needed only if using a custom domain — noted in deployment steps.
- Lambda memory at 256 MB — can be reduced to 128 MB after measuring actual usage in CloudWatch.

## Estimated monthly cost

**Total: $0.14/month**

| Service | Usage basis | Monthly |
|---|---|---:|
| Frontend Bucket (Amazon S3) | 0.1 GB Standard, 50 PUTs, 5,000 GETs | $0.00 |
| CloudFront Distribution (Amazon CloudFront) | 1 GB out, 10,000 HTTPS requests | $0.10 |
| Reports HTTP API (Amazon API Gateway (HTTP API)) | 10,000 HTTP API requests | $0.01 |
| SubmitReport Function (AWS Lambda) | 3,000 requests × 100 ms at 256 MB (arm64) | $0.00 |
| GetReports Function (AWS Lambda) | 7,000 requests × 80 ms at 256 MB (arm64) | $0.00 |
| WasteReports Table (Amazon DynamoDB) | On-demand: 15,000 reads, 3,000 writes, 0.1 GB | $0.03 |

_Estimate based on AWS on-demand list prices (us-east-1) and the usage assumptions shown. Free tiers are not subtracted, and data transfer between services is not included. Check the AWS Pricing Calculator before committing._
