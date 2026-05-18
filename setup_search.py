"""
setup_search.py — Create an Azure AI Search index and upload sample documents.

Run once:  python setup_search.py
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
)

load_dotenv()

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "contoso-policies")

# ── Sample knowledge base (company policies) ────────────────────────────────
DOCUMENTS = [
    {
        "id": "1",
        "title": "Refund Policy",
        "content": (
            "Contoso offers a 30-day full refund on all products purchased "
            "through our website. Items must be unused and in original packaging. "
            "Refunds are processed within 5-7 business days after we receive the "
            "returned item. Digital products are non-refundable once the download "
            "link has been accessed."
        ),
        "category": "returns",
    },
    {
        "id": "2",
        "title": "Shipping Policy",
        "content": (
            "Standard shipping takes 5-7 business days and is free for orders "
            "over $50. Express shipping (2-3 business days) costs $12.99. "
            "Overnight shipping is available for $24.99. All orders are shipped "
            "via FedEx. International shipping is available to 40 countries with "
            "delivery in 10-15 business days."
        ),
        "category": "shipping",
    },
    {
        "id": "3",
        "title": "Warranty Information",
        "content": (
            "All Contoso electronics come with a 2-year manufacturer warranty "
            "covering defects in materials and workmanship. The warranty does not "
            "cover accidental damage, water damage, or unauthorized repairs. "
            "To file a warranty claim, contact support@contoso.com with your "
            "order number and a description of the issue."
        ),
        "category": "warranty",
    },
    {
        "id": "4",
        "title": "Privacy Policy",
        "content": (
            "Contoso collects only the personal data necessary to fulfill orders: "
            "name, email, shipping address, and payment information. We never sell "
            "customer data to third parties. Data is encrypted at rest and in "
            "transit using AES-256 and TLS 1.3. Customers can request full data "
            "deletion by emailing privacy@contoso.com."
        ),
        "category": "privacy",
    },
    {
        "id": "5",
        "title": "Loyalty Program",
        "content": (
            "Contoso Rewards members earn 1 point per dollar spent. Points can be "
            "redeemed at 100 points = $5 discount. Gold tier members (500+ points "
            "per year) receive free express shipping and early access to sales. "
            "Points expire after 12 months of account inactivity."
        ),
        "category": "loyalty",
    },
]

# ── Create or update the index ──────────────────────────────────────────────
credential = DefaultAzureCredential()
index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

fields = [
    SimpleField(name="id", type=SearchFieldDataType.String, key=True),
    SearchableField(name="title", type=SearchFieldDataType.String),
    SearchableField(name="content", type=SearchFieldDataType.String),
    SimpleField(name="category", type=SearchFieldDataType.String, filterable=True),
]

index = SearchIndex(name=INDEX_NAME, fields=fields)
index_client.create_or_update_index(index)
print(f"Index '{INDEX_NAME}' ready.")

# ── Upload documents ────────────────────────────────────────────────────────
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
)
result = search_client.upload_documents(documents=DOCUMENTS)
print(f"Uploaded {len(result)} documents.")
print("Done — your search index is ready.")
