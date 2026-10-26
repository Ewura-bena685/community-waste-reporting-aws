#!/usr/bin/env bash
# Checks the deployed app really works by calling the real API and website:
#   bash scripts/smoke-test.sh
# Run it after scripts/deploy.sh (same STACK_NAME and AWS_REGION). It saves one report in the area
# "smoke-test"; DynamoDB deletes it automatically after the 90-day retention period.
set -uo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "${BASH_SOURCE[0]}")/.."

STACK_NAME="${STACK_NAME:-community-waste-reporting-ap}"
AWS_REGION="${AWS_REGION:-$(aws configure get region || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
aws cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1 || { echo "Stack $STACK_NAME isn't deployed in $AWS_REGION. Run bash scripts/deploy.sh first." >&2; exit 1; }
[ -f .admin-key ] || { echo "Missing .admin-key (deploy.sh creates it). Set ADMIN_KEY or redeploy." >&2; exit 1; }
PY="$(command -v python3 || command -v python)"

output() { aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
API="$(output ReportsApiUrl)"; API="${API%/}"
SITE="https://$(output CdnDomainName)"
KEY="$(cat .admin-key)"
BODY=""   # the body of the most recent response (kept in a variable, not a file, so it works the same in Git Bash)
JSON=(-H "content-type: application/json")

passed=0; failed=0
ok()  { printf '  \033[32mok\033[0m    %s\n' "$*"; passed=$((passed + 1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; failed=$((failed + 1)); }
# check <expected status> <description> <curl args...>: makes one request and checks the status code.
check() {
  local want="$1" desc="$2" resp got; shift 2
  resp="$(curl -s -w $'\n%{http_code}' "$@")"   # body, a newline, then the status code
  got="${resp##*$'\n'}"
  BODY="${resp%$'\n'*}"
  if [ "$got" = "$want" ]; then ok "$desc"; else bad "$desc (expected $want, got $got: ${BODY:0:200})"; fi
}
field() { printf '%s' "$BODY" | "$PY" -c "import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ''))" "$1"; }

echo "Smoke test of $STACK_NAME in $AWS_REGION"
echo "API:  $API"
echo "Site: $SITE"
echo
echo "Reports"
check 201 "POST /reports saves a valid report" -X POST "$API/reports" "${JSON[@]}" -d '{"area":"smoke-test","category":"other","description":"Created by smoke-test.sh"}'
ID="$(field reportId)"
check 400 "POST /reports rejects a missing description" -X POST "$API/reports" "${JSON[@]}" -d '{"area":"smoke-test","category":"other"}'
check 400 "POST /reports rejects an unknown category" -X POST "$API/reports" "${JSON[@]}" -d '{"area":"smoke-test","category":"graffiti","description":"x"}'

# Indexes (GSIs) are eventually consistent: a new item can take a moment to appear in a list.
found=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  BODY="$(curl -s "$API/reports?area=smoke-test")"
  if [ -n "$ID" ] && [[ "$BODY" == *"$ID"* ]]; then found=1; break; fi
  sleep 1
done
if [ "$found" = 1 ]; then ok "GET /reports?area=smoke-test lists the new report"; else bad "GET /reports?area=smoke-test did not list $ID"; fi
check 200 "GET /reports (default: open reports) works" "$API/reports"
check 200 "GET /reports/{id} returns the report" "$API/reports/$ID"
check 404 "GET /reports/{id} returns 404 for an unknown id" "$API/reports/does-not-exist"

echo
echo "Admin status changes"
check 401 "PATCH without the admin key is refused" -X PATCH "$API/reports/$ID/status" "${JSON[@]}" -d '{"status":"resolved"}'
check 400 "PATCH with an invalid status is refused" -X PATCH "$API/reports/$ID/status" "${JSON[@]}" -H "x-admin-key: $KEY" -d '{"status":"banana"}'
check 404 "PATCH on an unknown report is 404" -X PATCH "$API/reports/does-not-exist/status" "${JSON[@]}" -H "x-admin-key: $KEY" -d '{"status":"resolved"}'
check 200 "PATCH with the admin key marks it resolved" -X PATCH "$API/reports/$ID/status" "${JSON[@]}" -H "x-admin-key: $KEY" -d '{"status":"resolved"}'
if [ "$(field status)" = "resolved" ]; then ok "the response shows status = resolved"; else bad "the response did not show status = resolved"; fi

echo
echo "Website"
check 200 "CloudFront serves index.html" "$SITE/"
if [[ "$BODY" == *"Community Waste"* ]]; then ok "the page content is the waste reporting app"; else bad "unexpected page content"; fi
check 200 "CloudFront serves config.js" "$SITE/config.js"
check 403 "the S3 bucket is not directly reachable (only via CloudFront)" "https://$(output FrontendBucketBucketName).s3.$AWS_REGION.amazonaws.com/index.html"

echo
if [ "$failed" = 0 ]; then printf '\033[1;32mAll %s checks passed.\033[0m\n' "$passed"; else printf '\033[1;31m%s passed, %s failed.\033[0m\n' "$passed" "$failed"; exit 1; fi
