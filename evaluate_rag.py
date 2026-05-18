"""
evaluate_rag.py — Evaluate a RAG agent (local or deployed) using the Microsoft
Foundry cloud evaluation API (OpenAI Evals), so results appear in the new
Foundry portal's Evaluation tab.

Modes:
  - Local:    Calls rag_agent.ask() directly (default)
  - Remote:   Set AGENT_ENDPOINT=http://<ip> to call a deployed agent via HTTP

Steps:
  1. Run each test query through the agent (local or remote).
  2. Save results to a JSONL file.
  3. Upload as a Foundry dataset.
  4. Create a cloud evaluation + run using built-in evaluators.
  5. Poll and print results.

Usage:  python evaluate_rag.py
"""

import json
import os
import time
import uuid
from pprint import pprint
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
    SourceFileID,
)

load_dotenv(override=True)

# ── Config ──────────────────────────────────────────────────────────────────
endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
model_deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AGENT_ENDPOINT = os.environ.get("AGENT_ENDPOINT")  # e.g. http://<aks-ip>

TEST_DATA = "test_data.jsonl"
EVAL_OUTPUT = "eval_data_with_responses.jsonl"


def call_agent(query: str) -> dict:
    """Call the RAG agent — local import or remote HTTP depending on AGENT_ENDPOINT."""
    if AGENT_ENDPOINT:
        import requests
        resp = requests.post(
            f"{AGENT_ENDPOINT.rstrip('/')}/ask",
            json={"query": query},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    else:
        from rag_agent import ask
        return ask(query)


def run_rag_pipeline():
    """Call the RAG agent for each test query and save results to JSONL."""
    if AGENT_ENDPOINT:
        print(f"Running queries against deployed agent at {AGENT_ENDPOINT}...")
    else:
        print("Running RAG pipeline locally for each test query...")
    results = []
    with open(TEST_DATA, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line.strip())
            query = row["query"]
            ground_truth = row.get("ground_truth", "")
            print(f"  → {query}")
            answer = call_agent(query)
            results.append({
                "query": query,
                "response": answer["response"],
                "context": answer["context"],
                "ground_truth": ground_truth,
            })

    with open(EVAL_OUTPUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"Saved {len(results)} results to {EVAL_OUTPUT}\n")
    return results


def run_cloud_evaluation():
    """Upload results + create a cloud evaluation via the OpenAI Evals API."""
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=endpoint, credential=credential)

    # 1. Upload the dataset
    dataset_name = f"rag-eval-{uuid.uuid4().hex[:8]}"
    print(f"Uploading dataset '{dataset_name}'...")
    dataset = project_client.datasets.upload_file(
        name=dataset_name,
        version="1",
        file_path=EVAL_OUTPUT,
    )
    data_id = dataset.id
    print(f"  Dataset ID: {data_id}\n")

    # 2. Get OpenAI client (supports evals API)
    client = project_client.get_openai_client()

    # 3. Define the data schema
    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "response": {"type": "string"},
                "context": {"type": "string"},
                "ground_truth": {"type": "string"},
            },
            "required": ["query", "response", "context", "ground_truth"],
        },
    )

    # 4. Define evaluators (testing criteria)
    testing_criteria = [
        {
            "type": "azure_ai_evaluator",
            "name": "groundedness",
            "evaluator_name": "builtin.groundedness",
            "initialization_parameters": {
                "deployment_name": model_deployment_name,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "context": "{{item.context}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "relevance",
            "evaluator_name": "builtin.relevance",
            "initialization_parameters": {
                "deployment_name": model_deployment_name,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "context": "{{item.context}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "coherence",
            "evaluator_name": "builtin.coherence",
            "initialization_parameters": {
                "deployment_name": model_deployment_name,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "similarity",
            "evaluator_name": "builtin.similarity",
            "initialization_parameters": {
                "deployment_name": model_deployment_name,
            },
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
                "ground_truth": "{{item.ground_truth}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "f1_score",
            "evaluator_name": "builtin.f1_score",
            "data_mapping": {
                "response": "{{item.response}}",
                "ground_truth": "{{item.ground_truth}}",
            },
        },
    ]

    # 5. Create the evaluation definition
    print("Creating evaluation definition...")
    eval_object = client.evals.create(
        name="RAG Groundedness Demo",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"  Eval ID: {eval_object.id}\n")

    # 6. Create a run against the uploaded dataset
    print("Starting evaluation run...")
    eval_run = client.evals.runs.create(
        eval_id=eval_object.id,
        name="rag-eval-run",
        data_source=CreateEvalJSONLRunDataSourceParam(
            type="jsonl",
            source=SourceFileID(
                type="file_id",
                id=data_id,
            ),
        ),
    )
    print(f"  Run ID: {eval_run.id}")
    print(f"  Status: {eval_run.status}\n")

    # 7. Poll for completion
    print("Waiting for evaluation to complete...")
    while True:
        run = client.evals.runs.retrieve(
            run_id=eval_run.id, eval_id=eval_object.id
        )
        if run.status in ("completed", "failed", "canceled"):
            break
        print(f"  Status: {run.status} — waiting 10s...")
        time.sleep(10)

    print(f"\nFinal status: {run.status}")

    if run.status == "failed":
        print(f"Evaluation failed: {run}")
        return

    # 8. Print results
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)

    if hasattr(run, "result_counts") and run.result_counts:
        print(f"  Passed: {run.result_counts.passed}")
        print(f"  Failed: {run.result_counts.failed}")
        print(f"  Total:  {run.result_counts.total}")

    if hasattr(run, "per_testing_criteria_results") and run.per_testing_criteria_results:
        print("\nPer-evaluator results:")
        for cr in run.per_testing_criteria_results:
            label = getattr(cr, "name", None) or getattr(cr, "testing_criteria", "unknown")
            passed = getattr(cr, "passed", "?")
            failed = getattr(cr, "failed", "?")
            rate = getattr(cr, "pass_rate", None)
            rate_str = f"  pass_rate={rate:.2f}" if rate is not None else ""
            print(f"  {str(label):20s}{rate_str}  passed={passed}  failed={failed}")

    # Retrieve row-level output
    output_items = list(
        client.evals.runs.output_items.list(
            run_id=run.id, eval_id=eval_object.id
        )
    )
    if output_items:
        print(f"\nRow-level details ({len(output_items)} items):")
        print("-" * 60)
        for item in output_items:
            pprint(item.results, width=120)
            print()

    report_url = getattr(run, "report_url", None)
    if report_url:
        print(f"\nView in Foundry portal: {report_url}")
    else:
        print("\nCheck the Foundry portal Evaluation tab for results.")


if __name__ == "__main__":
    run_rag_pipeline()
    run_cloud_evaluation()
