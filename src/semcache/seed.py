"""The templates already listed on templates.aiven.io (snapshot, 2026-10-01)."""

BASE = "https://templates.aiven.io"

# GitHub orgs and users whose public repos are all put in the catalog at startup, whatever a
# search returns. Add a name here to have its projects suggested alongside search results.
SEED_OWNERS = ["Aiven-Labs"]

# (name, description, aiven services, tags)
_T = [
    ("n8n", "Minimal deployment of n8n and the traefik web apps", [], ["n8n", "traefik"]),
    (
        "LiteLLM",
        "AI gateway with admin UI, model-provider credentials, virtual keys",
        ["postgresql", "valkey"],
        ["ai-gateway", "llm"],
    ),
    (
        "Metabase",
        "Self-hosted analytics with sample database",
        ["postgresql"],
        ["analytics", "dashboards"],
    ),
    (
        "Streamlit",
        "Generic app with charts, filters, searchable table",
        ["postgresql"],
        ["dashboards", "python"],
    ),
    (
        "LangGraph",
        "Python/FastAPI app using LangGraph with draft-review workflow",
        ["postgresql"],
        ["fastapi", "workflow-orchestration"],
    ),
    (
        "RAG & OpenSearch",
        "FastAPI service for chunking, embedding, indexing documents",
        ["opensearch"],
        ["ai", "rag"],
    ),
    (
        "Langfuse",
        "LLM observability with the Langfuse web UI and worker",
        ["postgresql", "valkey"],
        ["llm", "observability"],
    ),
    ("MCP & Proxy", "FastMCP implementation with Caddy reverse proxy", [], ["mcp", "caddy"]),
    (
        "Temporal",
        "Self-hosted server, web UI, worker example",
        ["postgresql"],
        ["workflow-orchestration"],
    ),
    ("Airflow", "Workflow orchestration deployment", [], ["airflow"]),
    ("Hasura", "GraphQL engine v2 with console", ["postgresql"], ["graphql"]),
    ("Umami", "Privacy-first analytics platform without cookies", [], ["analytics"]),
    (
        "FastAPI + PG + Valkey",
        "Sample app with database and cache",
        ["postgresql", "valkey"],
        ["fastapi", "getting-started"],
    ),
    (
        "CLIP Multimodal Search",
        "Image search via text embeddings with pgvector",
        ["postgresql"],
        ["search", "embeddings"],
    ),
    ("Jaeger", "Distributed tracing deployment", [], ["tracing"]),
    (
        "Inventory Demo",
        "Multi-service product inventory system with React, Node.js, Go",
        ["postgresql", "valkey"],
        ["react", "go"],
    ),
    (
        "Kafka Anomaly Detection",
        "Streams example detecting out-of-range values",
        ["kafka"],
        ["java", "avro"],
    ),
    (
        "Kafka Streams",
        "Real-time message processing with schema registry",
        ["kafka"],
        ["java", "avro"],
    ),
    (
        "Community Event Search",
        "Event mapping across Meetup and Luma platforms",
        ["postgresql", "kafka"],
        ["events"],
    ),
    (
        "BetterDB Monitor",
        "Monitoring layer for Valkey/Redis with slowlogs",
        ["valkey"],
        ["monitoring", "prometheus"],
    ),
    ("Runs on Runtime", "Directory site itself", [], ["static-site"]),
    (
        "Valkey Admin",
        "Admin interface for Valkey service instances",
        ["valkey"],
        ["caching", "observability"],
    ),
    ("PGAdmin", "PostgreSQL administration dashboard", ["postgresql"], ["admin-portal"]),
    (
        "Keycloak",
        "Ready-to-deploy Keycloak + PostgreSQL 18 template",
        ["postgresql"],
        ["iam", "sso"],
    ),
    ("Kafbat UI", "Kafka cluster interface", ["kafka"], ["ui"]),
]

TEMPLATES = [
    {"name": n, "description": d, "services": s, "tags": t, "url": BASE} for n, d, s, t in _T
]
