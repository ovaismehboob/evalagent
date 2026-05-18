#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-github-oidc.sh — Create Azure AD app registration + federated
# credential for GitHub Actions OIDC authentication.
#
# Prerequisites: az login, correct subscription, setup-aks.sh already run
# Usage:         bash infra/setup-github-oidc.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Variables (edit these) ───────────────────────────────────────────────────
SUBSCRIPTION="fabefbde-9477-48d7-bdd0-27af2eaeeb52"
TENANT_ID="16b3c013-d300-468d-ac64-7eda0820b6d3"
GITHUB_ORG="ovaismehboob"
GITHUB_REPO="evalagent"
APP_NAME="github-evalagent-deploy"

# Resource groups for role assignments
AKS_RG="rg-eval-agent-aks"
ACR_NAME="acrevalagent"
FOUNDRY_RG="rg-contoso-helpdesk"
FOUNDRY_ACCOUNT="ai-account-ibfr6ordyckcq"
OPENAI_RG="rg-eval-demo"
OPENAI_NAME="aoai-eval-demo"

# ── Set subscription ────────────────────────────────────────────────────────
az account set --subscription "$SUBSCRIPTION"

# ── 1. Create Azure AD app registration ─────────────────────────────────────
echo "Creating app registration '$APP_NAME'..."
APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
echo "  App (Client) ID: $APP_ID"

# ── 2. Create service principal ─────────────────────────────────────────────
echo "Creating service principal..."
az ad sp create --id "$APP_ID" -o none 2>/dev/null || true
SP_OID=$(az ad sp show --id "$APP_ID" --query id -o tsv)
echo "  SP Object ID: $SP_OID"

# ── 3. Create federated credential for GitHub Actions ───────────────────────
echo "Creating federated credential for ${GITHUB_ORG}/${GITHUB_REPO}:main..."
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-main\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}" -o none
echo "  ✓ Federated credential created"

# ── 4. Assign roles to the service principal ────────────────────────────────
echo "Assigning RBAC roles..."

# Contributor on AKS resource group (deploy to AKS)
az role assignment create \
  --assignee-object-id "$SP_OID" \
  --assignee-principal-type ServicePrincipal \
  --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION/resourceGroups/$AKS_RG" \
  -o none
echo "  ✓ Contributor on $AKS_RG"

# AcrPush on ACR (push Docker images)
ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$AKS_RG" --query id -o tsv)
az role assignment create \
  --assignee-object-id "$SP_OID" \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPush" \
  --scope "$ACR_ID" \
  -o none
echo "  ✓ AcrPush on $ACR_NAME"

# Azure AI Developer on Foundry account (upload datasets, create evaluations)
FOUNDRY_SCOPE="/subscriptions/$SUBSCRIPTION/resourceGroups/$FOUNDRY_RG/providers/Microsoft.CognitiveServices/accounts/$FOUNDRY_ACCOUNT"
az role assignment create \
  --assignee-object-id "$SP_OID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI Developer" \
  --scope "$FOUNDRY_SCOPE" \
  -o none
echo "  ✓ Azure AI Developer on $FOUNDRY_ACCOUNT"

# Cognitive Services OpenAI User (evaluation uses the model to judge)
OPENAI_SCOPE="/subscriptions/$SUBSCRIPTION/resourceGroups/$OPENAI_RG/providers/Microsoft.CognitiveServices/accounts/$OPENAI_NAME"
az role assignment create \
  --assignee-object-id "$SP_OID" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "$OPENAI_SCOPE" \
  -o none
echo "  ✓ Cognitive Services OpenAI User on $OPENAI_NAME"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "GITHUB OIDC SETUP COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Add these as GitHub repository secrets (Settings → Secrets → Actions):"
echo ""
echo "  AZURE_CLIENT_ID=$APP_ID"
echo "  AZURE_TENANT_ID=$TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION"
echo ""
echo "Add these as GitHub repository variables (Settings → Variables → Actions):"
echo ""
echo "  ACR_NAME=$ACR_NAME"
echo "  AKS_CLUSTER_NAME=aks-eval-agent"
echo "  AKS_RESOURCE_GROUP=$AKS_RG"
echo "  AZURE_SEARCH_ENDPOINT=https://search-eval-demo.search.windows.net"
echo "  AZURE_OPENAI_ENDPOINT=https://aoai-eval-demo.openai.azure.com"
echo "  AZURE_AI_PROJECT_ENDPOINT=https://ai-account-ibfr6ordyckcq.services.ai.azure.com/api/projects/ai-project-contoso-helpdesk"
echo "  AZURE_OPENAI_DEPLOYMENT=gpt-4o"
