#!/usr/bin/env bash
# Deletes the stack and everything it created (including all reports).
#   bash scripts/destroy.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1
STACK_NAME="${STACK_NAME:-community-waste-reporting-ap}"
AWS_REGION="${AWS_REGION:-$(aws configure get region || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
read -r -p "Delete stack $STACK_NAME in $AWS_REGION and all its resources (data included)? Type the stack name to confirm: " answer
[ "$answer" = "$STACK_NAME" ] || { echo "Cancelled."; exit 1; }

# CloudFormation cannot delete a bucket that still has files in it, so empty the website bucket first.
SITE_BUCKET="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketBucketName'].OutputValue | [0]" --output text 2>/dev/null || true)"
if [ -n "$SITE_BUCKET" ] && [ "$SITE_BUCKET" != "None" ]; then
  aws s3 rm "s3://$SITE_BUCKET" --recursive >/dev/null && echo "Emptied the website bucket $SITE_BUCKET."
fi

aws cloudformation delete-stack --stack-name "$STACK_NAME"
echo "Deleting the stack (CloudFront can take a few minutes)..."
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
echo "Deleted $STACK_NAME."

# The deployment bucket only holds the uploaded build files (scripts/deploy.sh creates it).
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="$(printf '%s' "${STACK_NAME}-artifacts-${ACCOUNT_ID}-${AWS_REGION}" | tr '[:upper:]' '[:lower:]' | cut -c1-63)"
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws s3 rb "s3://$BUCKET" --force >/dev/null && echo "Deleted the deployment bucket $BUCKET."
fi
