# RAG Agent Evaluation Pipeline — Comprehensive Setup Guide

A complete end-to-end demo that builds a RAG (Retrieval-Augmented Generation) agent, deploys it to Azure Kubernetes Service, evaluates it using Microsoft Foundry cloud evaluations, and automates the entire flow with a GitHub Actions CI/CD pipeline.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Azure Resource Setup](#3-azure-resource-setup)
4. [Project File Reference](#4-project-file-reference)
5. [Phase 1 — Run Locally](#5-phase-1--run-locally)
6. [Phase 2 — Deploy to AKS](#6-phase-2--deploy-to-aks)
7. [Phase 3 — GitHub Actions CI/CD](#7-phase-3--github-actions-cicd)
8. [Testing & Validation](#8-testing--validation)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────┐        ┌──────────────────────┐        ┌──────────────────┐
│  GitHub Actions  │──push──▶  Azure Container     │──pull──▶  AKS Cluster     │
│  CI/CD Pipeline  │        │  Registry (ACR)      │        │  (eval-agent)    │
└────────┬────────┘        └──────────────────────┘        └────────┬─────────┘
         │                                                          │
         │  POST /ask                                               │
         ├──────────────────────────────────────────────────────────┘
         │                                              ┌─────────────────────┐
         │  Evaluation results                          │  Azure AI Search    │
         ▼                                              │  (contoso-policies) │
┌─────────────────────┐                                 └─────────────────────┘
│  Microsoft Foundry  │                                 ┌─────────────────────┐
│  (Evaluation Tab)   │                                 │  Azure OpenAI       │
└─────────────────────┘                                 │  (gpt-4o)           │
                                                        └─────────────────────┘
```

**Flow:**
1. Developer pushes code to `main` branch on GitHub.
2. GitHub Actions builds a Docker image and pushes it to ACR.
3. The pipeline deploys the new image to AKS.
4. Post-deployment, the pipeline runs 8 test queries against the deployed agent.
5. Results are uploaded to Microsoft Foundry and evaluated using 5 built-in evaluators.
6. Evaluation scores appear in the Foundry portal's Evaluation tab.

---

## 2. Prerequisites

### 2.1 Tools (Install on Your Machine)

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.10+ | Run agent and evaluation scripts |
| **Azure CLI** | 2.60+ | Provision Azure resources |
| **kubectl** | Latest | Manage AKS deployments |
| **GitHub CLI (`gh`)** | Latest | Create repo, set secrets/variables |
| **Git** | Latest | Version control |

Install commands (Windows):
```powershell
# Python — download from https://www.python.org/downloads/
# Azure CLI
winget install Microsoft.AzureCLI
# kubectl (installed with Azure CLI via)
az aks install-cli
# GitHub CLI
winget install GitHub.cli
```

### 2.2 Azure Subscription

You need an Azure subscription with permissions to create:
- Resource groups
- Azure AI Search (Free or Basic tier)
- Azure OpenAI (with `gpt-4o` model deployment)
- Azure AI Foundry project (for cloud evaluations)
- Azure Container Registry (Basic tier)
- Azure Kubernetes Service (1 node)
- Managed Identities and RBAC role assignments
- Azure AD App Registrations (for GitHub OIDC)

### 2.3 GitHub Account

A GitHub account to host the repo and run GitHub Actions.

### 2.4 Azure Authentication

Log in to Azure before running any scripts:
```bash
az login
az account set --subscription "<your-subscription-id>"
```

---

## 3. Azure Resource Setup

You need **three categories** of Azure resources. Create them in order.

### 3.1 Core AI Resources (Create First)

These are the backend services the RAG agent depends on.

#### Azure AI Search
```bash
az group create --name rg-eval-demo --location eastus2
az search service create \
  --name <your-search-service> \
  --resource-group rg-eval-demo \
  --sku basic \
  --location eastus
```

#### Azure OpenAI
```bash
az cognitiveservices account create \
  --name <your-openai-account> \
  --resource-group rg-eval-demo \
  --kind OpenAI \
  --sku-name S0 \
  --location eastus2

# Deploy gpt-4o model
az cognitiveservices account deployment create \
  --name <your-openai-account> \
  --resource-group rg-eval-demo \
  --deployment-name gpt-4o \
  --model-name gpt-4o \
  --model-version "2024-11-20" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name GlobalStandard
```

#### Azure AI Foundry Project
Create via the [Azure AI Foundry portal](https://ai.azure.com):
1. Create an AI Services account (e.g., `ai-account-<unique>`)
2. Create a project under it (e.g., `ai-project-<your-project>`)
3. Note the project endpoint: `https://<account>.services.ai.azure.com/api/projects/<project>`

#### RBAC for Your User Account
Grant yourself data-plane access so the scripts can authenticate via `DefaultAzureCredential`:
```bash
# Replace <your-user-object-id> with your Azure AD object ID
USER_OID=$(az ad signed-in-user show --query id -o tsv)

# AI Search — read index data
az role assignment create --assignee $USER_OID \
  --role "Search Index Data Contributor" \
  --scope "/subscriptions/<sub>/resourceGroups/<search-rg>/providers/Microsoft.Search/searchServices/<your-search-service>"

# Azure OpenAI — call the model
az role assignment create --assignee $USER_OID \
  --role "Cognitive Services OpenAI User" \
  --scope "/subscriptions/<sub>/resourceGroups/<openai-rg>/providers/Microsoft.CognitiveServices/accounts/<your-openai-account>"

# Foundry — create evaluations
az role assignment create --assignee $USER_OID \
  --role "Azure AI Developer" \
  --scope "/subscriptions/<sub>/resourceGroups/<foundry-rg>/providers/Microsoft.CognitiveServices/accounts/<foundry-account>"
```

### 3.2 AKS Infrastructure (Phase 2)

Created by `infra/setup-aks.sh`. See [Phase 2](#6-phase-2--deploy-to-aks).

### 3.3 GitHub OIDC (Phase 3)

Created by `infra/setup-github-oidc.sh`. See [Phase 3](#7-phase-3--github-actions-cicd).

---

## 4. Project File Reference

### 4.1 Core Application Files

| File | Purpose |
|------|---------|
| `rag_agent.py` | The RAG pipeline — retrieves documents from AI Search and generates answers with Azure OpenAI |
| `app.py` | FastAPI HTTP wrapper around `rag_agent.py` for containerized deployment |
| `evaluate_rag.py` | Runs test queries against the agent (local or remote), uploads results to Foundry, creates a cloud evaluation |
| `setup_search.py` | One-time script to create the AI Search index and upload 5 sample Contoso policy documents |
| `test_data.jsonl` | 8 test queries with ground-truth answers for evaluation |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment variables (copy to `.env` and fill in) |

### 4.2 Detailed File Descriptions

#### `rag_agent.py` — The RAG Agent

This is the core agent. It implements a standard RAG pattern:

1. **`retrieve(query)`** — Sends the user query to Azure AI Search, retrieves the top 3 matching document chunks.
2. **`generate(query, context)`** — Sends the query + retrieved context to Azure OpenAI (`gpt-4o`) with a system prompt that instructs the model to answer only from the context.
3. **`ask(query)`** — Orchestrates retrieve → generate, returns `{"context": "...", "response": "..."}`.

Authentication uses `DefaultAzureCredential` with AAD tokens (no API keys). This works both locally (via Azure CLI credential) and on AKS (via workload identity).

#### `app.py` — FastAPI HTTP API

Wraps `rag_agent.ask()` as a REST API:

- **`POST /ask`** — Accepts `{"query": "..."}`, returns `{"query": "...", "context": "...", "response": "..."}`.
- **`GET /health`** — Returns `{"status": "healthy"}` for Kubernetes liveness/readiness probes.

#### `evaluate_rag.py` — Evaluation Script

This script does two things:

**Step 1 — Run the agent on test data:**
- Reads `test_data.jsonl` (8 queries with ground truth).
- Calls the agent for each query (locally via `rag_agent.ask()` or remotely via HTTP if `AGENT_ENDPOINT` is set).
- Saves results to `eval_data_with_responses.jsonl`.

**Step 2 — Cloud evaluation via Foundry:**
- Connects to the Foundry project using `AIProjectClient`.
- Uploads the results JSONL as a dataset.
- Creates an evaluation definition with 5 evaluators:

| Evaluator | Type | What It Measures |
|-----------|------|-----------------|
| `groundedness` | AI-judged | Is the response supported by the retrieved context? |
| `relevance` | AI-judged | Does the response answer the user's question? |
| `coherence` | AI-judged | Is the response well-structured and logical? |
| `similarity` | AI-judged | How similar is the response to the ground truth? |
| `f1_score` | Computed | Token-level F1 overlap between response and ground truth |

- Creates an evaluation run, polls until complete, and prints results.
- Results are visible in the **Foundry portal → Evaluation tab**.

#### `setup_search.py` — Index Setup

Run once to create the `contoso-policies` index in Azure AI Search and upload 5 sample documents:
1. Refund Policy
2. Shipping Policy
3. Warranty Information
4. Privacy Policy
5. Loyalty Program

#### `test_data.jsonl` — Test Dataset

Contains 8 test queries covering the 5 policy areas:
```json
{"query": "What is Contoso's refund policy?", "ground_truth": "Contoso offers a 30-day full refund..."}
{"query": "How much does express shipping cost?", "ground_truth": "Express shipping costs $12.99..."}
...
```

### 4.3 Container & Kubernetes Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the agent container — Python 3.10 slim, installs deps, copies `rag_agent.py` + `app.py`, runs uvicorn on port 8000 |
| `k8s/service-account.yaml` | Kubernetes ServiceAccount with workload identity annotation (`${IDENTITY_CLIENT_ID}` placeholder) |
| `k8s/deployment.yaml` | Kubernetes Deployment — 1 replica, environment variables for Azure endpoints, health probes, resource limits |
| `k8s/service.yaml` | Kubernetes Service — LoadBalancer type, maps port 80 → 8000 |

#### How Workload Identity Works

The agent pod authenticates to Azure using **Workload Identity Federation** (no secrets stored in the cluster):

1. A **User Assigned Managed Identity** (`id-eval-agent`) is created with RBAC roles on AI Search and Azure OpenAI.
2. A **federated credential** links the Kubernetes service account (`eval-agent-sa`) to the managed identity.
3. When the pod starts, the AKS workload identity webhook injects token files into the pod.
4. `DefaultAzureCredential` in `rag_agent.py` automatically picks up the workload identity token.

### 4.4 Infrastructure Scripts

| File | Purpose |
|------|---------|
| `infra/setup-aks.sh` | Creates ACR, AKS cluster (1 node), managed identity, RBAC roles, federated credential, applies K8s service account |
| `infra/setup-github-oidc.sh` | Creates Azure AD app registration, service principal, federated credential for GitHub Actions OIDC, assigns RBAC roles |

### 4.5 CI/CD Pipeline

| File | Purpose |
|------|---------|
| `.github/workflows/deploy-and-evaluate.yaml` | GitHub Actions workflow — triggered on push to `main` or manual dispatch |

**Pipeline Steps:**
1. **Azure Login** — OIDC-based login using federated credential (no secrets).
2. **Build & Push** — Builds Docker image, pushes to ACR with commit SHA tag.
3. **Set AKS Context** — Connects to the AKS cluster.
4. **Deploy to AKS** — Applies K8s manifests with `envsubst` for variable substitution.
5. **Wait for Rollout** — Waits for the new pod to be ready.
6. **Get Agent Endpoint** — Retrieves the LoadBalancer external IP.
7. **Health Check** — Waits for the agent to respond on `/health`.
8. **Run Evaluation** — Installs Python deps, runs `evaluate_rag.py` against the deployed agent.
9. **Post Summary** — Writes a deployment summary to the GitHub Actions step summary.

---

## 5. Phase 1 — Run Locally

### 5.1 Clone & Set Up Python Environment

```bash
git clone https://github.com/<your-org>/evalagent.git
cd evalagent

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 5.2 Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your actual values:
```env
AZURE_SEARCH_ENDPOINT=https://<your-search-service>.search.windows.net
AZURE_SEARCH_INDEX=contoso-policies
AZURE_OPENAI_ENDPOINT=https://<your-openai>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_AI_PROJECT_ENDPOINT=https://<your-account>.services.ai.azure.com/api/projects/<your-project>
```

### 5.3 Populate the Search Index

```bash
python setup_search.py
```

Expected output:
```
Index 'contoso-policies' ready.
Uploaded 5 documents.
Done — your search index is ready.
```

### 5.4 Test the RAG Agent

```bash
python rag_agent.py
```

This runs a single test query ("What is the refund policy?") and prints the context and response.

### 5.5 Run Evaluation Locally

```bash
python evaluate_rag.py
```

This will:
1. Run all 8 test queries through the local agent.
2. Upload results to Foundry.
3. Create a cloud evaluation with 5 evaluators.
4. Poll and print results (takes ~1-2 minutes).

**Expected output:**
```
Running RAG pipeline locally for each test query...
  → What is Contoso's refund policy?
  → How much does express shipping cost?
  ...
Saved 8 results to eval_data_with_responses.jsonl

Uploading dataset 'rag-eval-xxxxxxxx'...
Creating evaluation definition...
Starting evaluation run...
Waiting for evaluation to complete...

EVALUATION RESULTS
============================================================
  Passed: 5
  Failed: 3
  Total:  8
```

View results in the [Foundry portal](https://ai.azure.com) → your project → Evaluation tab.

---

## 6. Phase 2 — Deploy to AKS

### 6.1 Provision AKS Infrastructure

Edit the variables at the top of `infra/setup-aks.sh` to match your environment, then run:

```bash
bash infra/setup-aks.sh
```

This creates (in order):
1. Resource group `rg-eval-agent-aks`
2. Azure Container Registry `<your-acr-name>`
3. AKS cluster `aks-eval-agent` (1 node, Standard_B2s, OIDC + workload identity enabled)
4. Managed identity `id-eval-agent`
5. RBAC: Search Index Data Reader, Cognitive Services OpenAI User
6. Federated credential linking K8s service account to managed identity
7. AKS kubeconfig + K8s service account

**On Windows**, run the equivalent commands in PowerShell (see the script comments for individual commands).

### 6.2 Build & Push the Docker Image

```bash
# Build in the cloud via ACR Build (no local Docker needed)
az acr build --registry <your-acr-name> --image eval-agent:v1 --image eval-agent:latest --no-logs .
```

### 6.3 Deploy to AKS

Substitute variables and apply manifests:

```bash
# Get the managed identity client ID
IDENTITY_CLIENT_ID=$(az identity show --name id-eval-agent \
  --resource-group rg-eval-agent-aks --query clientId -o tsv)

# Apply service account
sed "s|\${IDENTITY_CLIENT_ID}|${IDENTITY_CLIENT_ID}|g" k8s/service-account.yaml | kubectl apply -f -

# Apply deployment (substitute your ACR and endpoints)
export ACR_LOGIN_SERVER="<your-acr-name>.azurecr.io"
export AZURE_SEARCH_ENDPOINT="https://<your-search-service>.search.windows.net"
export AZURE_OPENAI_ENDPOINT="https://<your-openai-account>.openai.azure.com"
envsubst < k8s/deployment.yaml | kubectl apply -f -

# Apply service
kubectl apply -f k8s/service.yaml
```

### 6.4 Verify Deployment

```bash
# Wait for rollout
kubectl rollout status deployment/eval-agent --timeout=120s

# Get external IP
kubectl get svc eval-agent-svc

# Test health endpoint
curl http://<EXTERNAL_IP>/health

# Test agent
curl -X POST http://<EXTERNAL_IP>/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the refund policy?"}'
```

### 6.5 Run Evaluation Against Deployed Agent

```bash
AGENT_ENDPOINT=http://<EXTERNAL_IP> python evaluate_rag.py
```

---

## 7. Phase 3 — GitHub Actions CI/CD

### 7.1 Set Up GitHub OIDC

Edit `infra/setup-github-oidc.sh` variables, then run:

```bash
bash infra/setup-github-oidc.sh
```

This creates:
1. Azure AD app registration `github-evalagent-deploy`
2. Service principal
3. Federated credential for `repo:<owner>/evalagent:ref:refs/heads/main`
4. RBAC roles: Contributor (AKS RG), AcrPush (ACR), Azure AI Developer (Foundry), Cognitive Services OpenAI User (OpenAI)

> **Important:** You also need to assign these additional roles on the Foundry account for the evaluation API:
> - `Cognitive Services OpenAI Contributor`
> - `Cognitive Services User`

### 7.2 Create GitHub Repository

```bash
cd evalagent
git init
git add -A
git commit -m "Initial commit"
gh repo create <your-org>/evalagent --public --source=. --remote=origin --push
git branch -M main
git push origin main
gh repo edit <your-org>/evalagent --default-branch main
```

### 7.3 Configure GitHub Secrets & Variables

The `setup-github-oidc.sh` script prints the values to set. Use the GitHub CLI:

**Secrets** (Settings → Secrets → Actions):
```bash
gh secret set AZURE_CLIENT_ID --body "<app-client-id>"
gh secret set AZURE_TENANT_ID --body "<tenant-id>"
gh secret set AZURE_SUBSCRIPTION_ID --body "<subscription-id>"
```

**Variables** (Settings → Variables → Actions):
```bash
gh variable set ACR_NAME --body "<your-acr-name>"
gh variable set AKS_CLUSTER_NAME --body "aks-eval-agent"
gh variable set AKS_RESOURCE_GROUP --body "rg-eval-agent-aks"
gh variable set IDENTITY_CLIENT_ID --body "<managed-identity-client-id>"
gh variable set AZURE_SEARCH_ENDPOINT --body "https://<your-search-service>.search.windows.net"
gh variable set AZURE_OPENAI_ENDPOINT --body "https://<your-openai-account>.openai.azure.com"
gh variable set AZURE_AI_PROJECT_ENDPOINT --body "https://<your-foundry-account>.services.ai.azure.com/api/projects/<your-project>"
gh variable set AZURE_OPENAI_DEPLOYMENT --body "gpt-4o"
```

### 7.4 Trigger the Pipeline

The pipeline runs automatically on every push to `main`. To trigger manually:

```bash
gh workflow run "Deploy Agent & Run Evaluation" --ref main
```

Monitor the run:
```bash
gh run watch --exit-status
```

### 7.5 What the Pipeline Does

On every push to `main`:

```
Push to main
    │
    ▼
┌─── Azure Login (OIDC, no secrets) ───┐
│                                       │
├─── Build Docker Image ───────────────┤
│   docker build → ACR push (:sha)     │
│                                       │
├─── Deploy to AKS ───────────────────┤
│   envsubst → kubectl apply           │
│   kubectl rollout status              │
│                                       │
├─── Wait for Health ──────────────────┤
│   curl /health (retry 12×)           │
│                                       │
├─── Run Evaluation ───────────────────┤
│   python evaluate_rag.py             │
│   → 8 queries against deployed agent │
│   → Upload to Foundry                │
│   → 5 evaluators score each query    │
│                                       │
└─── Post Summary ─────────────────────┘
    Results visible in Foundry portal
```

---

## 8. Testing & Validation

### 8.1 Local Testing

```bash
# Test the agent directly
python rag_agent.py

# Run the FastAPI server locally
uvicorn app:app --host 0.0.0.0 --port 8000

# In another terminal, test the API
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "How much does express shipping cost?"}'

# Run evaluation locally
python evaluate_rag.py
```

### 8.2 AKS Testing

```bash
# Check pod status
kubectl get pods -l app=eval-agent

# Check pod logs
kubectl logs -l app=eval-agent --tail=50

# Check service
kubectl get svc eval-agent-svc

# Test deployed agent
EXTERNAL_IP=$(kubectl get svc eval-agent-svc -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$EXTERNAL_IP/health
curl -X POST http://$EXTERNAL_IP/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What warranty does Contoso offer?"}'

# Run evaluation against deployed agent
AGENT_ENDPOINT=http://$EXTERNAL_IP python evaluate_rag.py
```

### 8.3 Pipeline Testing

```bash
# Trigger the pipeline manually
gh workflow run "Deploy Agent & Run Evaluation" --ref main

# Watch it run
gh run list --workflow="deploy-and-evaluate.yaml" --limit 5
gh run watch --exit-status

# View failed step logs
gh run view <run-id> --log-failed

# View full logs for a specific job
gh run view <run-id> --log
```

### 8.4 Viewing Evaluation Results

1. Go to [Azure AI Foundry portal](https://ai.azure.com).
2. Navigate to your project.
3. Click the **Evaluation** tab.
4. You'll see each evaluation run with:
   - Overall pass/fail counts
   - Per-evaluator scores (groundedness, relevance, coherence, similarity, F1)
   - Row-level detail for each test query

---

## 9. Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `DefaultAzureCredential failed` locally | Azure CLI not logged in or token expired | Run `az login` |
| `DefaultAzureCredential failed` on AKS | Workload identity misconfigured | Check service account annotations, verify federated credential |
| `AADSTS53003: Conditional Access` on AKS | Enterprise CA policy blocking managed identity tokens | Check with your Azure AD admin; may need policy exclusion for the managed identity |
| `UnicodeEncodeError: 'charmap' codec` | Windows terminal encoding issue | Set `$env:PYTHONIOENCODING = "utf-8"` before running Python scripts |
| `401 PermissionDenied` on evaluation API | Missing RBAC roles on Foundry account | Assign `Cognitive Services OpenAI Contributor` + `Cognitive Services User` roles |
| Pipeline fails at Azure Login | Secrets not set or OIDC federated credential misconfigured | Verify `gh secret list`, check federated credential subject matches `repo:owner/repo:ref:refs/heads/main` |
| Agent returns "I don't have that information" | Query doesn't match indexed documents well | This is expected for some queries — the RAG agent only answers from retrieved context |
| ACR build fails with encoding error | Known Azure CLI bug on Windows | Use `--no-logs` flag: `az acr build --no-logs ...` |
| Service account placeholder not substituted | Workflow applied YAML without `envsubst` | Ensure the workflow uses `envsubst < k8s/service-account.yaml \| kubectl apply -f -` |

### Useful Debug Commands

```bash
# Check all Azure role assignments for a principal
az role assignment list --assignee <principal-id> -o table

# Check K8s service account annotations
kubectl get sa eval-agent-sa -o yaml

# Check pod environment variables
kubectl exec -it <pod-name> -- env | grep AZURE

# Check K8s events for errors
kubectl get events --sort-by='.lastTimestamp' --field-selector type=Warning

# View Foundry project details
az cognitiveservices account show --name <account> --resource-group <rg>
```

### RBAC Roles Summary

| Principal | Role | Scope | Purpose |
|-----------|------|-------|---------|
| **Your user** | Search Index Data Contributor | AI Search service | Create index, upload docs |
| **Your user** | Cognitive Services OpenAI User | Azure OpenAI account | Call gpt-4o locally |
| **Your user** | Azure AI Developer | Foundry account | Create evaluations locally |
| **Managed Identity** (AKS pod) | Search Index Data Reader | AI Search service | Query the index from AKS |
| **Managed Identity** (AKS pod) | Cognitive Services OpenAI User | Azure OpenAI account | Call gpt-4o from AKS |
| **GitHub Actions SP** | Contributor | AKS resource group | Deploy to AKS |
| **GitHub Actions SP** | AcrPush | Container Registry | Push Docker images |
| **GitHub Actions SP** | Azure AI Developer | Foundry account | Upload datasets |
| **GitHub Actions SP** | Cognitive Services OpenAI Contributor | Foundry account | Create evaluations |
| **GitHub Actions SP** | Cognitive Services User | Foundry account | Access AI services data plane |
| **GitHub Actions SP** | Cognitive Services OpenAI User | Azure OpenAI account | Run evaluators (model-as-judge) |

---

## Quick Reference

| Resource | Name | Region |
|----------|------|--------|
| Search Service | `<your-search-service>` | eastus |
| OpenAI Account | `<your-openai-account>` | eastus2 |
| Foundry Account | `<your-foundry-account>` | eastus2 |
| Container Registry | `<your-acr-name>` | eastus2 |
| AKS Cluster | `aks-eval-agent` | eastus2 |
| Managed Identity | `id-eval-agent` | eastus2 |
| GitHub Repo | `<your-org>/evalagent` | — |
| GitHub Actions App | `github-evalagent-deploy` | — |
