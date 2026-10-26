#!/usr/bin/env bash
# Builds the Lambda code, deploys the CloudFormation stack, then uploads the website to S3.
#
#   bash scripts/deploy.sh
#   STACK_NAME=my-app AWS_REGION=eu-west-1 bash scripts/deploy.sh
#
# Needs Python 3.12+, the AWS CLI v2 and AWS credentials (aws configure, or aws sso login).
# Works in Git Bash on Windows, macOS and Linux.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "${BASH_SOURCE[0]}")/.."

STACK_NAME="${STACK_NAME:-community-waste-reporting-ap}"
command -v aws >/dev/null || { echo "The AWS CLI v2 is required: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" >&2; exit 1; }
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)" || { echo "AWS credentials are not set up. Run 'aws configure' or 'aws sso login'." >&2; exit 1; }
AWS_REGION="${AWS_REGION:-$(aws configure get region || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
echo "Deploying stack $STACK_NAME to account $ACCOUNT_ID in $AWS_REGION"

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "Python 3.12+ is required: https://www.python.org/downloads/" >&2; exit 1; }

# The admin key protects PATCH /reports/{id}/status. It is created once, saved in .admin-key
# (git-ignored) and reused on every deploy so it never changes by accident.
if [ -z "${ADMIN_KEY:-}" ]; then
  if [ -f .admin-key ]; then
    ADMIN_KEY="$(cat .admin-key)"
  else
    ADMIN_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"
    echo "==> Generated a new admin key and saved it in .admin-key"
  fi
fi
printf '%s' "$ADMIN_KEY" > .admin-key

# Optional custom domain: DOMAIN_NAME=waste.example.com HOSTED_ZONE_ID=Z0123456789ABC bash scripts/deploy.sh
PARAMS=("AdminKey=$ADMIN_KEY")
if [ -n "${DOMAIN_NAME:-}" ]; then
  [ -n "${HOSTED_ZONE_ID:-}" ] || { echo "Set HOSTED_ZONE_ID (your Route 53 hosted zone) together with DOMAIN_NAME." >&2; exit 1; }
  PARAMS+=("DomainName=$DOMAIN_NAME" "HostedZoneId=$HOSTED_ZONE_ID")
fi

echo "==> Building the Lambda code"
"$PY" scripts/build.py

BUCKET="$(printf '%s' "${STACK_NAME}-artifacts-${ACCOUNT_ID}-${AWS_REGION}" | tr '[:upper:]' '[:lower:]' | cut -c1-63)"
if ! aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "==> Creating the deployment bucket $BUCKET"
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

echo "==> Uploading the code and deploying (the first deploy can take several minutes: CloudFront is slow)"
aws cloudformation package \
  --template-file infrastructure/template.yaml \
  --s3-bucket "$BUCKET" --s3-prefix "$STACK_NAME" \
  --output-template-file build/packaged.yaml >/dev/null
aws cloudformation deploy \
  --template-file build/packaged.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides "${PARAMS[@]}" \
  --no-fail-on-empty-changeset

output() { aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
API_URL="$(output ReportsApiUrl)"
SITE_BUCKET="$(output FrontendBucketBucketName)"
DISTRIBUTION="$(output CdnDistributionId)"
SITE_DOMAIN="$(output CdnDomainName)"

echo "==> Uploading the website"
# config.js tells the page where the API lives; it is generated here because the URL is only known after deploying.
printf 'window.APP_CONFIG = { apiUrl: "%s" };\n' "${API_URL%/}" > build/config.js
aws s3 cp frontend/index.html "s3://$SITE_BUCKET/index.html" --content-type "text/html; charset=utf-8" --cache-control "no-cache" >/dev/null
aws s3 cp build/config.js "s3://$SITE_BUCKET/config.js" --content-type "application/javascript; charset=utf-8" --cache-control "no-cache" >/dev/null
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/index.html" "/config.js" >/dev/null

echo
echo "==> Done."
echo "    Website:   https://$SITE_DOMAIN"
[ -z "${DOMAIN_NAME:-}" ] || echo "    Domain:    https://$DOMAIN_NAME (DNS can take a few minutes to start working)"
echo "    API:       $API_URL"
echo "    Admin key: saved in .admin-key (keep it secret)"
echo "Next: bash scripts/smoke-test.sh checks that everything works."
