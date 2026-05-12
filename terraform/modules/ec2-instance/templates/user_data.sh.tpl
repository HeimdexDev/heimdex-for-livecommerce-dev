#!/bin/bash
set -euo pipefail

# Heimdex EC2 Bootstrap — tenant: ${client_name}
# Runs once on first EC2 boot only.
# Subsequent .env updates are handled by GitHub Actions deploy workflow.

APP_DIR=/opt/heimdex/dev-heimdex-for-livecommerce

# ── Install Docker (if not present) ─────────────────────
if ! command -v docker &>/dev/null; then
  dnf install -y docker git
  systemctl enable docker
  systemctl start docker
  usermod -aG docker ec2-user

  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# ── Create directories ──────────────────────────────────
mkdir -p /opt/heimdex/logs

# ── Git clone (app + sibling libraries used via editable mounts) ─
CONTRACTS_DIR=/opt/heimdex/heimdex-media-contracts
PIPELINES_DIR=/opt/heimdex/heimdex-media-pipelines

if [ ! -d "$APP_DIR/.git" ]; then
  rm -rf "$APP_DIR"
  git clone -b ${git_branch} ${git_repo} "$APP_DIR"
fi

if [ ! -d "$CONTRACTS_DIR/.git" ]; then
  rm -rf "$CONTRACTS_DIR"
  git clone -b main https://github.com/jlee-heimdex/heimdex-media-contracts.git "$CONTRACTS_DIR"
fi

if [ ! -d "$PIPELINES_DIR/.git" ]; then
  rm -rf "$PIPELINES_DIR"
  git clone -b main https://github.com/jlee-heimdex/heimdex-media-pipelines.git "$PIPELINES_DIR"
fi

# ── Generate .env (config values + SSM params) ──────────
cat > $APP_DIR/.env << 'ENVEOF'
${env_content}
ENVEOF

# Fetch secrets and service URLs from SSM Parameter Store
%{ for param_name in ssm_param_names ~}
VALUE=$(aws ssm get-parameter \
  --name "${ssm_prefix}/${param_name}" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text \
  --region ${region} 2>/dev/null || echo "")
if [ -n "$VALUE" ]; then
  echo "${param_name}=$VALUE" >> $APP_DIR/.env
fi
%{ endfor ~}

chown -R ec2-user:ec2-user /opt/heimdex
