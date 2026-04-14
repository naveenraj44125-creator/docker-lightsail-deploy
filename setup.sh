#!/bin/bash
# setup.sh — Bootstrap OIDC, IAM role, and GitHub variables for Docker Lightsail deployment
set -e

# ── Prerequisites check ──────────────────────────────────────────────────────
for cmd in aws gh jq; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "❌ Required tool not found: $cmd"
    echo "   Install: aws-cli, gh (GitHub CLI), jq"
    exit 1
  fi
done

# ── Inputs ───────────────────────────────────────────────────────────────────
read -rp "GitHub username: " GITHUB_USER
read -rp "GitHub repository name: " GITHUB_REPO
read -rp "AWS region [us-east-1]: " AWS_REGION
AWS_REGION="${AWS_REGION:-us-east-1}"
read -rp "Lightsail instance name [my-docker-app]: " INSTANCE_NAME
INSTANCE_NAME="${INSTANCE_NAME:-my-docker-app}"

ROLE_NAME="GitHubActionsRole-${INSTANCE_NAME}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo ""
echo "🔧 Setting up OIDC + IAM for ${GITHUB_USER}/${GITHUB_REPO}"
echo "   Account: ${ACCOUNT_ID} | Region: ${AWS_REGION}"
echo ""

# ── OIDC Provider ────────────────────────────────────────────────────────────
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" &>/dev/null; then
  echo "✅ OIDC provider already exists"
else
  echo "Creating OIDC provider..."
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
  echo "✅ OIDC provider created"
fi

# ── IAM Role ─────────────────────────────────────────────────────────────────
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "${OIDC_ARN}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:${GITHUB_USER}/${GITHUB_REPO}:*"
      }
    }
  }]
}
EOF
)

if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  echo "✅ IAM role already exists: $ROLE_NAME"
else
  echo "Creating IAM role: $ROLE_NAME..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY"
  echo "✅ IAM role created"
fi

# ── IAM Policies ─────────────────────────────────────────────────────────────
LIGHTSAIL_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["lightsail:*"],
    "Resource": "*"
  }]
}
EOF
)

POLICY_NAME="LightsailFullAccess-${INSTANCE_NAME}"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

if aws iam get-policy --policy-arn "$POLICY_ARN" &>/dev/null; then
  echo "✅ Lightsail policy already exists"
else
  aws iam create-policy --policy-name "$POLICY_NAME" --policy-document "$LIGHTSAIL_POLICY"
  echo "✅ Lightsail policy created"
fi

aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" 2>/dev/null || true
aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess 2>/dev/null || true
echo "✅ Policies attached"

# ── GitHub Variable ───────────────────────────────────────────────────────────
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
gh variable set AWS_ROLE_ARN --body "$ROLE_ARN" --repo "${GITHUB_USER}/${GITHUB_REPO}"
echo "✅ GitHub variable AWS_ROLE_ARN set"

echo ""
echo "🎉 Setup complete!"
echo "   Role ARN: ${ROLE_ARN}"
echo "   Push to main to trigger deployment."
