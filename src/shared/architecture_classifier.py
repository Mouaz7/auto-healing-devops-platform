"""Architecture layer classifier — identifies which part of the system
contains the failing code so the AI can apply layer-appropriate fixes.

Combines four signals to classify failures across:
  • 6 main layers (FRONTEND / BACKEND / DATABASE / INFRA / TESTS / MOBILE)
  • 50+ programming languages
  • 100+ frameworks and runtimes
  • 30+ sub-layer specialisations (API endpoint, Migration, Auth, etc.)
  • Cross-layer detection (e.g. API call hitting a DB error)
  • Severity boosts for high-risk areas (migrations, auth, CI/CD)

Returns confidence-scored classification; the highest-scoring layer wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ArchLayer(str, Enum):
    FRONTEND = "FRONTEND"
    BACKEND  = "BACKEND"
    DATABASE = "DATABASE"
    INFRA    = "INFRA"
    TESTS    = "TESTS"
    MOBILE   = "MOBILE"
    DATA_ML  = "DATA_ML"
    UNKNOWN  = "UNKNOWN"


@dataclass
class LayerClassification:
    layer:          ArchLayer
    confidence:     float
    reason:         str
    risk_note:      str
    fix_hint:       str
    sub_layer:      str = ""
    framework:      str = ""
    language:       str = ""
    runtime:        str = ""
    cross_layers:   list[str] = field(default_factory=list)
    severity_boost: float = 0.0
    tags:           list[str] = field(default_factory=list)


# ============================================================================ #
# 1. PATH PATTERNS — most reliable signal (weight 3.0)                          #
# ============================================================================ #

_PATH_PATTERNS: dict[ArchLayer, list[re.Pattern]] = {
    ArchLayer.FRONTEND: [
        re.compile(r"/(frontend|client|web|ui|app/components?|src/components?|src/pages?|src/views?|public|static|assets)/", re.I),
        re.compile(r"\.(tsx|jsx|vue|svelte|astro|html|htm|css|scss|sass|less|styl|pcss|module\.css)$", re.I),
        re.compile(r"(package\.json|next\.config|nuxt\.config|vite\.config|webpack\.config|rollup\.config|svelte\.config|astro\.config|remix\.config|tailwind\.config)", re.I),
        re.compile(r"\.(stories|story)\.(jsx?|tsx?)$", re.I),
    ],
    ArchLayer.BACKEND: [
        re.compile(r"/(backend|server|api|services?|controllers?|routes?|handlers?|middleware|repositories|repos|adapters|interactors|use[_-]?cases?|domain|core|usecases)/", re.I),
        re.compile(r"\.(py|go|rs|rb|php|cs|fs|fsi|fsx|ml|mli|hs|lhs|ex|exs|erl|hrl|lua|pl|pm|jl|cr|nim|zig|d|v)$", re.I),
        re.compile(r"\.(java|kt|kts|scala|sc|sbt|groovy|gradle)$", re.I),
        re.compile(r"\.(c|cpp|cc|cxx|h|hpp|hh|hxx)$", re.I),
        re.compile(r"\.(go\.mod|go\.sum|Cargo\.toml|Gemfile|composer\.json|requirements\.txt|pyproject\.toml|setup\.py|build\.sbt|pom\.xml)", re.I),
    ],
    ArchLayer.DATABASE: [
        re.compile(r"/(migrations?|db|database|schemas?|models?|alembic|liquibase|flyway|sqitch|prisma|drizzle)/", re.I),
        re.compile(r"\.(sql|ddl|dml|psql|cql|cypher|sparql|graphql|gql|prisma|edgeql)$", re.I),
        re.compile(r"(schema\.sql|seeds?\.sql|fixtures?\.sql|alembic\.ini|liquibase\.properties|knexfile|sequelizerc)", re.I),
    ],
    ArchLayer.INFRA: [
        re.compile(r"(Dockerfile|docker-compose|\.dockerignore|\.containerignore|Containerfile|Earthfile)", re.I),
        re.compile(r"/(\.github|\.gitlab|ci|deploy|terraform|pulumi|cdk|k8s|kubernetes|helm|kustomize|ansible|chef|puppet|salt)/", re.I),
        re.compile(r"\.(yml|yaml|tf|tfvars|hcl|nomad|jsonnet|libsonnet|cue)$", re.I),
        re.compile(r"(Jenkinsfile|\.gitlab-ci|\.circleci|\.travis|\.drone|bitbucket-pipelines|azure-pipelines|cloudbuild|buildspec)", re.I),
        re.compile(r"(Makefile|justfile|Taskfile|magefile)", re.I),
        re.compile(r"\.(nix|flake)$", re.I),
    ],
    ArchLayer.TESTS: [
        re.compile(r"/(tests?|__tests__|spec|specs?|e2e|integration|cypress|playwright|selenium|puppeteer|features?)/", re.I),
        re.compile(r"(test_|_test|\.test\.|\.spec\.|_spec\.)", re.I),
        re.compile(r"\.(feature|story\.tsx?|test\.tsx?|spec\.tsx?|cy\.tsx?)$", re.I),
        re.compile(r"(conftest\.py|jest\.config|vitest\.config|karma\.conf|playwright\.config|cypress\.config)", re.I),
    ],
    ArchLayer.MOBILE: [
        # Path must clearly indicate mobile project — not just .java/.kt extensions
        re.compile(r"/(android|ios|mobile|react-native|flutter|expo|RCT)/", re.I),
        # Mobile-only extensions
        re.compile(r"\.(swift|m|mm|dart|xaml)$", re.I),
        # Mobile-specific filenames
        re.compile(r"(AppDelegate|Info\.plist|AndroidManifest\.xml|Podfile|pubspec\.yaml|app\.json|expo\.json|MainActivity)", re.I),
    ],
    ArchLayer.DATA_ML: [
        re.compile(r"/(notebooks?|ml|models?|training|datasets?|features?|pipelines?|dags?|airflow|spark|flink)/", re.I),
        re.compile(r"\.(ipynb|parquet|avro|feather|h5|pkl|pickle|joblib|onnx|pb|tflite|safetensors)$", re.I),
        re.compile(r"(dvc\.yaml|mlflow|kubeflow|metaflow|prefect|dagster)", re.I),
    ],
}


# ============================================================================ #
# 2. CONTENT HINTS — second-most reliable (weight 2.0)                          #
# ============================================================================ #

_CONTENT_HINTS: dict[ArchLayer, list[str]] = {
    ArchLayer.FRONTEND: [
        # React
        "import React", "from 'react'", "from \"react\"", "useState", "useEffect", "useReducer",
        "useContext", "useMemo", "useCallback", "ReactDOM", "createRoot", "JSX.Element",
        # Vue
        "from 'vue'", "Vue.component", "createApp", "<template>", "<script setup>", "defineComponent",
        # Angular
        "@angular/", "@Component", "@NgModule", "@Injectable", "ngOnInit",
        # Svelte / Solid / Astro / Qwik
        "from 'svelte'", "from 'solid-js'", "from 'astro'", "from '@builder.io/qwik'",
        # Browser-native
        "document.getElementById", "document.querySelector", "addEventListener",
        "window.location", "localStorage", "sessionStorage", "fetch(",
        # CSS-in-JS
        "styled-components", "emotion", "stitches", "vanilla-extract",
        # Build / bundler
        "import.meta.env", "process.env.NEXT_PUBLIC", "process.env.VITE_",
    ],
    ArchLayer.BACKEND: [
        # Python web frameworks
        "from flask", "from fastapi", "from django", "from starlette", "from quart",
        "from sanic", "from tornado", "from aiohttp", "from bottle", "from pyramid",
        # Node
        "import express", "require('express')", "import koa", "from 'koa'", "import fastify",
        "import nestjs", "@nestjs/", "import hapi", "import restify",
        # Go
        "package main", "func main()", "net/http", "gin.Default", "echo.New", "fiber.New",
        "gorilla/mux", "chi.NewRouter",
        # Rust
        "actix_web", "rocket::launch", "warp::Filter", "axum::Router", "tide::new",
        # Java/Kotlin/Scala
        "@RestController", "@RequestMapping", "@SpringBootApplication", "spring.boot",
        "javalin", "ktor", "akka.http", "play.api",
        # Ruby
        "Rails.application", "Sinatra::Base", "Hanami", "Rack::App",
        # PHP
        "<?php", "Laravel", "Symfony", "namespace App\\Http\\Controllers",
        # Elixir
        "Phoenix.Controller", "Plug.Router", "use Phoenix",
        # C#
        ".NET Core", "ASP.NET", "[ApiController]", "WebApplication.Create",
    ],
    ArchLayer.DATABASE: [
        # SQL
        "CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX", "ALTER COLUMN",
        "FOREIGN KEY", "PRIMARY KEY", "UNIQUE INDEX", "TRUNCATE", "GRANT", "REVOKE",
        # Drivers / ORMs Python
        "psycopg2", "asyncpg", "sqlalchemy", "import sqlite3", "from peewee",
        "from tortoise", "from gino", "databases.Database", "from edgedb",
        # JS/TS
        "Sequelize", "TypeORM", "Prisma", "Drizzle", "Knex", "MikroORM", "Mongoose",
        # Java
        "javax.persistence", "@Entity", "Hibernate", "JPA",
        # Migration tools
        "alembic", "op.create_table", "op.add_column", "flyway", "liquibase",
        # NoSQL
        "MongoClient", "pymongo", "redis.Redis", "from cassandra", "elasticsearch",
        "DynamoDB", "boto3.resource('dynamodb')", "neo4j.GraphDatabase",
    ],
    ArchLayer.INFRA: [
        # Docker
        "FROM ubuntu", "FROM python", "FROM node", "FROM golang", "FROM alpine",
        "RUN apt-get", "RUN apk add", "ENTRYPOINT", "CMD [", "EXPOSE ",
        # Compose / K8s
        "version: '3", "services:", "apiVersion:", "kind: Deployment", "kind: Service",
        "kind: StatefulSet", "kind: ConfigMap", "kind: Secret", "metadata:", "spec:",
        # Terraform / Pulumi / CDK
        "resource \"", "provider \"", "terraform {", "data \"",
        "pulumi.export", "import * as aws from", "Stack ",
        # CI
        "uses: actions/", "runs-on:", "stage(", "pipeline {", "stages {",
        # Helm
        "{{ .Values.", "{{ .Release.", "Chart.yaml",
        # Ansible
        "- hosts:", "ansible_become",
    ],
    ArchLayer.TESTS: [
        # Python
        "import pytest", "import unittest", "from unittest", "@pytest.fixture",
        "@pytest.mark", "def test_", "assert_called_with", "Mock(", "MagicMock(",
        # JS/TS
        "describe(", "it(", "test(", "expect(", "vi.mock(", "jest.mock(",
        "beforeEach(", "afterEach(", "setUp(", "tearDown(",
        # E2E
        "cy.get(", "cy.visit(", "page.goto(", "page.click(",
        # BDD
        "Given(", "When(", "Then(", "Feature:", "Scenario:",
        # Java
        "@Test", "TestCase", "assertEquals", "assertThrows", "Mockito",
    ],
    ArchLayer.MOBILE: [
        # React Native
        "from 'react-native'", "import { View", "import { Text",
        # Flutter
        "import 'package:flutter", "Widget build(", "StatefulWidget", "MaterialApp",
        # iOS Swift
        "import UIKit", "import SwiftUI", "UIViewController", "@State var",
        # Android
        "import android.", "AppCompatActivity", "@Composable", "androidx.",
        # Xamarin / MAUI
        "using Xamarin", "Microsoft.Maui",
    ],
    ArchLayer.DATA_ML: [
        # ML frameworks
        "import torch", "import tensorflow", "from sklearn", "import keras",
        "from transformers", "import jax", "from xgboost", "from lightgbm",
        # Data
        "import pandas", "import numpy", "import polars", "from pyspark",
        # Notebook
        "%matplotlib", "%%cell", "ipython.display",
        # Pipelines
        "from airflow", "@task", "@dag", "import prefect", "import dagster",
        "from kfp", "import mlflow",
    ],
}


# ============================================================================ #
# 3. ERROR MESSAGE HINTS — fallback signal (weight 1.5)                         #
# ============================================================================ #

_ERROR_HINTS: dict[ArchLayer, list[str]] = {
    ArchLayer.FRONTEND: [
        "Cannot read property", "Cannot read properties", "is not defined",
        "Hydration failed", "Hooks can only be called", "Maximum update depth",
        "Invalid hook call", "useState is not a function", "Element type is invalid",
        "Failed to compile", "Module not found", "Unexpected token <",
        "Cannot find module 'react", "JSX expressions must have one parent",
    ],
    ArchLayer.BACKEND: [
        "500 Internal Server Error", "502 Bad Gateway", "503 Service Unavailable",
        "504 Gateway Timeout", "Unhandled exception", "TimeoutError",
        "ConnectionRefusedError", "ValidationError", "DependencyError",
        "ASGI", "WSGI", "Address already in use",
        "Cannot start server", "Port .* in use",
    ],
    ArchLayer.DATABASE: [
        "psycopg2.OperationalError", "psycopg2.IntegrityError", "IntegrityError",
        "OperationalError", "duplicate key", "foreign key violation",
        "no such table", "no such column", "syntax error at or near",
        "deadlock detected", "connection refused", "too many connections",
        "constraint violation", "could not connect to server",
        "MongoNetworkError", "MongoServerError", "ClusterTimeoutException",
        "Redis.exceptions", "WrongDocumentVersion",
    ],
    ArchLayer.INFRA: [
        "port is already allocated", "no space left on device",
        "image not found", "container exited", "permission denied",
        "Network unreachable", "DNS resolution failed", "OOMKilled",
        "ImagePullBackOff", "CrashLoopBackOff", "manifest unknown",
        "failed to compute cache key", "unable to connect to docker daemon",
        "Helm install failed", "terraform apply", "kubectl apply",
        "no such host", "x509: certificate",
    ],
    ArchLayer.TESTS: [
        "AssertionError", "FAILED tests/", "test failed",
        "Mock.assert", "should equal", "to be", "assertion failed",
        "expect(received)", "Expected to be called",
        "Test suite failed to run", "Snapshot test failed",
        "0 passed", "0 passing",
    ],
    ArchLayer.MOBILE: [
        "RCT_EXPORT", "NSException", "EXC_BAD_ACCESS",
        "UIViewControllerHierarchyInconsistency",
        "RenderFlex overflowed", "setState() called after dispose",
        "ANR in", "Application Not Responding",
        "ld: framework not found", "Undefined symbol",
    ],
    ArchLayer.DATA_ML: [
        "CUDA out of memory", "RuntimeError: Expected all tensors",
        "shape mismatch", "loss is nan", "loss is inf",
        "DataLoader worker", "OOM during epoch",
        "checkpoint not found", "torch.cuda.OutOfMemoryError",
    ],
}


# ============================================================================ #
# 4. RISK NOTES — what reviewers should watch out for                           #
# ============================================================================ #

_RISK_NOTES: dict[ArchLayer, str] = {
    ArchLayer.FRONTEND:
        "Visual or interaction regression possible — manually smoke-test responsive "
        "layouts and main user flows. Watch for hydration mismatches if SSR is used.",
    ArchLayer.BACKEND:
        "API contract may have changed — re-test all consuming clients (frontend, "
        "mobile, integrations). Verify status codes and response payloads.",
    ArchLayer.DATABASE:
        "⚠️ HIGH RISK — schema or data changes can be irreversible. Run on a staging "
        "copy first, verify backups exist, prepare rollback SQL, take a snapshot "
        "before applying to production.",
    ArchLayer.INFRA:
        "Build/deploy pipeline affected — verify the next deploy on a non-prod "
        "environment before merging. Inspect generated IaC plan output before apply.",
    ArchLayer.TESTS:
        "Lowest risk — the fix only touches test code, not production behaviour. "
        "Verify the test still exercises the intended scenario and is not weakened.",
    ArchLayer.MOBILE:
        "Mobile change — test on both iOS and Android, multiple OS versions, and "
        "different screen sizes. App store review may be required for distribution.",
    ArchLayer.DATA_ML:
        "Model/data pipeline change — re-run training job and validate metrics on "
        "a hold-out set. Persist a model version snapshot before promotion.",
    ArchLayer.UNKNOWN:
        "Could not determine architecture layer — apply general caution and review "
        "thoroughly.",
}


# ============================================================================ #
# 5. FIX HINTS — guidance injected into the LLM prompt                          #
# ============================================================================ #

_FIX_HINTS: dict[ArchLayer, str] = {
    ArchLayer.FRONTEND:
        "Frontend code: focus on component state, props validation, hook "
        "dependencies, and async race conditions. Preserve the component's "
        "public API (props, exports). Avoid changes that break SSR/hydration. "
        "Keep accessibility (ARIA, keyboard nav) intact.",
    ArchLayer.BACKEND:
        "Backend code: focus on input validation, error handling, and concurrency. "
        "PRESERVE THE API CONTRACT — request/response shapes, status codes, and "
        "field names must remain unchanged unless they are the bug itself. "
        "Maintain backward compatibility for existing clients.",
    ArchLayer.DATABASE:
        "Database code: BE EXTREMELY CAREFUL — schema changes are often "
        "irreversible. Prefer additive migrations over destructive ones. "
        "Never DROP or ALTER columns containing data without explicit guard "
        "clauses. Always include a rollback strategy in the explanation. "
        "Wrap multi-statement migrations in a transaction where possible.",
    ArchLayer.INFRA:
        "Infrastructure code: focus on idempotency and reproducibility. "
        "Pin versions, avoid `latest` tags, prefer explicit env vars over "
        "implicit defaults. Document any new required permissions or secrets.",
    ArchLayer.TESTS:
        "Test code: fix the assertion, mock setup, or fixture — do NOT "
        "weaken the test to make it pass. If the test is correct, the "
        "production code is the real bug; flag that in the explanation.",
    ArchLayer.MOBILE:
        "Mobile code: test on both iOS and Android. Be mindful of platform-"
        "specific APIs and lifecycle methods. Avoid blocking the main thread.",
    ArchLayer.DATA_ML:
        "Data/ML code: preserve reproducibility — pin random seeds, dataset "
        "versions, and dependencies. Add a comment on any tuning parameters "
        "that are sensitive to numerical drift.",
    ArchLayer.UNKNOWN:
        "Architecture layer unknown — apply standard fix practices and "
        "minimise scope.",
}


# ============================================================================ #
# 6. FRAMEWORK DATABASE — 100+ frameworks across all layers                     #
# ============================================================================ #

_FRAMEWORK_PATTERNS: dict[str, tuple[list[str], ArchLayer]] = {
    # Frontend frameworks
    "React":        (["import React", "from 'react'", "from \"react\"", "useState", "ReactDOM"], ArchLayer.FRONTEND),
    "Next.js":      (["next/router", "next/link", "next.config", "getServerSideProps"], ArchLayer.FRONTEND),
    "Remix":        (["@remix-run/", "remix.config"], ArchLayer.FRONTEND),
    "Gatsby":       (["gatsby-config", "gatsby-node"], ArchLayer.FRONTEND),
    "Vue":          (["from 'vue'", "Vue.component", "createApp", "<template>"], ArchLayer.FRONTEND),
    "Nuxt":         (["nuxt.config", "@nuxt/", "useNuxtApp"], ArchLayer.FRONTEND),
    "Angular":      (["@angular/", "@Component", "@NgModule"], ArchLayer.FRONTEND),
    "Svelte":       (["from 'svelte'", "<script lang"], ArchLayer.FRONTEND),
    "SvelteKit":    (["@sveltejs/kit", "svelte.config"], ArchLayer.FRONTEND),
    "Solid":        (["from 'solid-js'", "createSignal"], ArchLayer.FRONTEND),
    "Qwik":         (["@builder.io/qwik", "component$"], ArchLayer.FRONTEND),
    "Astro":        (["from 'astro'", "astro.config"], ArchLayer.FRONTEND),
    "Lit":          (["from 'lit'", "@customElement"], ArchLayer.FRONTEND),
    "Alpine.js":    (["x-data=", "alpine.js"], ArchLayer.FRONTEND),
    "HTMX":         (["hx-get", "hx-post", "htmx.org"], ArchLayer.FRONTEND),

    # Backend frameworks — Python
    "FastAPI":      (["from fastapi", "FastAPI()", "@app.get"], ArchLayer.BACKEND),
    "Flask":        (["from flask", "Flask(__name__)", "@app.route"], ArchLayer.BACKEND),
    "Django":       (["from django", "django.db", "django.urls"], ArchLayer.BACKEND),
    "Starlette":    (["from starlette"], ArchLayer.BACKEND),
    "Quart":        (["from quart"], ArchLayer.BACKEND),
    "Sanic":        (["from sanic", "Sanic("], ArchLayer.BACKEND),
    "Tornado":      (["import tornado", "tornado.web"], ArchLayer.BACKEND),
    "aiohttp":      (["from aiohttp", "aiohttp.web"], ArchLayer.BACKEND),
    "Bottle":       (["from bottle"], ArchLayer.BACKEND),
    "Pyramid":      (["from pyramid"], ArchLayer.BACKEND),
    # Backend — Node.js
    "Express":      (["require('express')", "import express", "app.listen"], ArchLayer.BACKEND),
    "Koa":          (["from 'koa'", "import Koa"], ArchLayer.BACKEND),
    "Fastify":      (["import fastify", "from 'fastify'"], ArchLayer.BACKEND),
    "NestJS":       (["@nestjs/", "@Controller(", "@Injectable("], ArchLayer.BACKEND),
    "Hapi":         (["from '@hapi/hapi'", "Hapi.server"], ArchLayer.BACKEND),
    "AdonisJS":     (["@adonisjs/"], ArchLayer.BACKEND),
    "tRPC":         (["@trpc/server", "createTRPCRouter"], ArchLayer.BACKEND),
    # Backend — JVM
    "Spring Boot":  (["@SpringBootApplication", "spring.boot"], ArchLayer.BACKEND),
    "Spring MVC":   (["@RestController", "@RequestMapping"], ArchLayer.BACKEND),
    "Quarkus":      (["io.quarkus", "@QuarkusTest"], ArchLayer.BACKEND),
    "Micronaut":    (["io.micronaut"], ArchLayer.BACKEND),
    "Ktor":         (["import io.ktor", "embeddedServer"], ArchLayer.BACKEND),
    "Akka HTTP":    (["akka.http"], ArchLayer.BACKEND),
    "Play":         (["play.api"], ArchLayer.BACKEND),
    # Backend — Go
    "Gin":          (["gin.Default()", "gin.Engine"], ArchLayer.BACKEND),
    "Echo":         (["echo.New()", "labstack/echo"], ArchLayer.BACKEND),
    "Fiber":        (["fiber.New()", "gofiber/fiber"], ArchLayer.BACKEND),
    "Chi":          (["chi.NewRouter", "go-chi/chi"], ArchLayer.BACKEND),
    "Gorilla Mux":  (["gorilla/mux"], ArchLayer.BACKEND),
    "Buffalo":      (["gobuffalo/buffalo"], ArchLayer.BACKEND),
    # Backend — Rust
    "Actix":        (["actix_web", "use actix"], ArchLayer.BACKEND),
    "Rocket":       (["rocket::launch", "#[get(\""], ArchLayer.BACKEND),
    "Axum":         (["axum::Router", "use axum"], ArchLayer.BACKEND),
    "Warp":         (["warp::Filter"], ArchLayer.BACKEND),
    "Tide":         (["tide::new"], ArchLayer.BACKEND),
    "Tower":        (["tower::Service"], ArchLayer.BACKEND),
    # Backend — Ruby
    "Rails":        (["Rails.application", "ActiveRecord"], ArchLayer.BACKEND),
    "Sinatra":      (["Sinatra::Base"], ArchLayer.BACKEND),
    "Hanami":       (["Hanami::Application"], ArchLayer.BACKEND),
    # Backend — PHP
    "Laravel":      (["use Illuminate\\", "Artisan::"], ArchLayer.BACKEND),
    "Symfony":      (["use Symfony\\"], ArchLayer.BACKEND),
    "Slim":         (["Slim\\App"], ArchLayer.BACKEND),
    # Backend — Elixir
    "Phoenix":      (["use Phoenix", "Phoenix.Controller"], ArchLayer.BACKEND),
    "Plug":         (["Plug.Router"], ArchLayer.BACKEND),
    # Backend — .NET
    "ASP.NET":      (["[ApiController]", "Microsoft.AspNetCore"], ArchLayer.BACKEND),
    "Minimal API":  (["WebApplication.Create", "MapGet("], ArchLayer.BACKEND),

    # Database systems
    "PostgreSQL":   (["psycopg2", "asyncpg", "postgres://", "pg_dump", "pg_catalog"], ArchLayer.DATABASE),
    "MySQL":        (["mysql.connector", "mysql://", "pymysql", "mysqldump"], ArchLayer.DATABASE),
    "MariaDB":      (["mariadb://", "MariaDB"], ArchLayer.DATABASE),
    "SQLite":       (["import sqlite3", "sqlite://", "sqlite3.connect"], ArchLayer.DATABASE),
    "Oracle":       (["cx_Oracle", "oracledb"], ArchLayer.DATABASE),
    "SQL Server":   (["pyodbc", "mssql", "SQL Server"], ArchLayer.DATABASE),
    "MongoDB":      (["pymongo", "mongoose", "MongoClient"], ArchLayer.DATABASE),
    "Redis":        (["redis.Redis", "from redis", "import redis", "ioredis"], ArchLayer.DATABASE),
    "Cassandra":    (["from cassandra", "cassandra-driver"], ArchLayer.DATABASE),
    "Elasticsearch":(["elasticsearch", "from opensearch"], ArchLayer.DATABASE),
    "DynamoDB":     (["DynamoDB", "boto3.resource('dynamodb')"], ArchLayer.DATABASE),
    "CockroachDB":  (["cockroachdb"], ArchLayer.DATABASE),
    "Neo4j":        (["neo4j.GraphDatabase", "from neo4j"], ArchLayer.DATABASE),
    "Snowflake":    (["snowflake.connector"], ArchLayer.DATABASE),
    "BigQuery":     (["from google.cloud import bigquery"], ArchLayer.DATABASE),
    # ORMs
    "SQLAlchemy":   (["from sqlalchemy", "declarative_base"], ArchLayer.DATABASE),
    "Django ORM":   (["from django.db import models"], ArchLayer.DATABASE),
    "Tortoise":     (["from tortoise"], ArchLayer.DATABASE),
    "Peewee":       (["from peewee"], ArchLayer.DATABASE),
    "Prisma":       (["@prisma/client", "prisma generate"], ArchLayer.DATABASE),
    "TypeORM":      (["typeorm", "@Entity()"], ArchLayer.DATABASE),
    "Sequelize":    (["sequelize", "Sequelize"], ArchLayer.DATABASE),
    "Drizzle":      (["drizzle-orm"], ArchLayer.DATABASE),
    "Mongoose":     (["mongoose.Schema"], ArchLayer.DATABASE),
    "Hibernate":    (["org.hibernate", "@Entity"], ArchLayer.DATABASE),
    # Migration tools
    "Alembic":      (["alembic", "op.create_table"], ArchLayer.DATABASE),
    "Flyway":       (["flyway"], ArchLayer.DATABASE),
    "Liquibase":    (["liquibase"], ArchLayer.DATABASE),
    "Knex":         (["knex.schema"], ArchLayer.DATABASE),

    # Infra
    "Docker":       (["FROM ubuntu", "FROM python", "FROM node", "FROM golang", "RUN apt"], ArchLayer.INFRA),
    "Docker Compose":(["docker-compose", "version: '3", "services:"], ArchLayer.INFRA),
    "Kubernetes":   (["apiVersion:", "kind: Deployment", "kind: Service"], ArchLayer.INFRA),
    "Helm":         (["{{ .Values.", "{{ .Release.", "Chart.yaml"], ArchLayer.INFRA),
    "Kustomize":    (["kustomize", "patchesStrategicMerge"], ArchLayer.INFRA),
    "Terraform":    (["resource \"", "provider \"", "terraform {"], ArchLayer.INFRA),
    "Pulumi":       (["pulumi.export", "@pulumi/aws"], ArchLayer.INFRA),
    "AWS CDK":      (["aws-cdk-lib", "Stack ", "cdk.App"], ArchLayer.INFRA),
    "Ansible":      (["- hosts:", "ansible_become"], ArchLayer.INFRA),
    "Chef":         (["cookbook_file", "execute "], ArchLayer.INFRA),
    "Puppet":       (["class { '"], ArchLayer.INFRA),
    "GitHub Actions":(["uses: actions/", "runs-on:"], ArchLayer.INFRA),
    "GitLab CI":    (["stages:", ".gitlab-ci.yml"], ArchLayer.INFRA),
    "CircleCI":     ([".circleci/config"], ArchLayer.INFRA),
    "Jenkins":      (["pipeline {", "stages {", "Jenkinsfile"], ArchLayer.INFRA),
    "Travis CI":    ([".travis.yml"], ArchLayer.INFRA),
    "Drone":        (["pipeline:", ".drone.yml"], ArchLayer.INFRA),
    "Argo CD":      (["argoproj.io"], ArchLayer.INFRA),
    "Nix":          (["{ pkgs ? import"], ArchLayer.INFRA),

    # Test frameworks
    "pytest":       (["import pytest", "@pytest.fixture", "def test_"], ArchLayer.TESTS),
    "unittest":     (["import unittest", "TestCase"], ArchLayer.TESTS),
    "Jest":         (["describe(", "test(", "jest.config"], ArchLayer.TESTS),
    "Vitest":       (["from 'vitest'", "vitest.config"], ArchLayer.TESTS),
    "Mocha":        (["mocha", "describe(", "it("], ArchLayer.TESTS),
    "Cypress":      (["cy.visit", "cy.get", "cypress.config"], ArchLayer.TESTS),
    "Playwright":   (["@playwright/test", "page.goto"], ArchLayer.TESTS),
    "Selenium":     (["from selenium", "WebDriver"], ArchLayer.TESTS),
    "Puppeteer":    (["from 'puppeteer'", "puppeteer.launch"], ArchLayer.TESTS),
    "JUnit":        (["@Test", "import org.junit"], ArchLayer.TESTS),
    "TestNG":       (["import org.testng"], ArchLayer.TESTS),
    "RSpec":        (["RSpec.describe"], ArchLayer.TESTS),
    "Cucumber":     (["Feature:", "Scenario:"], ArchLayer.TESTS),

    # Mobile
    "React Native": (["from 'react-native'", "import { View"], ArchLayer.MOBILE),
    "Flutter":      (["import 'package:flutter", "Widget build("], ArchLayer.MOBILE),
    "SwiftUI":      (["import SwiftUI", "@State var"], ArchLayer.MOBILE),
    "UIKit":        (["import UIKit", "UIViewController"], ArchLayer.MOBILE),
    "Jetpack Compose":(["@Composable", "androidx.compose"], ArchLayer.MOBILE),
    "Android SDK":  (["AppCompatActivity", "androidx."], ArchLayer.MOBILE),
    "Ionic":        (["@ionic/"], ArchLayer.MOBILE),
    "Capacitor":    (["@capacitor/"], ArchLayer.MOBILE),
    "Expo":         (["expo-", "expo.json"], ArchLayer.MOBILE),
    "MAUI":         (["Microsoft.Maui"], ArchLayer.MOBILE),
    "Xamarin":      (["using Xamarin"], ArchLayer.MOBILE),

    # Data / ML
    "PyTorch":      (["import torch", "torch.nn"], ArchLayer.DATA_ML),
    "TensorFlow":   (["import tensorflow", "tf.keras"], ArchLayer.DATA_ML),
    "Keras":        (["from keras", "tf.keras"], ArchLayer.DATA_ML),
    "scikit-learn": (["from sklearn", "import sklearn"], ArchLayer.DATA_ML),
    "Hugging Face": (["from transformers", "AutoModel"], ArchLayer.DATA_ML),
    "JAX":          (["import jax", "jax.numpy"], ArchLayer.DATA_ML),
    "XGBoost":      (["from xgboost", "xgb.train"], ArchLayer.DATA_ML),
    "LightGBM":     (["from lightgbm"], ArchLayer.DATA_ML),
    "pandas":       (["import pandas", "import pandas as pd"], ArchLayer.DATA_ML),
    "NumPy":        (["import numpy", "import numpy as np"], ArchLayer.DATA_ML),
    "Polars":       (["import polars"], ArchLayer.DATA_ML),
    "PySpark":      (["from pyspark"], ArchLayer.DATA_ML),
    "Dask":         (["import dask"], ArchLayer.DATA_ML),
    "Airflow":      (["from airflow", "@dag"], ArchLayer.DATA_ML),
    "Prefect":      (["import prefect", "@flow"], ArchLayer.DATA_ML),
    "Dagster":      (["import dagster", "@asset"], ArchLayer.DATA_ML),
    "MLflow":       (["import mlflow"], ArchLayer.DATA_ML),
    "Kubeflow":     (["from kfp"], ArchLayer.DATA_ML),
    "DVC":          (["dvc.yaml"], ArchLayer.DATA_ML),
}


# ============================================================================ #
# 7. SUB-LAYER PATTERNS — 30+ specialised areas                                 #
# ============================================================================ #

_SUB_LAYER_PATTERNS: list[tuple[ArchLayer, re.Pattern, str]] = [
    # Backend sub-layers
    (ArchLayer.BACKEND, re.compile(r"@(app|router)\.(get|post|put|delete|patch)|@RestController|@RequestMapping|@(Get|Post|Put|Delete|Patch)Mapping"), "API endpoint"),
    (ArchLayer.BACKEND, re.compile(r"middleware|@app\.middleware|use\(\s*\w+\(", re.I), "Middleware"),
    (ArchLayer.BACKEND, re.compile(r"auth|login|jwt|session|oauth|password|hash|bcrypt|argon2", re.I), "Auth / Security"),
    (ArchLayer.BACKEND, re.compile(r"webhook|event_handler|signal|celery|queue|kafka|rabbitmq|sqs|pubsub", re.I), "Async / Event handler"),
    (ArchLayer.BACKEND, re.compile(r"BaseModel|pydantic|@dataclass|@Entity|class.*Model", re.I), "Data model / Schema"),
    (ArchLayer.BACKEND, re.compile(r"service|business_logic|use_case|usecase", re.I), "Business logic"),
    (ArchLayer.BACKEND, re.compile(r"repository|repo\.|dao", re.I), "Repository / DAO"),
    (ArchLayer.BACKEND, re.compile(r"graphql|@Resolver|gql`", re.I), "GraphQL resolver"),
    (ArchLayer.BACKEND, re.compile(r"grpc|protobuf|\.proto", re.I), "gRPC / protobuf"),
    (ArchLayer.BACKEND, re.compile(r"websocket|ws\.|socket\.io", re.I), "WebSocket"),
    (ArchLayer.BACKEND, re.compile(r"cron|scheduler|@scheduled|@periodic", re.I), "Scheduled job"),

    # Frontend sub-layers
    (ArchLayer.FRONTEND, re.compile(r"useState|useEffect|useReducer|useContext"), "React hook / state"),
    (ArchLayer.FRONTEND, re.compile(r"<.*Form|onSubmit|FormData|<form"), "Form handling"),
    (ArchLayer.FRONTEND, re.compile(r"fetch\(|axios\.|XMLHttpRequest|useQuery|useMutation"), "API client / data fetching"),
    (ArchLayer.FRONTEND, re.compile(r"router|Route|Link|navigate|useRouter", re.I), "Routing / navigation"),
    (ArchLayer.FRONTEND, re.compile(r"styled|css`|className|tailwind"), "Styling / UI"),
    (ArchLayer.FRONTEND, re.compile(r"redux|zustand|jotai|recoil|mobx|store\.", re.I), "State management"),
    (ArchLayer.FRONTEND, re.compile(r"i18n|t\(|useTranslation|locale", re.I), "Internationalisation"),
    (ArchLayer.FRONTEND, re.compile(r"<canvas|webgl|three\.js|d3\.", re.I), "Visualisation / canvas"),
    (ArchLayer.FRONTEND, re.compile(r"a11y|aria-|role=|alt=", re.I), "Accessibility"),

    # Database sub-layers
    (ArchLayer.DATABASE, re.compile(r"CREATE TABLE|ALTER TABLE", re.I), "Schema / DDL"),
    (ArchLayer.DATABASE, re.compile(r"migrations?/", re.I), "Migration"),
    (ArchLayer.DATABASE, re.compile(r"INSERT|UPDATE|DELETE|SELECT", re.I), "Query / DML"),
    (ArchLayer.DATABASE, re.compile(r"INDEX|UNIQUE|PRIMARY KEY|FOREIGN KEY", re.I), "Constraint / Index"),
    (ArchLayer.DATABASE, re.compile(r"VIEW|MATERIALIZED|CTE|WITH ", re.I), "View / CTE"),
    (ArchLayer.DATABASE, re.compile(r"TRIGGER|FUNCTION|PROCEDURE|STORED", re.I), "Trigger / Stored proc"),
    (ArchLayer.DATABASE, re.compile(r"pubsub|stream|change_data_capture|cdc", re.I), "CDC / Streaming"),

    # Infra sub-layers
    (ArchLayer.INFRA, re.compile(r"Dockerfile|FROM\s+\w"), "Container build"),
    (ArchLayer.INFRA, re.compile(r"docker-compose|compose\.ya?ml"), "Compose orchestration"),
    (ArchLayer.INFRA, re.compile(r"kind:\s*(Deployment|StatefulSet|DaemonSet)"), "Kubernetes workload"),
    (ArchLayer.INFRA, re.compile(r"kind:\s*(Service|Ingress|Route|Gateway)"), "Kubernetes networking"),
    (ArchLayer.INFRA, re.compile(r"kind:\s*(ConfigMap|Secret)"), "Kubernetes config"),
    (ArchLayer.INFRA, re.compile(r"\.github/workflows|gitlab-ci|Jenkinsfile|circleci|drone"), "CI/CD pipeline"),
    (ArchLayer.INFRA, re.compile(r"\.tf$|terraform|provider \""), "Infrastructure-as-code"),
    (ArchLayer.INFRA, re.compile(r"helm|values\.ya?ml|Chart\.yaml"), "Helm chart"),
    (ArchLayer.INFRA, re.compile(r"prometheus|grafana|alerting|alertmanager", re.I), "Monitoring / Alerting"),
    (ArchLayer.INFRA, re.compile(r"nginx|haproxy|envoy|traefik|caddy", re.I), "Load balancer / Proxy"),

    # Test sub-layers
    (ArchLayer.TESTS, re.compile(r"e2e|end_to_end|cypress|playwright", re.I), "End-to-end test"),
    (ArchLayer.TESTS, re.compile(r"integration", re.I), "Integration test"),
    (ArchLayer.TESTS, re.compile(r"unit|test_"), "Unit test"),
    (ArchLayer.TESTS, re.compile(r"perf|benchmark|load|stress", re.I), "Performance / load test"),
    (ArchLayer.TESTS, re.compile(r"snapshot", re.I), "Snapshot test"),
    (ArchLayer.TESTS, re.compile(r"smoke", re.I), "Smoke test"),

    # Mobile sub-layers
    (ArchLayer.MOBILE, re.compile(r"@Composable|jetpack"), "Android Compose UI"),
    (ArchLayer.MOBILE, re.compile(r"SwiftUI|@State|@Binding"), "iOS SwiftUI"),
    (ArchLayer.MOBILE, re.compile(r"Widget|StatefulWidget|StatelessWidget"), "Flutter widget"),
    (ArchLayer.MOBILE, re.compile(r"Push|Notification|FCM|APNS", re.I), "Push notification"),
    (ArchLayer.MOBILE, re.compile(r"AsyncStorage|SharedPreferences|UserDefaults|Hive", re.I), "Local storage"),
    (ArchLayer.MOBILE, re.compile(r"navigator|navigation\.|Navigator\."), "Navigation"),

    # Data/ML sub-layers
    (ArchLayer.DATA_ML, re.compile(r"\.fit\(|train_loop|train_step|model\.train", re.I), "Model training"),
    (ArchLayer.DATA_ML, re.compile(r"\.predict\(|inference|model\.eval", re.I), "Inference"),
    (ArchLayer.DATA_ML, re.compile(r"DataLoader|Dataset|tf\.data|batch_size", re.I), "Data pipeline"),
    (ArchLayer.DATA_ML, re.compile(r"feature_store|featurize|preprocess", re.I), "Feature engineering"),
    (ArchLayer.DATA_ML, re.compile(r"checkpoint|save_model|load_model", re.I), "Model serialization"),
    (ArchLayer.DATA_ML, re.compile(r"hyperparameter|tune|optuna|wandb\.config", re.I), "Hyperparameter tuning"),
]


# ============================================================================ #
# 8. LANGUAGE DETECTION — 50+ languages                                          #
# ============================================================================ #

_LANGUAGE_BY_EXT: dict[str, str] = {
    # Python
    ".py": "Python", ".pyx": "Python", ".pyi": "Python", ".pyw": "Python",
    # JS/TS
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    # Go / Rust / Zig / Nim / V / Crystal / D
    ".go": "Go", ".rs": "Rust", ".zig": "Zig", ".nim": "Nim", ".v": "V",
    ".cr": "Crystal", ".d": "D",
    # JVM
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala", ".sc": "Scala", ".sbt": "SBT",
    ".groovy": "Groovy", ".gradle": "Gradle",
    ".clj": "Clojure", ".cljs": "ClojureScript",
    # .NET
    ".cs": "C#", ".fs": "F#", ".fsi": "F#", ".fsx": "F#", ".vb": "VB.NET",
    # C / C++
    ".c": "C", ".h": "C/C++ Header",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++", ".hxx": "C++",
    # Apple
    ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C++",
    # Ruby / PHP / Perl
    ".rb": "Ruby", ".rbw": "Ruby", ".php": "PHP", ".phtml": "PHP",
    ".pl": "Perl", ".pm": "Perl",
    # Functional
    ".hs": "Haskell", ".lhs": "Haskell",
    ".ml": "OCaml", ".mli": "OCaml",
    ".elm": "Elm", ".purs": "PureScript",
    ".lisp": "Lisp", ".scm": "Scheme", ".rkt": "Racket",
    # BEAM
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hrl": "Erlang",
    # Frontend
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "Sass",
    ".less": "Less", ".styl": "Stylus", ".vue": "Vue", ".svelte": "Svelte",
    ".astro": "Astro",
    # Mobile
    ".dart": "Dart", ".xaml": "XAML",
    # Data / config
    ".sql": "SQL", ".graphql": "GraphQL", ".gql": "GraphQL", ".prisma": "Prisma Schema",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".json": "JSON", ".ini": "INI",
    ".tf": "HCL", ".hcl": "HCL",
    # Shell / scripting
    ".sh": "Bash", ".bash": "Bash", ".zsh": "Zsh", ".fish": "Fish",
    ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".lua": "Lua", ".tcl": "Tcl",
    # Other
    ".jl": "Julia", ".r": "R", ".R": "R", ".rmd": "R Markdown",
    ".matlab": "MATLAB", ".m": "MATLAB",   # noqa: collision with Objective-C handled above
    ".sol": "Solidity", ".cairo": "Cairo", ".move": "Move",
    ".asm": "Assembly", ".s": "Assembly",
    ".vala": "Vala", ".coffee": "CoffeeScript",
    # Data files
    ".ipynb": "Jupyter Notebook", ".rmd": "R Markdown",
    # Container / IaC
    ".dockerfile": "Dockerfile",
    # Build files
    ".cmake": "CMake", ".ninja": "Ninja", ".meson": "Meson",
    # Markup
    ".md": "Markdown", ".rst": "reStructuredText", ".tex": "LaTeX",
}

# Special filenames without standard extensions
_LANGUAGE_BY_FILENAME: dict[str, str] = {
    "Dockerfile":            "Dockerfile",
    "Containerfile":         "Containerfile",
    "Makefile":              "Makefile",
    "Rakefile":              "Ruby",
    "Gemfile":               "Ruby",
    "Procfile":              "YAML",
    "Vagrantfile":           "Ruby",
    "Jenkinsfile":           "Groovy",
    "build.gradle":          "Gradle",
    "pom.xml":               "Maven",
    "Cargo.toml":            "Rust",
    "go.mod":                "Go",
    "package.json":          "Node.js manifest",
    "pyproject.toml":        "Python project",
    "requirements.txt":      "Python deps",
    "composer.json":         "PHP",
    "mix.exs":               "Elixir",
    "rebar.config":          "Erlang",
    "stack.yaml":            "Haskell",
    "shard.yml":             "Crystal",
}


# ============================================================================ #
# 9. RUNTIME DETECTION — JVM, Node, Python interpreter, etc.                    #
# ============================================================================ #

_RUNTIME_HINTS: dict[str, str] = {
    "Python":          "CPython",
    "JavaScript":      "Node.js",
    "TypeScript":      "Node.js",
    "Java":            "JVM",
    "Kotlin":          "JVM",
    "Scala":           "JVM",
    "Clojure":         "JVM",
    "Groovy":          "JVM",
    "C#":              ".NET",
    "F#":              ".NET",
    "VB.NET":          ".NET",
    "Swift":           "Apple LLVM",
    "Objective-C":     "Apple LLVM",
    "Objective-C++":   "Apple LLVM",
    "Go":              "Go runtime",
    "Rust":            "Rust runtime",
    "Ruby":            "MRI/CRuby",
    "PHP":             "PHP-FPM",
    "Elixir":          "BEAM",
    "Erlang":          "BEAM",
    "Haskell":         "GHC",
    "Lua":             "Lua VM",
    "Dart":            "Dart VM",
    "R":               "R interpreter",
    "Julia":           "Julia runtime",
    "Solidity":        "EVM",
}


# ============================================================================ #
# 10. SEVERITY BOOSTS                                                            #
# ============================================================================ #

_SEVERITY_BOOSTS: dict[str, float] = {
    # Database — highest risk
    "Migration":              0.30,
    "Schema / DDL":           0.30,
    "Trigger / Stored proc":  0.25,
    "CDC / Streaming":        0.25,
    # Auth / security
    "Auth / Security":        0.30,
    # Infra
    "Kubernetes workload":    0.20,
    "Helm chart":             0.20,
    "Infrastructure-as-code": 0.20,
    "CI/CD pipeline":         0.20,
    "Container build":        0.15,
    "Load balancer / Proxy":  0.20,
    # API contracts
    "API endpoint":           0.15,
    "GraphQL resolver":       0.15,
    "gRPC / protobuf":        0.15,
    # ML
    "Model training":         0.15,
    "Hyperparameter tuning":  0.10,
}


# ============================================================================ #
# Detection helpers                                                              #
# ============================================================================ #

def _detect_framework(files: list[str], content: str) -> str:
    """Return the most likely framework, or empty string."""
    haystack = (content or "") + "\n" + "\n".join(files or [])
    if not haystack.strip():
        return ""
    for fw, (patterns, _layer) in _FRAMEWORK_PATTERNS.items():
        for p in patterns:
            if isinstance(p, str) and p in haystack:
                return fw
    return ""


def _detect_sub_layer(layer: ArchLayer, files: list[str], content: str) -> str:
    """Return the sub-layer (specific area within the main layer)."""
    haystack = "\n".join(files or []) + "\n" + (content or "")
    for lyr, pat, label in _SUB_LAYER_PATTERNS:
        if lyr == layer and pat.search(haystack):
            return label
    return ""


def _detect_language(files: list[str]) -> str:
    """Return the dominant programming language by file extension or filename."""
    if not files:
        return ""
    counts: dict[str, int] = {}
    for fp in files:
        # Try filename first (Dockerfile, Makefile, etc.)
        basename = fp.rsplit("/", 1)[-1]
        if basename in _LANGUAGE_BY_FILENAME:
            lang = _LANGUAGE_BY_FILENAME[basename]
            counts[lang] = counts.get(lang, 0) + 1
            continue
        # Then by extension
        for ext, lang in sorted(_LANGUAGE_BY_EXT.items(), key=lambda x: -len(x[0])):
            if fp.lower().endswith(ext):
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _detect_runtime(language: str) -> str:
    return _RUNTIME_HINTS.get(language, "")


def _build_tags(layer: ArchLayer, sub_layer: str, framework: str,
                language: str, cross_layers: list[str]) -> list[str]:
    """Build a list of normalised tags for downstream filtering / metrics."""
    tags = [layer.value.lower()]
    if sub_layer:
        tags.append(sub_layer.lower().replace(" / ", "_").replace(" ", "_"))
    if framework:
        tags.append(framework.lower().replace(" ", "_"))
    if language:
        tags.append(language.lower().replace(" ", "_"))
    for cl in cross_layers:
        tags.append(f"crosses_{cl.lower()}")
    return tags


# ============================================================================ #
# Main classifier                                                                #
# ============================================================================ #

def classify(
    affected_files: list[str] | None,
    code_context:   str = "",
    error_message:  str = "",
) -> LayerClassification:
    """Classify the architecture layer for the failing code.

    Combines path patterns (weight 3.0), content hints (2.0), and error message
    keywords (1.5). The highest-scoring layer wins; secondary layers with
    score ≥ 1.5 are reported as cross-layer involvement.
    """
    scores: dict[ArchLayer, float] = {layer: 0.0 for layer in ArchLayer}
    reasons: list[str] = []

    # 1. Path patterns
    for fp in affected_files or []:
        for layer, patterns in _PATH_PATTERNS.items():
            for pat in patterns:
                if pat.search(fp):
                    scores[layer] += 3.0
                    reasons.append(f"path `{fp}` matches `{pat.pattern[:30]}`")
                    break

    # 2. Content hints
    if code_context:
        for layer, hints in _CONTENT_HINTS.items():
            for hint in hints:
                if hint in code_context:
                    scores[layer] += 2.0
                    reasons.append(f"code contains `{hint}`")
                    break   # one hint per layer is enough

        # Strong cross-domain signals: certain imports definitively place
        # the file in a specific layer, overriding ambiguous path matches.
        _STRONG_OVERRIDES = [
            (ArchLayer.MOBILE,  ["from 'react-native'", "import 'package:flutter", "import SwiftUI", "import UIKit"], 3.0),
            (ArchLayer.DATA_ML, ["from airflow", "import mlflow", "import prefect", "import dagster", "from kfp"], 3.0),
        ]
        for layer, hints, boost in _STRONG_OVERRIDES:
            for hint in hints:
                if hint in code_context:
                    scores[layer] += boost
                    reasons.append(f"strong signal `{hint}` → {layer.value}")
                    break

    # 3. Error message hints
    if error_message:
        error_message = str(error_message)
        for layer, hints in _ERROR_HINTS.items():
            for hint in hints:
                if hint.lower() in error_message.lower():
                    scores[layer] += 1.5
                    reasons.append(f"error contains `{hint}`")
                    break

    # Pick the highest-scoring layer
    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    layer, raw_score = sorted_scores[0]

    # Cross-layer involvement
    cross_layers = [
        lyr.value for lyr, sc in sorted_scores[1:]
        if sc >= 1.5 and lyr not in (ArchLayer.UNKNOWN, layer)
    ]

    if raw_score == 0:
        layer = ArchLayer.UNKNOWN
        confidence = 0.0
        reason = "no path, content, or error patterns matched"
    else:
        confidence = min(1.0, raw_score / 5.0)
        reason = "; ".join(reasons[:3])

    framework  = _detect_framework(affected_files or [], code_context)
    sub_layer  = _detect_sub_layer(layer, affected_files or [], code_context)
    language   = _detect_language(affected_files or [])
    runtime    = _detect_runtime(language)
    severity   = _SEVERITY_BOOSTS.get(sub_layer, 0.0)

    fix_hint = _FIX_HINTS.get(layer, _FIX_HINTS[ArchLayer.UNKNOWN])
    if sub_layer:
        fix_hint = f"[{sub_layer}] {fix_hint}"
    if framework:
        fix_hint = f"Framework: {framework}. {fix_hint}"

    risk_note = _RISK_NOTES.get(layer, _RISK_NOTES[ArchLayer.UNKNOWN])
    if severity >= 0.25:
        risk_note = f"🚨 EXTRA CAUTION ({sub_layer}). {risk_note}"
    elif severity >= 0.15:
        risk_note = f"⚠️ Caution ({sub_layer}). {risk_note}"

    tags = _build_tags(layer, sub_layer, framework, language, cross_layers)

    return LayerClassification(
        layer=layer,
        confidence=round(confidence, 2),
        reason=reason,
        risk_note=risk_note,
        fix_hint=fix_hint,
        sub_layer=sub_layer,
        framework=framework,
        language=language,
        runtime=runtime,
        cross_layers=cross_layers,
        severity_boost=severity,
        tags=tags,
    )
