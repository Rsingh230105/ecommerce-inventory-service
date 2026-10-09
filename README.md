# Inventory Service

Inventory Service owns stock quantities. It exposes an HTTP API and consumes `ORDER_CREATED` events asynchronously from an SQS queue.

## Responsibilities

- Create, read, update, and decrease inventory under `/inventory`.
- Provide `/health`, `/ready`, and `/inventory/health` endpoints.
- Consume order events from SQS.
- Deduct stock and record the event ID in `processed_events` in one PostgreSQL transaction.
- Delete an SQS message only after successful database processing.
- Listen on port `8002`.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/inventory` | Create stock record |
| `GET` | `/inventory/{product_id}` | Read stock |
| `PUT` | `/inventory/{product_id}` | Set stock quantity |
| `POST` | `/inventory/{product_id}/decrease` | Decrease stock through the API |
| `GET` | `/health` | Process health check |
| `GET` | `/ready` | Database readiness check |

Open `/docs` on the service URL for interactive API documentation.

## SQS event processing

The consumer expects an `ORDER_CREATED` event containing `event_id`, `order_id`, `product_id`, and `quantity`. The current Order publisher includes these fields and also publishes price, total, and status. The consumer can parse either an SNS notification envelope or raw SNS-to-SQS delivery.

The service uses `event_id` as the primary key of `processed_events`. It locks the relevant inventory record, checks whether the event was already processed, decreases stock, writes the event record, and commits. A duplicate event is ignored. The SQS message is deleted only after the processing function returns successfully. Repeated failures are handled by the queue's redrive policy and DLQ.

## Run locally with Docker Compose

1. Copy `.env.example` to `.env` and set a local-only database password.
2. From this directory, run:

   ```powershell
   docker compose up --build
   ```

3. Open `http://localhost:8002/docs`.

The local PostgreSQL container maps to host port 5435; the API uses `postgres:5432` from inside Docker. The Compose file also expects the external Docker network `ecommerce-network` and an externally managed volume named `ecommerce_inventory_postgres_data`. Create/manage those resources before startup, or adjust a local-only Compose setup to use ordinary project-managed resources. Do not remove a volume containing data you need.

The API can run without an SQS consumer when `SQS_QUEUE_URL` is empty. To test real event consumption, set the queue URL and configure AWS credentials with least-privilege SQS receive/delete permissions.

## Configuration

See `.env.example`:

- `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`
- `AWS_REGION` (defaults in the application to `ap-south-1`)
- `SQS_QUEUE_URL`
- AWS credentials supplied by the standard AWS SDK credential chain (in AWS, the ECS task role)

Never commit `.env` or AWS credentials.

## Database migrations

The `processed_events` table is introduced by migration `1d3e4f5a6b7c`, after `0c227cc4a67a`. The inventory migration chain is owned by this service. Its container entrypoint runs `alembic upgrade head` before starting Uvicorn and the SQS consumer; for production, coordinate schema changes with rollout and avoid relying on multiple replicas racing migrations.

## Tests

From this directory:

```powershell
python -m pytest
```

The focused consumer idempotency tests use an in-memory SQLite database and test duplicate event handling, transaction rollback, and message acknowledgement order. Run the full suite to verify API and migration-related behavior as well.

## How it connects to the application

- ALB forwards `/inventory` and `/inventory/*` to port 8002.
- SNS order events are delivered to the Inventory SQS queue.
- The queue is configured with a DLQ and a redrive policy in Terraform.
- Inventory does not make synchronous calls back to Order Service.

## Next improvements

1. Add strict validation for event field types and sensible quantity bounds before database work.
2. Add visibility-timeout and consumer concurrency settings appropriate to real processing duration.
3. Add alarms and a documented replay/inspection process for the DLQ.
4. Decide and document how inventory reservation interacts with order cancellation, order updates, and insufficient stock. The current event processor reports a failure for missing/insufficient inventory; it does not cancel the order.

## CI and development deployment

The `CI and deploy (dev)` GitHub Actions workflow runs on pull requests and pushes to `dev`, and can be manually dispatched for an initial deployment or redeployment. It starts a disposable PostgreSQL 16 test database, runs the test suite, and verifies the Docker image builds.

On pushes or a manual run on branch `dev`, the AWS deploy job runs only when the repository Actions variable `AWS_ECR_ECS_DEPLOY_ENABLED` is set to the string `true`. Before enabling it:

1. Apply the development infrastructure so the ECR repository and Inventory ECS service exist.
2. Configure GitHub repository variables `AWS_REGION` (`ap-south-1`) and `AWS_DEPLOY_ROLE_ARN`.
3. Configure a dedicated AWS role to trust `token.actions.githubusercontent.com`, with audience `sts.amazonaws.com` and subject `repo:Rsingh230105/ecommerce-inventory-service:ref:refs/heads/dev`.
4. Limit that role to ECR push operations for `ecommerce-dev-inventory-service`, ECS describe/register/update operations for the dev cluster/service, and `iam:PassRole` only for the existing ECS task roles (condition `iam:PassedToService=ecs-tasks.amazonaws.com`). `ecr:GetAuthorizationToken` and task-definition registration may require `Resource: "*"`.
5. Set `AWS_ECR_ECS_DEPLOY_ENABLED=true`.

Each deployment publishes an immutable image tagged with the Git commit SHA, applies it to the latest Terraform task-definition family revision, and waits for the Inventory ECS service to become stable. Terraform ignores only the deployed task-definition revision so a later apply does not roll back a CI deployment; Terraform still owns the task-definition template and the service's other settings. If the job is not enabled, CI still runs but no AWS access or deployment is attempted. This workflow targets development only; it does not deploy production.
