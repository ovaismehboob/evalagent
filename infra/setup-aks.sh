#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-aks.sh — Provision ACR, AKS, Managed Identity, and Workload Identity
#
# Prerequisites: az login, correct subscription selected
# Usage:         bash infra/setup-aks.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Variables (edit these) ───────────────────────────────────────────────────
SUBSCRIPTION="fabefbde-9477-48d7-bdd0-27af2eaeeb52"
LOCATION="eastus2"
RG="rg-eval-agent-aks"
ACR_NAME="acrevalagent"          # Must be globally unique, alphanumeric only
AKS_NAME="aks-eval-agent"
IDENTITY_NAME="id-eval-agent"
K8S_SA_NAME="eval-agent-sa"
K8S_NAMESPACE="default"

# Existing resources (used for RBAC)
SEARCH_RG="rg-eval-demo"
SEARCH_NAME="search-eval-demo"
OPENAI_RG="rg-eval-demo"
OPENAI_NAME="aoai-eval-demo"
FOUNDRY_RG="rg-contoso-helpdesk"
FOUNDRY_ACCOUNT="ai-account-ibfr6ordyckcq"

# ── Set subscription ────────────────────────────────────────────────────────
az account set --subscription "$SUBSCRIPTION"
echo "Using subscription: $SUBSCRIPTION"

# ── 1. Create resource group ────────────────────────────────────────────────
echo "Creating resource group $RG..."
az group create --name "$RG" --location "$LOCATION" -o none

# ── 2. Create Azure Container Registry ──────────────────────────────────────
echo "Creating ACR $ACR_NAME..."
az acr create --name "$ACR_NAME" --resource-group "$RG" --sku Basic -o none
ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
echo "  ACR Login Server: $ACR_LOGIN_SERVER"

# ── 3. Create AKS cluster ───────────────────────────────────────────────────
echo "Creating AKS cluster $AKS_NAME (this takes a few minutes)..."
az aks create \
  --resource-group "$RG" \
  --name "$AKS_NAME" \
  --node-count 1 \
  --node-vm-size Standard_B2s \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --attach-acr "$ACR_NAME" \
  --generate-ssh-keys \
  -o none

# ── 4. Create managed identity for the agent ────────────────────────────────
echo "Creating managed identity $IDENTITY_NAME..."
az identity create --name "$IDENTITY_NAME" --resource-group "$RG" -o none

IDENTITY_CLIENT_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query clientId -o tsv)
IDENTITY_PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query principalId -o tsv)
echo "  Client ID:    $IDENTITY_CLIENT_ID"
echo "  Principal ID: $IDENTITY_PRINCIPAL_ID"

# ── 5. Assign RBAC roles to the managed identity ────────────────────────────
echo "Assigning RBAC roles..."

SEARCH_SCOPE="/subscriptions/$SUBSCRIPTION/resourceGroups/$SEARCH_RG/providers/Microsoft.Search/searchServices/$SEARCH_NAME"
OPENAI_SCOPE="/subscriptions/$SUBSCRIPTION/resourceGroups/$OPENAI_RG/providers/Microsoft.CognitiveServices/accounts/$OPENAI_NAME"

az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Search Index Data Reader" \
  --scope "$SEARCH_SCOPE" -o none
echo "  ✓ Search Index Data Reader"

az role assignment create \
  --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "$OPENAI_SCOPE" -o none
echo "  ✓ Cognitive Services OpenAI User"

# ── 6. Create federated credential for workload identity ────────────────────
AKS_OIDC_ISSUER=$(az aks show --name "$AKS_NAME" --resource-group "$RG" --query "oidcIssuerProfile.issuerUrl" -o tsv)
echo "AKS OIDC Issuer: $AKS_OIDC_ISSUER"

az identity federated-credential create \
  --name "fed-aks-eval-agent" \
  --identity-name "$IDENTITY_NAME" \
  --resource-group "$RG" \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:${K8S_NAMESPACE}:${K8S_SA_NAME}" \
  --audience "api://AzureADTokenExchange" \
  -o none
echo "  ✓ Federated credential created"

# ── 7. Get AKS credentials ──────────────────────────────────────────────────
echo "Getting AKS credentials..."
az aks get-credentials --resource-group "$RG" --name "$AKS_NAME" --overwrite-existing

# ── 8. Apply K8s service account (substitute client ID) ─────────────────────
echo "Applying Kubernetes manifests..."
sed "s|\${IDENTITY_CLIENT_ID}|${IDENTITY_CLIENT_ID}|g" k8s/service-account.yaml | kubectl apply -f -
echo "  ✓ ServiceAccount created"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "AKS INFRASTRUCTURE READY"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "ACR Login Server:     $ACR_LOGIN_SERVER"
echo "AKS Cluster:          $AKS_NAME"
echo "Managed Identity:     $IDENTITY_CLIENT_ID"
echo ""
echo "Next steps:"
echo "  1. Build + push image:  az acr build --registry $ACR_NAME --image eval-agent:v1 ."
echo "  2. Deploy to AKS:       Update k8s/deployment.yaml with your values, then kubectl apply -f k8s/"
echo "  3. Set up GitHub OIDC:  bash infra/setup-github-oidc.sh"
echo ""
echo "Save these values for GitHub Actions repository variables:"
echo "  ACR_NAME=$ACR_NAME"
echo "  AKS_CLUSTER_NAME=$AKS_NAME"
echo "  AKS_RESOURCE_GROUP=$RG"
echo "  IDENTITY_CLIENT_ID=$IDENTITY_CLIENT_ID"
